from flask import (request, Blueprint, render_template, redirect, url_for, flash, jsonify, session)
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from app.vacation import vacation_bp
from app.models import User, Vacation, MonthLock, AltLeaveRecipient
from app import db
from app.models import now_kst
from sqlalchemy import or_, and_, func


# =======================================================
# 공용: 휴가 차감 맵
# =======================================================
DEDUCTION_MAP = {
    "연차": 1.0,
    "반차(전)": 0.5,
    "반차(후)": 0.5,
    "반반차": 0.25,
    "병가": 0,
    "예비군": 0,
    "탄력근무": 0,
    "근무자": 0,
    "토연차": 0.75,
    "일정": 0,
}

LEAVE_EXCLUDED_DEPARTMENTS = {
    "병동",
    "의료진",
}

def _get_alt_leave_balance(user_id: int) -> float:
    """
    대체연차 현재 잔여량

    총 부여:
        AltLeaveRecipient.user_id 기준

    총 사용:
        Vacation.is_alt == True 인 승인 휴가 기준

    잔여:
        총 부여 - 총 사용
    """

    user = User.query.get(user_id)

    if not user:
        return 0.0

    # ✅ 병동 / 의료진은 연차 시스템 제외
    if (user.department or "").strip() in LEAVE_EXCLUDED_DEPARTMENTS:
        return 0.0

    # -----------------------------
    # 1) 총 부여 대체연차
    # -----------------------------
    recipients = (
        AltLeaveRecipient.query
        .filter_by(user_id=user_id)
        .all()
    )

    granted = sum(
        float(r.add_days or 0)
        for r in recipients
    )

    # -----------------------------
    # 2) 실제 사용 대체연차
    # -----------------------------
    alt_vacations = (
        Vacation.query
        .filter(
            Vacation.approved == True,
            Vacation.is_alt == True,
            or_(
                Vacation.target_user_id == user_id,
                and_(
                    Vacation.target_user_id.is_(None),
                    Vacation.user_id == user_id
                )
            )
        )
        .all()
    )

    used = 0.0

    for vac in alt_vacations:
        used += DEDUCTION_MAP.get(
            (vac.type or "").strip(),
            0.0
        )

    return round(
        float(granted) - float(used),
        2
    )

# =======================================================
# ✅ 공용: 월 확정(잠금) 체크
# - 잠금된 달이면 "총관리자만" 수정/삭제 가능
# =======================================================
def _is_month_locked(dept: str, y: int, m: int) -> bool:
    lk = MonthLock.query.filter_by(department=dept, year=y, month=m).first()
    return bool(lk and lk.locked)

def _block_if_locked(dept: str, dt: date):
    # ✅ 잠금된 달은 총관리자만 변경 가능
    if _is_month_locked(dept, dt.year, dt.month) and (not current_user.is_superadmin):
        return jsonify({
            "status": "error",
            "message": "확정된 달입니다. 총관리자만 수정/삭제할 수 있습니다."
        }), 403
    return None

