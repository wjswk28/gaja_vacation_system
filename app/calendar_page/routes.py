# app/calendar/routes.py
import os
import json
from flask import (
    render_template,
    request,
    jsonify,
    session,
    current_app
)
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
import calendar
from app.calendar_page import calendar_bp
from app.models import Vacation, User, MonthLock, UserMonthConfirm
from app import db


# ======================================
#  메인 캘린더 페이지 (예전 로직 이식)
# ======================================
@calendar_bp.route("/")
@login_required
def calendar_page():
    """
    로그인 후 가장 먼저 들어오는 기본 페이지
    - master(총관리자)는 부서별 캘린더를 볼 수 있고
    - 일반 관리자/직원은 자기 부서만 본다.
    """

    user = current_user

    # 기본 부서 목록 (고정값)
    base_departments = [
        "의료진",
        "임원진",
        "수술실",
        "물리치료",
        "도수",
        "외래",
        "영상의학과",
        "원무과",
        "병동",
        "총무과",
        "심사과",
        "홍보",
        "진단검사",
        "상담실",
        "영양",
        "약제부",
    ]

    # ✅ 총관리자(마스터) 접근
    if user.is_superadmin:
        # URL 파라미터 → 세션 → 기본값 순서로 부서 결정
        selected_dept = request.args.get("dept")
        session_dept = session.get("department")

        # 초기 진입(선택X) 이거나 세션이 '관리자'인 경우 → 실제 부서 하나 자동 선택
        if not selected_dept and (not session_dept or session_dept == "관리자"):
            first_real_dept = (
                db.session.query(User.department)
                .filter(User.department.isnot(None), User.department != "관리자")
                .order_by(User.department.asc())
                .first()
            )
            current_dept = first_real_dept[0] if first_real_dept else "수술실"
            session["department"] = current_dept
        else:
            current_dept = selected_dept or session_dept or "수술실"
            session["department"] = current_dept

        # DB에 존재하는 실제 부서 목록 추출 (관리자 제외)
        db_departments = (
            db.session.query(User.department)
            .distinct()
            .filter(User.department != "관리자", User.department.isnot(None))
            .all()
        )
        db_dept_list = [d[0] for d in db_departments]

        # 고정 부서 + DB 부서 합쳐서 중복 제거 후 정렬
        dept_list = sorted(set(base_departments + db_dept_list))

    else:
        # ✅ 일반 사용자 또는 부서 관리자: (내 부서 + 의료진)만 선택 가능
        allowed = []
        if user.department:
            allowed.append(user.department)
        allowed.append("의료진")

        # ✅ 중복 제거(순서 유지)
        dept_list = []
        seen = set()
        for d in allowed:
            if d and d not in seen:
                dept_list.append(d)
                seen.add(d)

        # ✅ URL → 세션 → 기본값 순으로 선택 부서 결정(단, 허용된 부서만)
        selected_dept = request.args.get("dept") or session.get("department") or (user.department or "수술실")
        if selected_dept not in dept_list:
            selected_dept = user.department or "수술실"

        current_dept = selected_dept
        session["department"] = current_dept


    # ✅ 선택된 부서의 직원 목록 (모달에서 근무자 버튼에 사용)
    users = User.query.filter_by(department=current_dept).all()
    user_names = [u.first_name or u.name or u.username for u in users] or []
    user_dept = (user.department or "").strip() or "관리자"

    return render_template(
        "calendar.html",
        username=user.name or f"{user.last_name}{user.first_name}" or user.username,
        dept=current_dept,              # ✅ '선택한 캘린더 부서' (드롭다운 따라감)
        user_dept=user_dept,            # ✅ '로그인한 내 소속 부서' (고정 표시용)
        user_names=user_names,
        is_admin=user.is_admin,
        is_superadmin=user.is_superadmin,
        dept_list=dept_list,
    )


