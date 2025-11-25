# app/altleave/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from app.models import User, AltLeaveLog

altleave_bp = Blueprint("altleave", __name__, url_prefix="/altleave")


# ==========================
# 대체연차 부여 페이지
# ==========================
@altleave_bp.route("/", methods=["GET", "POST"])
@login_required
def grant_alt_leave():

    # 총관리자만 접근 가능
    if not current_user.is_superadmin:
        flash("이 기능은 총관리자만 사용할 수 있습니다.", "error")
        return redirect(url_for("employee.employee_list"))

    # 부서별 직원 정렬
    users = (
        User.query.filter(User.is_superadmin == False)
        .order_by(User.department, User.name)
        .all()
    )

    users_by_dept = {}
    for u in users:
        dept = u.department or "기타"
        users_by_dept.setdefault(dept, []).append(u)

    # ------------------------
    # POST : 대체연차 부여
    # ------------------------
    if request.method == "POST":
        ids_str = request.form.get("user_ids", "")
        add_days = float(request.form.get("add_days", 0))
        reason = request.form.get("reason", "").strip()
        apply_date = request.form.get("apply_date")

        if not ids_str:
            flash("직원을 선택하세요.", "error")
            return redirect(url_for("altleave.grant_alt_leave"))

        try:
            apply_date = datetime.strptime(apply_date, "%Y-%m-%d").date()
        except:
            flash("적용일자를 올바르게 입력하세요.", "error")
            return redirect(url_for("altleave.grant_alt_leave"))

        user_ids = [int(x) for x in ids_str.split(",") if x.isdigit()]
        if not user_ids or add_days <= 0:
            flash("직원과 일수를 올바르게 입력하세요.", "error")
            return redirect(url_for("altleave.grant_alt_leave"))

        # 대상자 불러오기
        selected_users = User.query.filter(User.id.in_(user_ids)).all()

        # 부서별 이름 요약 만들기
        dept_map = {}
        for user in selected_users:
            dept_map.setdefault(user.department or "기타", []).append(user.name)

        dept_summary = ", ".join(
            [f"{dept}({', '.join(names)})" for dept, names in dept_map.items()]
        )

        # 1) 각 사용자에게 alt_leave 부여
        for u in selected_users:
            u.alt_leave = (u.alt_leave or 0) + add_days

        # 2) 로그는 지급건 1건만 생성
        log = AltLeaveLog(
            apply_date=apply_date,
            reason=reason,
            add_days=add_days,
            granted_by=current_user.name,
            department_summary=dept_summary
        )
        db.session.add(log)
        db.session.commit()

        flash(f"{len(selected_users)}명에게 대체연차 {add_days}일을 부여했습니다.", "success")
        return redirect(url_for("altleave.grant_alt_leave"))

    # ------------------------
    # GET: 페이지 렌더링
    # ------------------------
    logs = AltLeaveLog.query.order_by(AltLeaveLog.grant_date.desc()).all()

    return render_template(
        "grant_alt_leave.html",
        users_by_dept=users_by_dept,
        logs=logs,
    )