# =======================================================
# 휴가 추가 (연차, 반차, 토연차, 탄력근무 포함)
# =======================================================
@vacation_bp.route("/add", methods=["POST"])
@login_required
def add_event():
    try:
        data = request.get_json(silent=True) or {}
        if not data:
            return jsonify({"status": "error", "message": "데이터가 없습니다."}), 400

        start = (data.get("start") or "").strip()
        end = (data.get("end") or start).strip()
        vac_type = (data.get("type") or "연차").strip()
        
        # ✅ 탄력근무는 전용 API(/vacation/add_flex_event)로만 등록 허용
        if vac_type == "탄력근무":
            return jsonify({
                "status": "error",
                "message": "탄력근무는 전용 등록 기능으로만 추가할 수 있습니다."
            }), 200


        worker_names = data.get("worker_names", []) or []
        single_worker = data.get("worker_name")
        target_name = (data.get("target_name") or "").strip()  # 관리자가 선택한 직원명

        # ✅ 의료진/일정 추가 입력
        selected_dept = (data.get("department") or "").strip()
        memo = (data.get("memo") or "").strip()
        start_time = (data.get("start_time") or "").strip()  # "08:00"
        end_time = (data.get("end_time") or "").strip()      # "17:00"

        user_name = current_user.first_name or current_user.name or current_user.username
        user_dept = (current_user.department or "").strip()

        if not selected_dept:
            selected_dept = user_dept
            
        # ✅ 일반 사용자는 부서 파라미터 조작 불가 (본인 부서만 등록)
        if (not current_user.is_admin) and (not current_user.is_superadmin):
            if selected_dept != user_dept:
                return jsonify({"status": "error", "message": "다른 부서에는 등록할 수 없습니다."}), 403


        if not selected_dept:
            return jsonify({"status": "error", "message": "부서 정보가 없습니다. 캘린더를 새로고침 후 다시 시도해주세요."}), 200
        
        # 날짜 변환
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
        except Exception:
            return jsonify({"status": "error", "message": "날짜 형식 오류"}), 200

        if end_date < start_date:
            return jsonify({"status": "error", "message": "종료일이 시작일보다 빠릅니다."}), 200

        # =======================================================
        # ✅ '일정'은 의료진 부서에서만 허용
        # =======================================================
        if vac_type == "일정" and selected_dept != "의료진":
            return jsonify({"status": "error", "message": "‘일정’은 의료진 캘린더에서만 등록할 수 있습니다."}), 200

        # 일정은 하루만 허용 + 시간 필수
        if vac_type == "일정":
            if start_date != end_date:
                return jsonify({"status": "error", "message": "‘일정’은 하루만 선택해서 등록해주세요."}), 200
            if not start_time or not end_time:
                return jsonify({"status": "error", "message": "‘일정’은 시작/종료 시간이 필요합니다."}), 200
            if start_time >= end_time:
                return jsonify({"status": "error", "message": "종료 시간은 시작 시간보다 늦어야 합니다."}), 200

        # =======================================================
        # ✅ 월 잠금 체크: 선택 부서 기준(의료진 포함)
        # =======================================================
        blocked = _block_if_locked(selected_dept, start_date)
        if blocked:
            return blocked
        blocked = _block_if_locked(selected_dept, end_date)
        if blocked:
            return blocked

        weekday = start_date.weekday()  # 월=0 ~ 일=6

        # =======================================================
        #  🟦 여러 부서 전용 토요일 토연차 규칙 (선택부서 기준)
        # =======================================================
        TOYEONCHA_DEPTS = ["원무과", "물리치료실", "영상의학과", "심사과", "외래", "진단검사", "상담실", "도수"]

        if selected_dept in TOYEONCHA_DEPTS:
            # (1) 토연차는 토요일만 가능
            if vac_type == "토연차" and weekday != 5:
                return jsonify({
                    "status": "error",
                    "message": f"{selected_dept}의 '토연차'는 토요일에만 사용할 수 있습니다."
                }), 200

            # (2) 토요일은 토연차만 가능 (근무자는 예외)
            if weekday == 5 and vac_type not in ["토연차", "근무자"]:
                return jsonify({
                    "status": "error",
                    "message": f"{selected_dept}는 토요일에 '토연차'만 사용할 수 있습니다."
                }), 200
            
        # =======================================================
        #  🟦 근무자 지정 (근무자 → 항상 바로 승인)
        # =======================================================
        if vac_type == "근무자":
            names_to_add = worker_names if worker_names else [single_worker]
            added_count = 0

            for raw_name in names_to_add:
                name = (raw_name or "").strip()
                if not name:
                    continue

                # ✅ 근무하는 사람을 DB에서 정확히 찾기 (선택부서에서만)
                worker_user = User.query.filter(
                    func.trim(User.department) == selected_dept,
                    User.employment_status == "재직중",
                    or_(
                        func.trim(User.name) == name,
                        func.trim(User.first_name) == name
                    )
                ).first()

                if not worker_user:
                    # 필요하면 여기서 return error로 바꿔도 됨
                    continue

                worker_display = (worker_user.name or worker_user.first_name or worker_user.username or "").strip()

                # ✅ 중복 방지: "사람(id) + 날짜 + 근무자" 기준으로 체크
                exists = Vacation.query.filter_by(
                    department=selected_dept,
                    type="근무자",
                    start_date=start_date,
                    target_user_id=worker_user.id
                ).first()
                if exists:
                    continue

                # ✅ 핵심: 근무자 본인 id로 저장
                new_worker = Vacation(
                    user_id=worker_user.id,          # ✅ 근무자 본인
                    target_user_id=worker_user.id,   # ✅ 근무자 본인
                    name=worker_display,             # ✅ 표준 이름
                    department=selected_dept,
                    start_date=start_date,
                    end_date=start_date,             # ✅ 근무자는 하루 단위 권장
                    type="근무자",
                    approved=True
                )
                db.session.add(new_worker)
                added_count += 1

            db.session.commit()
            return jsonify({
                "status": "success",
                "message": f"{added_count}명 근무자 등록 완료"
            }), 200
        
        # =======================================================
        # ✅ 대상자 결정 (의료진/일반 부서 공통)
        # =======================================================
        # 기본: 본인
        target_user = current_user

        if selected_dept == "의료진":
            # 타부서 일반직원은 의료진 등록 불가
            if (user_dept != "의료진") and (not (current_user.is_admin or current_user.is_superadmin)):
                return jsonify({"status": "error", "message": "의료진 일정 등록 권한이 없습니다."}), 200

            # 타부서 관리자/총관리자는 의료진 선택 필수
            if target_name:
                target_user = User.query.filter(
                    func.trim(User.department) == "의료진",
                    User.employment_status == "재직중",
                    or_(
                        func.trim(User.first_name) == target_name,
                        func.trim(User.name) == target_name
                    )
                ).first()
                if not target_user:
                    return jsonify({"status": "error", "message": "선택한 의료진을 찾을 수 없습니다."}), 200
            else:
                # ✅ 의료진 소속이면 본인 등록 허용
                # ✅ 단, "근무자" 타입은 worker_names로 따로 처리하므로 여기서 막지 않음
                if user_dept != "의료진" and vac_type != "근무자":
                    return jsonify({"status": "error", "message": "의료진을 선택해주세요."}), 200
                target_user = current_user
        else:
            # 의료진이 아닌 부서에서 관리자가 target_name 지정하는 경우: 선택부서에서 찾기
            if target_name and (current_user.is_admin or current_user.is_superadmin):
                tu = User.query.filter(
                    func.trim(User.department) == selected_dept,
                    User.employment_status == "재직중",
                    or_(
                        func.trim(User.first_name) == target_name,
                        func.trim(User.name) == target_name
                    )
                ).first()
                if not tu:
                    return jsonify({"status": "error", "message": "대상 직원을 찾을 수 없습니다."}), 200
                target_user = tu

        # ✅ 휴직·퇴사 상태 직원 신규 일정 등록 차단
        target_status = (
            target_user.employment_status or "재직중"
        ).strip()

        if target_status != "재직중":
            return jsonify({
                "status": "error",
                "message": (
                    f"{target_user.name or target_user.username}님은 "
                    f"현재 '{target_status}' 상태이므로 "
                    "신규 휴가나 근무 일정을 등록할 수 없습니다."
                )
            }), 400

        # ✅ 표시용 이름 통일 (근무표/리스트에서 흔들리지 않게)
        display_name = (target_user.name or target_user.first_name or target_user.username or "").strip()


        


        # =======================================================
        #  🟦 휴가 중복 검사 (대상자 기준 + 부서 기준)
        # =======================================================
        overlap = Vacation.query.filter(
            Vacation.department == selected_dept,
            Vacation.type != "탄력근무",
            Vacation.start_date <= end_date,
            Vacation.end_date >= start_date,
            Vacation.target_user_id == target_user.id
        ).first()

        # 기존 데이터 중 target_user_id가 NULL로 저장된 예전 기록과도 충돌 체크(이름 기준 보완)
        if not overlap:
            overlap = Vacation.query.filter(
                Vacation.department == selected_dept,
                Vacation.type != "탄력근무",
                Vacation.start_date <= end_date,
                Vacation.end_date >= start_date,
                Vacation.name == display_name
            ).first()

        if overlap:
            return jsonify({
                "status": "error",
                "message": f"{target_user.name or target_user.username}님은 이미 같은 날짜에 '{overlap.type}' 일정이 있습니다."
            }), 200

        # =======================================================
        #  🟦 승인 여부 자동 결정 (의료진 규칙 반영)
        # =======================================================
        if selected_dept == "의료진":
            if vac_type == "일정":
                approved_status = True  # ✅ 일정은 즉시 등록
            elif current_user.is_superadmin:
                approved_status = True
            elif (user_dept == "의료진") and current_user.is_admin:
                approved_status = True
            else:
                approved_status = False  # ✅ 의료진 중간관리자 승인 대기
        else:
            approved_status = current_user.is_admin or current_user.is_superadmin

        # =======================================================
        #  🟦 휴가 등록
        # =======================================================
        # ✅ 등록자(작성자) / 대상자(일정 주인) 분리
        creator_id = current_user.id
        owner_id = target_user.id

        # ✅ 재발 방지 핵심: 일정의 "주인"을 user_id로도 저장
        new_event = Vacation(
            user_id=owner_id,          # ✅ 항상 주인
            target_user_id=owner_id,   # ✅ 항상 주인
            name=display_name,
            department=selected_dept,
            start_date=start_date,
            end_date=end_date,
            type=vac_type,
            approved=approved_status
        )


        # ✅ 일정이면 메모/시간 저장 (Vacation 모델 컬럼 있어야 함)
        if vac_type == "일정":
            new_event.memo = memo or None
            new_event.start_time = start_time
            new_event.end_time = end_time
        else:
            new_event.memo = None
            new_event.start_time = None
            new_event.end_time = None

        db.session.add(new_event)

        # =======================================================
        # ✅ 신규 휴가는 기본적으로 일반 연차
        #
        # 실제 잔여 연차는
        # 총 발생 연차 - 승인된 일반연차 사용량
        # 으로 계산하므로 remaining_days는 직접 변경하지 않는다.
        # =======================================================
        if hasattr(new_event, "is_alt"):
            new_event.is_alt = False

        db.session.commit()

        msg_name = display_name or (target_user.name or target_user.username)
        msg = f"{msg_name}님의 휴가가 등록되었습니다."
        if selected_dept == "의료진" and vac_type != "일정" and (not approved_status):
            msg = f"{msg_name}님의 휴가 신청이 등록되었습니다. (승인 대기)"

        return jsonify({
            "status": "success",
            "message": msg,
            "approved": approved_status
        }), 200

    except Exception as e:
        print("❌ /vacation/add 오류:", e)
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500


