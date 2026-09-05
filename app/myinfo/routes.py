from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash
)
from flask_login import login_required, current_user
from datetime import date, datetime, timedelta
from sqlalchemy import or_, and_

from app.myinfo import myinfo_bp
from app.models import User, Vacation, AltLeaveRecipient
from app.leave_utils import calculate_annual_leave

# ====================================================
# 연차 / 대체연차 시스템 제외 부서
# ====================================================
LEAVE_EXCLUDED_DEPARTMENTS = {
    "병동",
    "의료진",
}

# ====================================================
# 내 정보 페이지
# ====================================================
@myinfo_bp.route("/", methods=["GET", "POST"])
@login_required
def myinfo():

    user = current_user

    # ------------------------------------------------
    # 1) POST → 주소 또는 비밀번호 수정
    # ------------------------------------------------
    if request.method == "POST":
        new_address = (request.form.get("address") or "").strip()
        new_password = (request.form.get("password") or "").strip()
        new_phone = (request.form.get("phone") or "").strip()

        if new_address:
            user.address = new_address
        if new_password:
            user.password = new_password  # 운영 시 해시 추천
        if new_phone:
            user.phone = new_phone

        user_name = user.name or user.username
        flash(f"{user_name}님의 정보가 수정되었습니다.", "success")
        from app import db
        db.session.commit()

        return redirect(url_for("myinfo.myinfo"))

    # ------------------------------------------------
    # 2) 연차 / 대체연차 계산
    #    ✅ 직원관리 페이지와 동일한 기준
    # ------------------------------------------------
    today = date.today()

    leave_excluded = (
        (user.department or "").strip()
        in LEAVE_EXCLUDED_DEPARTMENTS
    )

    # 휴가 종류별 차감 일수
    weights = {
        "연차": 1.0,
        "반차(전)": 0.5,
        "반차(후)": 0.5,
        "반반차": 0.25,
        "토연차": 0.75,
    }


    # ====================================================
    # 병동 / 의료진
    # - 직원 등록과 일반 정보만 사용
    # - 연차 시스템에서는 제외
    # ====================================================
    if leave_excluded:

        total_leave = 0.0
        used_before = 0.0

        used_after = 0.0
        used_total = 0.0

        alt_used_total = 0.0
        annual_used_total = 0.0

        total_alt_leave = 0.0
        alt_left = 0.0
        annual_left = 0.0

        my_alt_logs = []


    # ====================================================
    # 일반 연차 시스템 대상 부서
    # ====================================================
    else:

        # ---------------------------------------------
        # 1) 총 발생 일반 연차
        # ---------------------------------------------
        total_leave = float(
            calculate_annual_leave(user.join_date) or 0
        )

        # 시스템 도입 전 사용 연차
        # → 대체연차인지 구분할 수 없으므로 일반 연차 사용으로 처리
        used_before = float(
            user.used_before_system or 0.0
        )


        # ---------------------------------------------
        # 2) 승인된 휴가 조회
        #
        # target_user_id가 있으면 그것을 우선 기준으로 사용
        # 예전 데이터는 target_user_id가 NULL일 때만 user_id 보완
        # ---------------------------------------------
        approved_events = (
            Vacation.query
            .filter(
                Vacation.approved.is_(True),
                Vacation.type.in_(weights.keys()),
                or_(
                    Vacation.target_user_id == user.id,
                    and_(
                        Vacation.target_user_id.is_(None),
                        Vacation.user_id == user.id
                    )
                )
            )
            .all()
        )


        # ---------------------------------------------
        # 3) 사용량 계산
        # ---------------------------------------------
        used_after = 0.0
        alt_used_total = 0.0

        for v in approved_events:

            vac_type = (v.type or "").strip()
            days = float(
                weights.get(vac_type, 0.0)
            )

            used_after += days

            # ✅ 대체연차로 실제 지정된 휴가만
            if bool(getattr(v, "is_alt", False)):
                alt_used_total += days


        used_after = round(
            used_after,
            2
        )

        # 전체 사용량
        used_total = round(
            used_before + used_after,
            2
        )

        # 대체연차 사용량
        alt_used_total = round(
            alt_used_total,
            2
        )

        # 일반연차 사용량
        #
        # 시스템 도입 전 사용량은 모두 일반연차로 포함되고,
        # is_alt=True인 것만 전체 사용량에서 제외
        annual_used_total = round(
            used_total - alt_used_total,
            2
        )


        # ---------------------------------------------
        # 4) 총 발생 대체연차
        #
        # ✅ 이름 검색 완전 제거
        # ✅ AltLeaveRecipient.user_id 기준
        # ---------------------------------------------
        recipients = (
            AltLeaveRecipient.query
            .filter_by(user_id=user.id)
            .all()
        )

        total_alt_leave = round(
            sum(
                float(r.add_days or 0)
                for r in recipients
            ),
            2
        )


        # ---------------------------------------------
        # 5) 대체연차 지급 이력
        # ---------------------------------------------
        my_alt_logs = []

        for recipient in recipients:

            log = recipient.log

            if not log:
                continue

            my_alt_logs.append({
                "grant_date": log.grant_date,
                "apply_date": log.apply_date,
                "reason": log.reason,
                "add_days": float(
                    recipient.add_days or 0
                ),
                "granted_by": log.granted_by,
                "department_summary": log.department_summary,
            })


        # 최근 지급/적용일 순
        my_alt_logs.sort(
            key=lambda row: (
                row["apply_date"] or date.min,
                row["grant_date"] or datetime.min,
            ),
            reverse=True,
        )


        # ---------------------------------------------
        # 6) 최종 잔여량
        # ---------------------------------------------

        # 대체연차
        alt_left = round(
            float(total_alt_leave)
            - float(alt_used_total),
            2
        )

        # 일반연차
        annual_left = round(
            float(total_leave)
            - float(annual_used_total),
            2
        )

    # ------------------------------------------------
    # 4) 입사 D-day 계산
    # ------------------------------------------------
    dday = 0
    if user.join_date:
        try:
            jd = (
                datetime.strptime(user.join_date, "%Y-%m-%d").date()
                if isinstance(user.join_date, str)
                else user.join_date
            )
            dday = (today - jd).days
        except:
            dday = 0

    # ------------------------------------------------
    # 6) 템플릿 전달 데이터
    # ------------------------------------------------
    # full name
    if user.last_name and user.first_name:
        full_name = f"{user.last_name}{user.first_name}"
    else:
        full_name = user.name or user.username

    view = {
        "id": user.username,
        "username": user.username,
        "name": full_name,
        "birth": user.birthday,
        "address": user.address,
        "phone": user.phone,  # ✅ 추가
        "join_date": user.join_date,
        "dday": dday,
        "total_leave": total_leave,
        "used_leave": used_total,
        "remaining_leave": annual_left,
        "total_alt_leave": total_alt_leave,
        "alt_left": alt_left,
        "department": user.department,
    }

    return render_template("myinfo.html", user=view, logs=my_alt_logs)
