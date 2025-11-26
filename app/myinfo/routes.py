from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash
)
from flask_login import login_required, current_user
from datetime import date, datetime, timedelta
from app.myinfo import myinfo_bp
from app.models import User, Vacation, AltLeaveLog
from app.leave_utils import calculate_annual_leave


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

        if new_address:
            user.address = new_address
        if new_password:
            user.password = new_password  # 운영 시 해시 추천

        user_name = user.name or user.username
        flash(f"{user_name}님의 정보가 수정되었습니다.", "success")
        from app import db
        db.session.commit()

        return redirect(url_for("myinfo.myinfo"))

    # ------------------------------------------------
    # 2) 연차 계산(직원관리와 동일)
    # ------------------------------------------------
    today = date.today()

    # 총 발생 연차
    total_leave = calculate_annual_leave(user.join_date)

    # 승인된 휴가만 적용(과거+미래)
    weights = {
        "연차": 1.0,
        "반차(전)": 0.5,
        "반차(후)": 0.5,
        "반반차": 0.25,
        "토연차": 0.75,
    }

    used_before = float(user.used_before_system or 0.0)

    approved_events = Vacation.query.filter(
        ((Vacation.user_id == user.id) | (Vacation.target_user_id == user.id)),
        Vacation.approved.is_(True),
        Vacation.type.in_(weights.keys())
    ).all()

    used_after = sum(weights.get(v.type, 0) for v in approved_events)
    used_total = round(used_before + used_after, 2)

    # ------------------------------------------------
    # 3) 대체연차 계산 (직원관리와 동일)
    # ------------------------------------------------
    name_key = (user.first_name or user.name or user.username or "").strip()

    logs_all = AltLeaveLog.query.order_by(AltLeaveLog.grant_date.desc()).all()

    my_alt_logs = [
        log for log in logs_all
        if (log.department_summary or "").find(name_key) != -1
    ]

    total_alt_leave = sum(log.add_days for log in my_alt_logs)
    alt_total = float(total_alt_leave)

    # 대체연차 → 연차 차감 로직
    if used_total <= alt_total:
        alt_left = round(alt_total - used_total, 2)
        annual_left = float(total_leave)
    else:
        remain_use = used_total - alt_total
        alt_left = 0.0
        annual_left = round(float(total_leave) - remain_use, 2)

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