# =======================================================
# 휴가 승인
# =======================================================
@vacation_bp.route("/approve/<int:event_id>", methods=["POST"])
@login_required
def approve_event(event_id):
    if not (current_user.is_admin or current_user.is_superadmin):
        return jsonify({"status": "error", "message": "승인 권한이 없습니다."}), 403


    event = Vacation.query.get_or_404(event_id)

    # ✅ 승인된 휴가만 대체연차로 변경 가능
    if not bool(event.approved):
        return jsonify({
            "status": "error",
            "message": "승인된 휴가만 대체연차로 변경할 수 있습니다."
        }), 400
    
    # ✅ 중간관리자면 자기 부서만 승인 가능
    if current_user.is_admin and (not current_user.is_superadmin):
        if (event.department or "").strip() != (current_user.department or "").strip():
            return jsonify({"status": "error", "message": "다른 부서 일정은 승인할 수 없습니다."}), 403

    # ✅ 총관리자는 탄력근무 승인 금지 (원 설계 유지)
    if current_user.is_superadmin and event.type == "탄력근무":
        return jsonify({"status": "error", "message": "총관리자는 탄력근무를 처리할 수 없습니다."}), 403

    
    blocked = _block_if_locked(event.department, event.start_date)
    if blocked:
        return blocked
    event.approved = True
    db.session.commit()

    return jsonify({"status": "success", "message": "승인되었습니다."})