@calendar_bp.route("/events")
@login_required
def get_events():

    my_only = request.args.get("my") == "1"
    selected_dept = (
        request.args.get("dept")
        or session.get("department")
        or current_user.department
    )
    # ✅ 일반 사용자/부서관리자는 (내부서, 의료진)만 허용
    if not current_user.is_superadmin:
        allowed = {current_user.department, "의료진"}
        if selected_dept not in allowed:
            selected_dept = current_user.department

    # 1) 전체 이벤트 불러오기
    all_events = Vacation.query.all()
    
    # ✅ 내 이벤트인지 판별(일반휴가 기준)
    def _is_mine_event(ev):
        current_names = {
            (current_user.first_name or "").strip(),
            (current_user.name or "").strip(),
            (current_user.username or "").strip(),
        }
        return (
            getattr(ev, "target_user_id", None) == current_user.id
            or (getattr(ev, "target_user_id", None) in (None, 0) and getattr(ev, "user_id", None) == current_user.id)
            or ((getattr(ev, "name", "") or "").strip() in current_names)
        )


    # 2) 1차 필터링 (부서 / 탄력근무 특수 규칙)
    filtered = []
    for e in all_events:

        # -------------------------------
        # ✅ 탄력근무 특수 규칙 (권한/부서 고정)
        # -------------------------------
        if e.type == "탄력근무":

            # 1) 탄력근무의 소속 부서 판정 (DB department 우선, 없으면 대상자 부서로 보완)
            flex_dept = (getattr(e, "department", None) or "").strip()
            if not flex_dept and getattr(e, "target_user_id", None):
                tu = User.query.get(e.target_user_id)
                flex_dept = (tu.department if tu else "") or ""
            flex_dept = (flex_dept or "").strip()

            # ✅ 총관리자: 선택한 부서의 탄력근무는 조회 가능(등록 확인용)
            if current_user.is_superadmin:
                if selected_dept and flex_dept != (selected_dept or "").strip():
                    continue
                filtered.append(e)
                continue

            # 2) “선택한 캘린더 부서”가 내 부서가 아닐 때는 탄력근무는 안 섞이게 처리
            #    (의료진 캘린더에서 탄력근무가 떠버리는 것 방지)
            if (selected_dept or "").strip() != (current_user.department or "").strip():
                continue

            # 3) 중간관리자: 내 부서 탄력근무는 전체 조회
            if current_user.is_admin:
                if flex_dept == (current_user.department or "").strip():
                    filtered.append(e)
                continue

            # 4) 일반 사용자: 내 탄력근무만
            current_names = {
                (current_user.first_name or "").strip(),
                (current_user.name or "").strip(),
                (current_user.username or "").strip(),
            }
            if (
                getattr(e, "target_user_id", None) == current_user.id
                or (getattr(e, "user_id", None) == current_user.id)  # 레거시 보완
                or ((e.name or "").strip() in current_names)
            ):
                filtered.append(e)

            continue

        # -------------------------------
        # 일반 휴가 일정 (부서 기준 필터링)
        # -------------------------------
        # ✅ 부서 판정은 "대상자(target_user_id)" 우선
        owner_user = None
        if getattr(e, "target_user_id", None):
            owner_user = User.query.get(e.target_user_id)
        elif e.user_id:
            owner_user = User.query.get(e.user_id)

        # ✅ department는 DB 값 우선, 없으면 대상자 부서로만 fallback
        event_dept = (e.department or (owner_user.department if owner_user else "") or "").strip()

        # ✅ 부서가 끝내 판정 안되면 아예 제외(수술실로 잘못 섞이는 것 방지)
        if not event_dept:
            continue

        # ✅ superadmin: 선택 부서만
        if current_user.is_superadmin:
            if selected_dept and event_dept != selected_dept:
                continue
        else:
            # ✅ 일반/부서관리자: 선택한 부서(내부서 또는 의료진)만
            if event_dept != selected_dept:
                continue

        # ✅ [핵심] 일반사용자는 "남의 승인대기" 일정은 숨김
        # - approved=False 이면서 내 일정이 아니면 제외
        # - 근무자(type=근무자)는 휴가 신청개념이 아니라서 예외 처리(원하면 제거 가능)
        if (not current_user.is_admin) and (not current_user.is_superadmin):
            if (getattr(e, "approved", False) is False) and (e.type != "근무자") and (not _is_mine_event(e)):
                continue

        filtered.append(e)

    
    # 3) my_only 필터링 (⭐ 근무자 일정 포함해서 정확히 처리)
    if my_only:
        original = filtered
        filtered = []

        current_names = set([
            current_user.first_name,
            current_user.name,
            current_user.username
        ])

        for e in original:

            # ⭐ 근무자 일정 → name 값(근무자 이름)이 현재 사용자와 일치해야 내 근무로 판단
            if e.type == "근무자":
                if e.name in current_names:
                    filtered.append(e)
                continue

            # ⭐ 일반 휴가 일정
            is_mine = (
                (getattr(e, "target_user_id", None) == current_user.id)
                # ✅ 레거시(옛 데이터)만 user_id로 보완: target_user_id가 없을 때만 인정
                or (getattr(e, "target_user_id", None) in (None, 0) and e.user_id == current_user.id)
                or (e.name in current_names)
            )


            if is_mine:
                filtered.append(e)

    # -------------------------------
    # 4) 출력 변환
    # -------------------------------
    color_map = {
        "연차": "#ef4444",
        "반차": "#f97316",
        "반차(전)": "#f97316",
        "반차(후)": "#fb923c",
        "반반차": "#eab308",
        "병가": "#10b981",
        "예비군": "#6366f1",
        "탄력근무": "#6b7280",
        "근무자": "#38bdf8",
        "토연차": "#a855f7",
        "일정": "#16a34a",  # 초록(원하는 색으로 바꿔도 됨)

    }

    event_list = []
    for e in filtered:
        name = e.name or "이름없음"
        etype = e.type or "기타"
        approved = getattr(e, "approved", False)

        color = color_map.get(etype, "#22c55e") if approved else "#9ca3af"

        start = e.start_date.isoformat()

        # ✅ FullCalendar allDay 규칙: end는 "다음날"로 보내야 하루짜리도 정상 표시됨
        end = (e.end_date + timedelta(days=1)).isoformat()


        short_name = name[-2:] if len(name) > 2 else name

        # ✅ 일정 메모/시간 가져오기 (없으면 빈값)
        memo = (getattr(e, "memo", "") or "").strip()
        st = (getattr(e, "start_time", "") or "").strip()
        en = (getattr(e, "end_time", "") or "").strip()

        if etype == "탄력근무":
            hour_sign = "+" if (e.hours and e.hours > 0) else ""
            hour_display = f"{hour_sign}{e.hours}h"
            title_text = f"{short_name} (탄력 {hour_display})"

        elif etype == "일정":
            # ✅ 윤진(은행) 형태로 만들기 (메모 없으면 '일정')
            title_text = f"{short_name}({memo or '일정'})"

        else:
            title_text = f"{short_name} ({etype})"

        if not approved:
            title_text += " [신청]"

        event_list.append({
            "id": e.id,
            "title": title_text,
            "start": start,
            "end": end,
            "color": color,
            "type": etype,
            "approved": approved,
            "allDay": True,
            "memo": memo,
            "start_time": st,
            "end_time": en,
        })

    return jsonify(event_list)

