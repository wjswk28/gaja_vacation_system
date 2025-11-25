from flask import (
    render_template,
    request,
)
from flask_login import login_required
from datetime import datetime, date
from app.birthday import birthday_bp
from app.models import User


# ====================================================
# 🎂 생일자 조회 페이지
# ====================================================
@birthday_bp.route("/report", methods=["GET"])
@login_required
def birthday_report():

    # 선택한 월 (없으면 현재 월)
    month = request.args.get("month", type=int)
    if not month:
        month = datetime.now().month

    today = date.today()

    # --------------------------------------------------
    # 1) 생일자 목록 조회 (선택한 월만)
    # --------------------------------------------------
    results = []
    users = User.query.all()

    for u in users:
        if not u.birthday:
            continue

        try:
            bday = datetime.strptime(u.birthday, "%Y-%m-%d").date()
        except:
            continue

        # 선택한 월만 표시
        if bday.month != month:
            continue

        # 한국식 나이 계산
        try:
            age = today.year - bday.year + 1
        except:
            age = "-"

        results.append({
            "name": u.name or u.username,
            "birthday": u.birthday,
            "day": bday.day,
            "age": age,
            "department": u.department,
        })

    # 날짜 정렬
    results.sort(key=lambda x: x["day"])

    # --------------------------------------------------
    # 2) 병원/상조회 축하금 계산 (선택한 월만)
    # --------------------------------------------------
    birthday_members = []   # 병원 축하금(31일↑)
    union_members = []      # 상조회 축하금(6개월/3년↑)

    for u in users:
        if not u.birthday or not u.join_date:
            continue

        # 날짜 변환
        try:
            bday = datetime.strptime(u.birthday, "%Y-%m-%d").date()
            join = datetime.strptime(u.join_date, "%Y-%m-%d").date()
        except:
            continue

        # 선택한 월 생일자만 계산
        if bday.month != month:
            continue

        # 올해 기준 생일 날짜
        this_year_bday = bday.replace(year=today.year)
        if this_year_bday < today:
            this_year_bday = this_year_bday.replace(year=today.year + 1)

        # 입사일부터 생일까지의 기간
        days_until_birthday = (this_year_bday - join).days

        # 표기용 이름
        display_name = u.name or u.username or "이름없음"
        dept = u.department or "미지정"
        full_name = f"({dept}){display_name}"

        # 🏥 병원 생일축하금: 31일 이상 근무자
        if days_until_birthday >= 31:
            birthday_members.append(full_name)

        # ❤️ 상조회 축하금: 180일/1095일 기준
        if days_until_birthday >= 180:
            if days_until_birthday < 1095:
                amount = 50000
            else:
                amount = 70000

            union_members.append((full_name, amount))

    # 총액 계산 (해당 월 생일자만)
    hospital_total = len(birthday_members) * 30000
    union_total = sum(amount for _, amount in union_members)

    # --------------------------------------------------
    # 3) 템플릿 렌더링
    # --------------------------------------------------
    return render_template(
        "birthday_report.html",
        month=month,
        results=results,
        birthday_members=birthday_members,
        hospital_total=hospital_total,
        union_members=union_members,
        union_total=union_total,
    )