# =======================================================
# 휴가 삭제
# =======================================================
@vacation_bp.route("/delete/<int:event_id>", methods=["DELETE"])
@login_required
def delete_event(event_id):
    event = Vacation.query.get_or_404(event_id)
    blocked = _block_if_locked(event.department, event.start_date)
    if blocked:
        return blocked
    
    # ✅ 총관리자는 탄력근무를 삭제/처리 불가 (원 설계 유지)
    if current_user.is_superadmin and event.type == "탄력근무":
        return jsonify({"status": "error", "message": "총관리자는 탄력근무를 처리할 수 없습니다."}), 403

    # 🔹 이 일정이 "나"의 일정인지 user_id 기준으로 확인
    is_mine = (
        event.user_id == current_user.id
        or (getattr(event, "target_user_id", None) == current_user.id)
    )

    # 1) 내 일정이면 승인 여부와 상관없이 삭제 허용
    if is_mine:
        was_approved = bool(event.approved)


        db.session.delete(event)
        db.session.commit()
        return jsonify({
            "status": "success",
            "message": "승인된 휴가가 삭제되었습니다." if was_approved else "신청이 취소되었습니다."
        })

    # 2) 총관리자 / 중간관리자 삭제 권한 분리
    if current_user.is_superadmin:
        # (위에서 탄력근무는 이미 차단했지만, 안전하게 한 번 더)
        if event.type == "탄력근무":
            return jsonify({"status": "error", "message": "총관리자는 탄력근무를 처리할 수 없습니다."}), 403
        db.session.delete(event)
        db.session.commit()
        return jsonify({"status": "success", "message": "일정이 삭제되었습니다."}), 200

    if current_user.is_admin:
        # ✅ 중간관리자는 자기 부서 일정만 삭제 가능
        if (event.department or "").strip() != (current_user.department or "").strip():
            return jsonify({"status": "error", "message": "다른 부서 일정은 삭제할 수 없습니다."}), 403
        db.session.delete(event)
        db.session.commit()
        return jsonify({"status": "success", "message": "일정이 삭제되었습니다."}), 200


    # 3) 그 외에는 삭제 불가
    return jsonify({
        "status": "error",
        "message": "삭제 권한이 없습니다."
    }), 403

