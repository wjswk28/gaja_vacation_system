from flask import (request, Blueprint, render_template, redirect, url_for, flash, jsonify, session)
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from app.vacation import vacation_bp
from app.models import User, Vacation
from app import db
from app.models import now_kst


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
}


# =======================================================
# 휴가 추가 (연차, 반차, 토연차, 탄력근무 포함)
# =======================================================
@vacation_bp.route("/add", methods=["POST"])
@login_required
def add_event():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "데이터가 없습니다."}), 400

        start = data.get("start")
        end = data.get("end") or start
        vac_type = data.get("type", "연차")
        worker_names = data.get("worker_names", [])
        single_worker = data.get("worker_name")
        target_name = data.get("target_name")  # 관리자가 선택한 직원명

        user_name = current_user.first_name or current_user.name or current_user.username
        user_dept = current_user.department

        # 날짜 변환
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
        except Exception:
            return jsonify({"status": "error", "message": "날짜 형식 오류"}), 400

        weekday = start_date.weekday()  # 월=0 ~ 일=6

        # =======================================================
        #  🟦 여러 부서 전용 토요일 토연차 규칙
        # =======================================================
        TOYEONCHA_DEPTS = ["원무과", "물리치료실", "영상의학과", "심사과", "외래", "진단검사"]

        if user_dept in TOYEONCHA_DEPTS:

            # (1) 토연차는 토요일만 가능
            if vac_type == "토연차" and weekday != 5:
                return jsonify({
                    "status": "error",
                    "message": f"{user_dept}의 '토연차'는 토요일에만 사용할 수 있습니다."
                }), 200

            # (2) 토요일은 토연차만 가능 (근무자는 예외)
            if weekday == 5 and vac_type not in ["토연차", "근무자"]:
                return jsonify({
                    "status": "error",
                    "message": f"{user_dept}는 토요일에 '토연차'만 사용할 수 있습니다."
                }), 200

        # =======================================================
        #  🟦 근무자 지정 (근무자 → 항상 바로 승인)
        # =======================================================
        if vac_type == "근무자":
            names_to_add = worker_names if worker_names else [single_worker]
            added_count = 0

            for name in names_to_add:
                if not name:
                    continue

                exists = Vacation.query.filter_by(
                    name=name,
                    department=user_dept,
                    start_date=start_date,
                    type="근무자"
                ).first()

                if exists:
                    continue

                new_worker = Vacation(
                    user_id=current_user.id,
                    name=name,
                    department=user_dept,
                    start_date=start_date,
                    end_date=end_date,
                    type="근무자",
                    approved=True
                )
                db.session.add(new_worker)
                added_count += 1

            db.session.commit()
            return jsonify({
                "status": "success",
                "message": f"{added_count}명 근무자 등록 완료"
            })

        # =======================================================
        #  🟦 휴가 중복 검사
        # =======================================================
        if current_user.is_admin or current_user.is_superadmin:
            name_to_check = target_name or user_name
        else:
            name_to_check = user_name

        overlap = Vacation.query.filter(
            Vacation.name == name_to_check,
            Vacation.department == user_dept,
            Vacation.type != "탄력근무",
            Vacation.start_date <= end_date,
            Vacation.end_date >= start_date
        ).first()

        if overlap:
            return jsonify({
                "status": "error",
                "message": f"{name_to_check}님은 이미 같은 날짜에 '{overlap.type}' 일정이 있습니다."
            }), 200

        # =======================================================
        #  🟦 휴가 등록 (미승인/승인 여부 자동 결정)
        # =======================================================
        approved_status = current_user.is_admin or current_user.is_superadmin

        new_event = Vacation(
            user_id=current_user.id,
            name=target_name or user_name,
            department=user_dept,
            start_date=start_date,
            end_date=end_date,
            type=vac_type,
            approved=approved_status
        )

        # 관리자가 다른 직원에게 부여한 경우
        if target_name and (current_user.is_admin or current_user.is_superadmin):
            target_user = User.query.filter_by(name=target_name, department=user_dept).first()
            if target_user:
                new_event.target_user_id = target_user.id
        else:
            target_user = current_user

        db.session.add(new_event)

        # =======================================================
        # 🟦 연차 차감 (대체연차 우선)
        # =======================================================
        deduction = DEDUCTION_MAP.get(vac_type, 0)

        try:
            if deduction > 0:
                alt = float(target_user.alt_leave or 0)
                remain = float(target_user.remaining_days or 0)

                if alt >= deduction:
                    target_user.alt_leave = alt - deduction
                else:
                    leftover = deduction - alt
                    target_user.alt_leave = 0
                    target_user.remaining_days = max(-999, remain - leftover)

        except Exception as e:
            print("⚠️ 연차 차감 오류:", e)

        db.session.commit()

        return jsonify({
            "status": "success",
            "message": f"{target_user.name or target_user.username}님의 휴가가 등록되었습니다."
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
        return jsonify({"status": "error", "message": "승인 권한이 없습니다."})

    event = Vacation.query.get_or_404(event_id)
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

    # 🔹 이 일정이 "나"의 일정인지 user_id 기준으로 확인
    is_mine = (event.user_id == current_user.id)

    from app import db  # 파일 상단에 이미 있으면 이 줄은 생략해도 됨

    # 1) 내 일정이면 승인 여부와 상관없이 삭제 허용
    if is_mine:
        was_approved = bool(event.approved)

        db.session.delete(event)
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "승인된 휴가가 삭제되었습니다." if was_approved else "신청이 취소되었습니다."
        })

    # 2) 관리자 / 총관리자 → 어떤 일정이든 삭제 가능
    if current_user.is_superadmin or current_user.is_admin:
        db.session.delete(event)
        db.session.commit()
        return jsonify({
            "status": "success",
            "message": "일정이 삭제되었습니다."
        })

    # 3) 그 외에는 삭제 불가
    return jsonify({
        "status": "error",
        "message": "삭제 권한이 없습니다."
    }), 403


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
    users = User.query.filter_by(department=current_user.department).all()
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

    vac.approved = True
    db.session.commit()
    return jsonify({
        "status": "success",
        "message": f"{vac.name}님의 휴가가 승인되었습니다."
    })

#------------------------------------------------------
# 탄력근무 추가
#------------------------------------------------------
@vacation_bp.route("/add_flex_event", methods=["POST"])
@login_required
def add_flex_event():
    data = request.get_json()

    target_name = data.get("target_name")
    date_str = data.get("date")
    hours = data.get("hours")

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

    # 🔥 타겟 직원 조회 (first_name 기반)
    target_user = User.query.filter_by(first_name=target_name).first()
    if not target_user:
        return jsonify({"status": "error", "message": "직원 정보 없음"}), 400

    flex_event = Vacation(
        user_id=target_user.id,               # 🔥 반드시 저장
        target_user_id=target_user.id,        # 🔥 본인 기준 확인용
        name=target_user.first_name,          # 기존 유지 가능
        department=target_user.department,    # 🔥 반드시 저장
        type="탄력근무",
        start_date=date_obj,
        end_date=date_obj,
        hours=hours,
        is_flex=True,
        approved=True,                        # 탄력근무 자동 승인
        created_at=now_kst()
    )

    db.session.add(flex_event)
    db.session.commit()

    return jsonify({"status": "success"})