def _get_lock(dept: str, year: int, month: int):
    return MonthLock.query.filter_by(department=dept, year=year, month=month).first()

def _is_locked(dept: str, year: int, month: int) -> bool:
    lk = _get_lock(dept, year, month)
    return bool(lk and lk.locked)

def _can_confirm_target_month(year: int, month: int) -> bool:
    """
    ✅ 확정 가능 기간:
      - '확정 대상 월(year, month)'의 29일 ~ (다음 달) 4일 까지 (포함)
      - 예) 2025년 11월 확정 가능: 2025-11-29 ~ 2025-12-04
    """
    today = date.today()

    # month의 마지막 날짜(2월 등 예외 대비)
    last_day = calendar.monthrange(year, month)[1]
    start_day = 29 if last_day >= 29 else last_day  # 2월(28일) 같은 달은 마지막 날부터

    start = date(year, month, start_day)

    # 다음 달 계산
    next_year, next_month = year, month + 1
    if next_month == 13:
        next_month = 1
        next_year += 1

    end = date(next_year, next_month, 4)

    return start <= today <= end


@calendar_bp.route("/users_by_dept")
@login_required
def users_by_dept():
    # ✅ 총관리자만 사용
    if not bool(getattr(current_user, "is_superadmin", False)):
        return jsonify({"users": []}), 403

    dept = (request.args.get("dept") or "").strip()
    if not dept:
        return jsonify({"users": []})

    users = User.query.filter_by(department=dept).all()

    def display_name(u: User) -> str:
        return (u.first_name or u.name or u.username or "").strip()

    # ✅ 정렬(이름 기준) - 원하면 join_date 기준으로 바꿔도 됨
    users_sorted = sorted(users, key=lambda u: display_name(u))

    return jsonify({
        "users": [
            {
                "id": u.id,
                "name": display_name(u),
                "is_admin": bool(getattr(u, "is_admin", False)),   # 중간관리자 포함 여부 확인용(표시는 선택)
            }
            for u in users_sorted
        ]
    })