@vacation_bp.route("/convert_to_alt/<int:event_id>", methods=["POST"])
@login_required
def convert_to_alt(event_id):
    # ✅ 총관리자만
    if not current_user.is_superadmin:
        return jsonify({"status": "error", "message": "권한이 없습니다."}), 403

    event = Vacation.query.get_or_404(event_id)

    # ✅ 월 잠금 체크 (총관리자만 수정 가능 정책이면 _block_if_locked가 알아서 처리)
    blocked = _block_if_locked(event.department, event.start_date)
    if blocked:
        return blocked
    
    # ✅ 연차류만 대체연차로 전환 허용 (원하는 타입만)
    CONVERTIBLE_TYPES = {"연차", "반차(전)", "반차(후)", "반반차", "토연차"}
    if (event.type or "").strip() not in CONVERTIBLE_TYPES:
        return jsonify({"status": "error", "message": "대체연차로 변경할 수 없는 일정입니다."}), 400

    deduction = DEDUCTION_MAP.get(event.type or "", 0)
    if deduction <= 0:
        return jsonify({"status": "error", "message": "대체연차로 변경할 수 없는 일정입니다."}), 400

    if getattr(event, "is_alt", False):
        return jsonify({"status": "success", "message": "이미 대체연차로 처리된 휴가입니다."}), 200

    target_user = event.target_user or User.query.get(event.target_user_id) or User.query.get(event.user_id)
    if not target_user:
        return jsonify({"status": "error", "message": "대상 직원을 찾을 수 없습니다."}), 400

    # =======================================================
    # ✅ 연차 시스템 제외 부서 차단
    # =======================================================
    if (
        (target_user.department or "").strip()
        in LEAVE_EXCLUDED_DEPARTMENTS
    ):
        return jsonify({
            "status": "error",
            "message": "병동과 의료진은 연차/대체연차 시스템 대상이 아닙니다."
        }), 400


    # =======================================================
    # ✅ 실제 잔여 대체연차 계산
    # AltLeaveRecipient 총 부여 - Vacation.is_alt 총 사용
    # =======================================================
    alt_balance = _get_alt_leave_balance(
        target_user.id
    )

    if alt_balance < deduction:
        return jsonify({
            "status": "error",
            "message": (
                f"대체연차가 부족합니다. "
                f"(잔여 {alt_balance:.2f}일 / 필요 {deduction:.2f}일)"
            )
        }), 400


    # =======================================================
    # ✅ 일반 연차 → 대체연차로 전환
    # =======================================================
    event.is_alt = True

    # User.alt_leave는 더 이상 사용/차감하지 않음
    #
    # 직원관리·내정보에서
    # Vacation.is_alt=True가 자동으로 대체연차 사용량에 포함된다.

    db.session.commit()
    return jsonify({"status": "success", "message": "대체연차로 변경되었습니다."}), 200


# =====================
# 연차 승인 대기 목록 (관리자 전용)
# =====================
@vacation_bp.route("/pending_vacations")
@login_required
def pending_vacations():
    # 관리자 / 총관리자만 접근
    if not (current_user.is_admin or current_user.is_superadmin):
        flash("권한이 없습니다.", "error")
        return redirect(url_for("calendar.calendar_page"))

    pending = Vacation.query.filter_by(
        department=current_user.department,
        approved=False
    ).all()

    # 🔥 날짜 기준 정렬 (오름차순)
    pending = sorted(pending, key=lambda v: v.start_date)
    users = User.query.filter_by(
        department=current_user.department,
        employment_status="재직중",
    ).all()
    return render_template("pending_vacations.html", vacations=pending, users=users)


