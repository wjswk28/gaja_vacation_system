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
from datetime import datetime, date
import calendar
from app.calendar_page import calendar_bp
from app.models import Vacation, User, MonthLock
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
        # ✅ 일반 사용자 또는 부서 관리자
        current_dept = user.department or "수술실"
        dept_list = []

        # 세션과 동기화
        if session.get("department") != current_dept:
            session["department"] = current_dept

    # ✅ 선택된 부서의 직원 목록 (모달에서 근무자 버튼에 사용)
    users = User.query.filter_by(department=current_dept).all()
    user_names = [u.first_name or u.name or u.username for u in users] or []

    return render_template(
        "calendar.html",
        username=user.name or f"{user.last_name}{user.first_name}" or user.username,
        dept=current_dept,
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

    # 1) 전체 이벤트 불러오기
    all_events = Vacation.query.all()

    # 2) 1차 필터링 (부서 / 탄력근무 특수 규칙)
    filtered = []
    for e in all_events:

        # -------------------------------
        # 탄력근무는 부서 무시
        # -------------------------------
        if e.type == "탄력근무":

            # 관리자 → 모두 보임
            if current_user.is_admin or current_user.is_superadmin:
                filtered.append(e)
                continue

            # 직원 → 본인만
            if e.target_user_id == current_user.id or e.name == current_user.first_name:
                filtered.append(e)
                continue

            continue  # 나머지는 제외

        # -------------------------------
        # 일반 휴가 일정 (부서 기준 필터링)
        # -------------------------------
        user = User.query.get(e.user_id) if e.user_id else None
        if not user:
            continue

        # 총관리자 → URL 파라미터 기준 부서 필터
        if current_user.is_superadmin:
            if selected_dept and user.department != selected_dept:
                continue
        else:
            # 일반 관리자/직원 → 자기 부서만
            if user.department != current_user.department:
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
            if (
                e.user_id == current_user.id or
                e.target_user_id == current_user.id or
                e.name in current_names
            ):
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
    }

    event_list = []
    for e in filtered:
        name = e.name or "이름없음"
        etype = e.type or "기타"
        approved = getattr(e, "approved", False)

        color = color_map.get(etype, "#22c55e") if approved else "#9ca3af"

        start = e.start_date.isoformat()
        end = e.end_date.isoformat()

        short_name = name[-2:] if len(name) > 2 else name

        if etype == "탄력근무":
            hour_sign = "+" if (e.hours and e.hours > 0) else ""
            hour_display = f"{hour_sign}{e.hours}h"
            title_text = f"{short_name} (탄력 {hour_display})"
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
    is_admin = bool(getattr(current_user, "is_admin", False)) or (str(getattr(current_user, "department", "")).strip() == "관리자")
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

    # Vacation 모델에서 start_date로 필터링
    pending_list = Vacation.query.filter_by(
        start_date=date,
        approved=False
    ).all()

    result = []
    for v in pending_list:
        result.append({
            "id": v.id,
            "name": v.name,
            "type": v.type,
            "created_at": v.created_at.strftime("%Y-%m-%d %H:%M") if v.created_at else "",
        })

    return jsonify({"requests": result})


#--------------------------------------------
@calendar_bp.route("/approve_request/<int:event_id>", methods=["POST"])
@login_required
def approve_request(event_id):
    v = Vacation.query.get(event_id)
    if not v:
        return jsonify({"status": "error", "message": "일정을 찾을 수 없습니다."})

    # ✅ 확정된 달이면 총관리자만 승인 가능
    year = int(str(v.start_date)[:4])
    month = int(str(v.start_date)[5:7])
    dept = None
    u = User.query.get(v.user_id) if v.user_id else None
    dept = (u.department if u else (session.get("department") or current_user.department))

    if _is_locked(dept, year, month) and (not current_user.is_superadmin):
        return jsonify({"status": "error", "message": "확정된 달입니다. 총관리자만 승인/수정할 수 있습니다."}), 403

    v.approved = True
    db.session.commit()
    return jsonify({"status": "approved"})


@calendar_bp.route("/reject_request/<int:event_id>", methods=["POST"])
@login_required
def reject_request(event_id):
    v = Vacation.query.get(event_id)
    if not v:
        return jsonify({"status": "error", "message": "일정을 찾을 수 없습니다."})

    # ✅ 확정된 달이면 총관리자만 삭제 가능
    year = int(str(v.start_date)[:4])
    month = int(str(v.start_date)[5:7])
    u = User.query.get(v.user_id) if v.user_id else None
    dept = (u.department if u else (session.get("department") or current_user.department))

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