@calendar_bp.route("/user_month_confirm/status")
@login_required
def user_month_confirm_status():
    year = int(request.args.get("year"))
    month = int(request.args.get("month"))

    row = UserMonthConfirm.query.filter_by(
        user_id=current_user.id, year=year, month=month
    ).first()

    return jsonify({
        "confirmed": bool(row),
        "confirmed_at": row.confirmed_at.isoformat() if (row and row.confirmed_at) else None,
    })


@calendar_bp.route("/user_month_confirm/confirm", methods=["POST"])
@login_required
def user_month_confirm():
    data = request.get_json(silent=True) or {}
    year = int(data.get("year"))
    month = int(data.get("month"))
    dept = (data.get("dept") or "").strip()  # 프론트에서 currentDept 보내줄 예정

    # ✅ 확정 가능 기간은 관리자 확정과 "동일"하게 사용
    if not _can_confirm_target_month(year, month):
        return jsonify({"status": "error", "message": "확정은 해당 월의 29일 ~ 다음 달 4일에만 가능합니다."}), 400

    # ✅ 일반사용자는 '내 부서 캘린더'에서만 개인확정 허용 (의료진 달력 보고 눌러버리는 실수 방지)
    if (not current_user.is_superadmin) and dept:
        my_dept = (current_user.department or "").strip()
        if dept != my_dept:
            return jsonify({"status": "error", "message": "개인 확정은 내 부서 캘린더에서만 가능합니다."}), 403

        # (선택) 이미 부서가 잠겼으면 개인확정 의미가 없으니 막기
        if _is_locked(dept, year, month):
            return jsonify({"status": "error", "message": "이미 확정(잠금)된 달입니다."}), 400

    row = UserMonthConfirm.query.filter_by(
        user_id=current_user.id, year=year, month=month
    ).first()

    if not row:
        row = UserMonthConfirm(user_id=current_user.id, year=year, month=month)

    # 재확정 시각 갱신(원하면 유지)
    row.confirmed_at = datetime.now()

    db.session.add(row)
    db.session.commit()

    return jsonify({"status": "success", "message": f"{year}년 {month}월 개인 확정 완료"})

@calendar_bp.route("/manager_month_confirm", methods=["POST"])
@login_required
def manager_month_confirm():
    # ✅ 중간관리자만 (총관리자는 제외하고 싶으면 아래 조건 유지)
    if not bool(getattr(current_user, "is_admin", False)) or bool(getattr(current_user, "is_superadmin", False)):
        return jsonify({"status": "error", "message": "부서 관리자만 가능합니다."}), 403

    data = request.get_json(silent=True) or {}
    year = int(data.get("year"))
    month = int(data.get("month"))
    dept = (data.get("dept") or "").strip()

    # ✅ 확정 가능 기간 동일 적용
    if not _can_confirm_target_month(year, month):
        return jsonify({"status": "error", "message": "확정은 해당 월의 29일 ~ 다음 달 4일에만 가능합니다."}), 400

    # ✅ 내 부서에서만 허용
    my_dept = (current_user.department or "").strip()
    if dept and dept != my_dept:
        return jsonify({"status": "error", "message": "내 부서 캘린더에서만 확정할 수 있습니다."}), 403

    # ✅ (중요) 여기서는 잠금/서명 기능 절대 하지 않음 → 개인확정만
    row = UserMonthConfirm.query.filter_by(user_id=current_user.id, year=year, month=month).first()
    if not row:
        row = UserMonthConfirm(user_id=current_user.id, year=year, month=month)

    row.confirmed_at = datetime.now()
    db.session.add(row)
    db.session.commit()

    return jsonify({"status": "success", "message": f"{year}년 {month}월 부서장 개인 확정 완료"})


@calendar_bp.route("/month_lock/status")
@login_required
def month_lock_status():
    dept = request.args.get("dept") or (session.get("department") or current_user.department)
    year = int(request.args.get("year"))
    month = int(request.args.get("month"))

    locked = _is_locked(dept, year, month)
    can_confirm = _can_confirm_target_month(year, month) and (not locked)

    return jsonify({
        "dept": dept,
        "year": year,
        "month": month,
        "locked": locked,
        "can_confirm": can_confirm,
    })