# =====================
# 휴가 승인 (연차 승인 대기 페이지용)
# =====================
@vacation_bp.route("/approve_vacation/<int:vac_id>", methods=["POST"])
@login_required
def approve_vacation(vac_id):
    if not (current_user.is_admin or current_user.is_superadmin):
        return jsonify({"status": "error", "message": "권한이 없습니다."}), 403

    vac = Vacation.query.get(vac_id)

    if not vac:
        return jsonify({"status": "error", "message": "휴가를 찾을 수 없습니다."}), 404
    
    # ✅ 중간관리자면 자기 부서만 승인 가능
    if current_user.is_admin and (not current_user.is_superadmin):
        if (vac.department or "").strip() != (current_user.department or "").strip():
            return jsonify({"status": "error", "message": "다른 부서 일정은 승인할 수 없습니다."}), 403

    # ✅ 총관리자는 탄력근무 승인 금지 (원 설계 유지)
    if current_user.is_superadmin and vac.type == "탄력근무":
        return jsonify({"status": "error", "message": "총관리자는 탄력근무를 처리할 수 없습니다."}), 403

    blocked = _block_if_locked(vac.department, vac.start_date)
    if blocked:
        return blocked

    vac.approved = True
    db.session.commit()
    return jsonify({
        "status": "success",
        "message": f"{vac.name}님의 휴가가 승인되었습니다."
    })

#------------------------------------------------------
# 탄력근무 추가 (중간관리자 전용)
#------------------------------------------------------
@vacation_bp.route("/add_flex_event", methods=["POST"])
@login_required
def add_flex_event():

    # ✅ 총관리자 / 중간관리자만 허용
    if not (current_user.is_admin or current_user.is_superadmin):
        return jsonify({"status": "error", "message": "탄력근무 등록 권한이 없습니다."}), 403
    
    data = request.get_json(silent=True) or {}

    target_name = (data.get("target_name") or "").strip()
    date_str = (data.get("date") or "").strip()
    hours = data.get("hours", None)

    if not target_name or not date_str or hours is None:
        return jsonify({"status": "error", "message": "필수 값 누락"}), 400

    # 🔥 문자열을 date 객체로 변환
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"status": "error", "message": "잘못된 날짜 형식"}), 400

    try:
        hours = float(hours)
    except:
        return jsonify({"status": "error", "message": "시간값 오류"}), 400

    # ✅ 총관리자면 payload의 department 기준 / 중간관리자는 본인 부서 고정
    selected_dept = (data.get("department") or "").strip()
    if not current_user.is_superadmin:
        selected_dept = (current_user.department or "").strip()

    if not selected_dept:
        return jsonify({"status": "error", "message": "부서 정보가 없습니다."}), 400

    # ✅ 타겟 직원 조회: 선택된 부서에서만 찾기 (동명이인/타부서 방지)
    target_user = User.query.filter(
        func.trim(User.department) == func.trim(selected_dept),
        User.employment_status == "재직중",
        or_(
            func.trim(User.first_name) == target_name,
            func.trim(User.name) == target_name,
        )
    ).first()

    if not target_user:
        return jsonify({"status": "error", "message": "직원 정보 없음(같은 부서인지 확인)"}), 400

    # ✅ 확정(잠금)된 달이면 등록 불가 (총관리자만 가능하도록 되어있다면 그대로 적용)
    blocked = _block_if_locked(selected_dept, date_obj)
    if blocked:
        return blocked

    # ✅ (선택) 같은날 중복 방지
    exists = Vacation.query.filter_by(
        target_user_id=target_user.id,
        department=target_user.department,
        type="탄력근무",
        start_date=date_obj,
        end_date=date_obj
    ).first()
    if exists:
        return jsonify({"status": "error", "message": "이미 해당 날짜에 탄력근무가 있습니다."}), 200
    
    display_name = (target_user.name or target_user.first_name or target_user.username or "").strip()
    
    flex_event = Vacation(
        user_id=target_user.id,
        target_user_id=target_user.id,
        name=display_name,
        department=target_user.department,
        type="탄력근무",
        start_date=date_obj,
        end_date=date_obj,
        hours=hours,
        is_flex=True,
        approved=True,  # 탄력근무 자동 승인
        created_at=now_kst()
    )

    db.session.add(flex_event)
    db.session.commit()

    return jsonify({"status": "success"}), 200