@calendar_bp.route("/month_lock/confirm", methods=["POST"])
@login_required
def month_lock_confirm():
    # ✅ 중간관리자(관리자)만 “확정” 가능
    # ✅ 총관리자는 확정 불가(확정/잠금과 역할 충돌 방지)
    if bool(getattr(current_user, "is_superadmin", False)):
        return jsonify({"status": "error", "message": "총관리자는 부서 확정을 할 수 없습니다."}), 403

    is_admin = bool(getattr(current_user, "is_admin", False)) or (
        str(getattr(current_user, "department", "")).strip() == "관리자"
    )

    if not is_admin:
        return jsonify({"status": "error", "message": "관리자만 확정할 수 있습니다."}), 403

    data = request.get_json(silent=True) or {}
    dept = (data.get("dept") or session.get("department") or current_user.department)
    year = int(data.get("year"))
    month = int(data.get("month"))

    # ✅ 29일 ~ 다음 달 4일 + 해당 년월에서만 확정 가능
    if not _can_confirm_target_month(year, month):
        return jsonify({"status": "error", "message": "확정은 해당 월의 29일 ~ 다음 달 4일에만 가능합니다."}), 400

    sig = (getattr(current_user, "signature_image", None) or "").strip()
    if not sig:
        return jsonify({"status": "error", "message": "서명이 등록되어 있어야 확정할 수 있습니다. (내정보에서 서명 등록 후 확정하세요)"}), 400

    lk = _get_lock(dept, year, month)
    if not lk:
        lk = MonthLock(department=dept, year=year, month=month)

    lk.locked = True
    lk.locked_at = datetime.now()
    lk.locked_by = current_user.id

    db.session.add(lk)
    db.session.commit()

    return jsonify({"status": "success", "message": f"{year}년 {month}월 확정 완료"})

@calendar_bp.route("/month_lock/unlock", methods=["POST"])
@login_required
def month_lock_unlock():
    # ✅ 총관리자만 “확정 해제” 가능
    if not bool(getattr(current_user, "is_superadmin", False)):
        return jsonify({"status": "error", "message": "총관리자만 확정 해제할 수 있습니다."}), 403

    data = request.get_json(silent=True) or {}
    dept = (data.get("dept") or session.get("department") or current_user.department)
    year = int(data.get("year"))
    month = int(data.get("month"))

    lk = _get_lock(dept, year, month)
    if not lk or not lk.locked:
        return jsonify({"status": "success", "message": "이미 확정 해제 상태입니다."})

    # ✅ 해제 처리
    lk.locked = False
    lk.locked_at = None
    lk.locked_by = None

    db.session.add(lk)
    db.session.commit()

    return jsonify({"status": "success", "message": f"{year}년 {month}월 확정 해제 완료"})

# ============================================
# ✅ 특정 날짜의 승인 대기 휴가 목록 조회 API
# ============================================
@calendar_bp.route("/pending_requests/<date>")
@login_required
def pending_requests(date):
    """
    날짜별 '승인 대기(approved=False)' 휴가 목록 조회
    front-end에서 승인 모달에 사용됨.
    """
    # ✅ 관리자(부서관리자)/총관리자만 승인대기 목록 조회 가능
    if not (getattr(current_user, "is_admin", False) or getattr(current_user, "is_superadmin", False)):
        return jsonify({"requests": []}), 403

    # 1) 날짜 파싱 (YYYY-MM-DD)
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"requests": []})

    # 2) 조회할 부서 결정 (권한 강제)
    req_dept = (request.args.get("dept") or "").strip()

    if current_user.is_superadmin:
        if not req_dept:
            return jsonify({"requests": []}), 400
        dept = req_dept
    else:
        dept = (current_user.department or "").strip()

    if not dept:
        return jsonify({"requests": []})

    # 3) 일단 날짜 + 승인대기만 조회
    pending_list = Vacation.query.filter(
        Vacation.start_date == day,
        Vacation.approved == False
    ).all()

    # 4) 응답에서 "부서"로 최종 필터링 (✅ 서버에서 섞임 차단)
    result = []
    for v in pending_list:
        v_dept = (getattr(v, "department", None) or "").strip()

        # department가 비어있는 레거시 데이터는 대상자/작성자 부서로 보완
        if not v_dept and getattr(v, "target_user_id", None):
            tu = User.query.get(v.target_user_id)
            v_dept = (tu.department if tu else "") or ""
        if not v_dept and getattr(v, "user_id", None):
            uu = User.query.get(v.user_id)
            v_dept = (uu.department if uu else "") or ""

        v_dept = (v_dept or "").strip()
        if v_dept != dept:
            continue

        result.append({
            "id": v.id,
            "name": v.name,
            "type": v.type,
            "created_at": v.created_at.strftime("%Y-%m-%d %H:%M") if v.created_at else "",
        })

    return jsonify({"requests": result})

# ===========================================
# ✅ 휴가 승인/거절 API 라우트
#--------------------------------------------
@calendar_bp.route("/approve_request/<int:event_id>", methods=["POST"])
@login_required
def approve_request(event_id):

    # ✅ 관리자만 승인 가능(총관리자 포함)
    if not (getattr(current_user, "is_admin", False) or getattr(current_user, "is_superadmin", False)):
        return jsonify({"status": "error", "message": "관리자만 승인할 수 있습니다."}), 403

    v = Vacation.query.get(event_id)
    if not v:
        return jsonify({"status": "error", "message": "일정을 찾을 수 없습니다."}), 404
    
    # ✅ 총관리자는 탄력근무 승인/처리 금지
    if getattr(current_user, "is_superadmin", False) and (v.type == "탄력근무"):
        return jsonify({"status": "error", "message": "총관리자는 탄력근무를 처리할 수 없습니다."}), 403

    # ✅ 부서 판정: DB department 우선 → target_user 부서 → user_id 부서
    dept = (getattr(v, "department", None) or "").strip()

    if not dept and getattr(v, "target_user_id", None):
        tu = User.query.get(v.target_user_id)
        dept = (tu.department if tu else "") or ""

    if not dept and getattr(v, "user_id", None):
        uu = User.query.get(v.user_id)
        dept = (uu.department if uu else "") or ""

    dept = (dept or "").strip()
    if not dept:
        return jsonify({"status": "error", "message": "부서를 판정할 수 없습니다."}), 400

    # ✅ 타부서 승인 차단 (총관리자만 예외)
    if not getattr(current_user, "is_superadmin", False):
        if dept != (current_user.department or "").strip():
            return jsonify({"status": "error", "message": "타부서 일정은 승인할 수 없습니다."}), 403

    # ✅ 확정된 달이면 총관리자만 승인 가능
    year = v.start_date.year
    month = v.start_date.month
    if _is_locked(dept, year, month) and (not current_user.is_superadmin):
        return jsonify({"status": "error", "message": "확정된 달입니다. 총관리자만 승인/수정할 수 있습니다."}), 403

    v.approved = True
    db.session.commit()
    return jsonify({"status": "approved"})


@calendar_bp.route("/reject_request/<int:event_id>", methods=["POST"])
@login_required
def reject_request(event_id):

    # ✅ 관리자만 삭제 가능(총관리자 포함)
    if not (getattr(current_user, "is_admin", False) or getattr(current_user, "is_superadmin", False)):
        return jsonify({"status": "error", "message": "관리자만 삭제할 수 있습니다."}), 403

    v = Vacation.query.get(event_id)
    if not v:
        return jsonify({"status": "error", "message": "일정을 찾을 수 없습니다."}), 404
    
    # ✅ 총관리자는 탄력근무 삭제/처리 금지
    if getattr(current_user, "is_superadmin", False) and (v.type == "탄력근무"):
        return jsonify({"status": "error", "message": "총관리자는 탄력근무를 처리할 수 없습니다."}), 403

    # ✅ 부서 판정: DB department 우선 → target_user 부서 → user_id 부서
    dept = (getattr(v, "department", None) or "").strip()

    if not dept and getattr(v, "target_user_id", None):
        tu = User.query.get(v.target_user_id)
        dept = (tu.department if tu else "") or ""

    if not dept and getattr(v, "user_id", None):
        uu = User.query.get(v.user_id)
        dept = (uu.department if uu else "") or ""

    dept = (dept or "").strip()
    if not dept:
        return jsonify({"status": "error", "message": "부서를 판정할 수 없습니다."}), 400

    # ✅ 타부서 삭제 차단 (총관리자만 예외)
    if not getattr(current_user, "is_superadmin", False):
        if dept != (current_user.department or "").strip():
            return jsonify({"status": "error", "message": "타부서 일정은 삭제할 수 없습니다."}), 403

    # ✅ 확정된 달이면 총관리자만 삭제 가능
    year = v.start_date.year
    month = v.start_date.month
    if _is_locked(dept, year, month) and (not current_user.is_superadmin):
        return jsonify({"status": "error", "message": "확정된 달입니다. 총관리자만 삭제/수정할 수 있습니다."}), 403

    db.session.delete(v)
    db.session.commit()
    return jsonify({"status": "deleted"})

# ============================================
# ✅ 공휴일 API 연동 라우트
# ============================================
# app/calendar_page/routes.py

import requests
from flask import current_app, jsonify, Blueprint

calendar_api_bp = Blueprint("calendar_api", __name__)

@calendar_api_bp.route("/calendar/api/holidays/<int:year>")
def get_holidays(year):
    service_key = current_app.config["HOLIDAY_API_KEY"]

    # 🔹 1) 캐시 파일 경로 설정
    cache_dir = current_app.config.get("HOLIDAY_CACHE_DIR")
    cache_path = None
    if cache_dir:
        cache_path = os.path.join(cache_dir, f"{year}.json")

    # 🔹 2) 캐시 파일이 있으면 그대로 반환
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            # 형식: {"holidays": [...], "holiday_names": {...}}
            return jsonify(cached)
        except Exception as e:
            current_app.logger.exception("Holiday cache read error (%s): %s", year, e)
            # 캐시 읽기 실패하면 그냥 API 다시 호출하도록 아래로 진행

    # 🔹 3) 캐시가 없거나 읽기 실패 → 기존 방식대로 API 호출
    url = (
        "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService"
        "/getHoliDeInfo"
        f"?serviceKey={service_key}&_type=json&solYear={year}&numOfRows=100"
    )

    holidays = []          # "YYYY-MM-DD" 리스트
    holiday_names = {}     # { "YYYY-MM-DD": "설날" } 형식

    try:
        res = requests.get(url, timeout=5)
        res.raise_for_status()
        data = res.json()

        body = data.get("response", {}).get("body", {})
        items_container = body.get("items")

        if not items_container or isinstance(items_container, str):
            items = []
        else:
            raw_items = items_container.get("item")
            if raw_items is None:
                items = []
            elif isinstance(raw_items, list):
                items = raw_items
            else:
                items = [raw_items]

        EXCLUDE_KEYWORDS = [
            "선거",
            "대체",
            "임시",
            "대체공휴일",
        ]
        RENAME_MAP = {
            "1월1일": "신정",
            "기독탄신일": "성탄절",
        }

        for item in items:
            if str(item.get("isHoliday", "N")) != "Y":
                continue

            name = str(item.get("dateName", "")).strip()
            name = RENAME_MAP.get(name, name)

            if any(kw in name for kw in EXCLUDE_KEYWORDS):
                continue

            date = str(item.get("locdate", ""))  # YYYYMMDD
            if len(date) != 8:
                continue

            ymd = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            holidays.append(ymd)
            holiday_names[ymd] = name

    except Exception as e:
        current_app.logger.exception("Holiday parse error %s: %s", year, e)

    # 🔁 4) API에서 아무 것도 못 받았으면, 고정 양력 공휴일 fallback
    if not holidays:
        FIXED_SOLAR_HOLIDAYS = {
            "0101": "신정",
            "0301": "3·1절",
            "0505": "어린이날",
            "0606": "현충일",
            "0815": "광복절",
            "1003": "개천절",
            "1009": "한글날",
            "1225": "성탄절",
        }

        for md, name in FIXED_SOLAR_HOLIDAYS.items():
            ymd = f"{year}-{md[:2]}-{md[2:]}"
            holidays.append(ymd)
            holiday_names[ymd] = name

        current_app.logger.info(
            "Holiday API empty for %s → using fixed solar holidays fallback.", year
        )

    # 🔹 5) 결과 만들기
    result = {"holidays": holidays, "holiday_names": holiday_names}

    # 🔹 6) 디스크 캐시에 저장 (실패해도 서비스는 정상)
    if cache_path:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception as e:
            current_app.logger.exception("Holiday cache write error (%s): %s", year, e)

    return jsonify(result)







