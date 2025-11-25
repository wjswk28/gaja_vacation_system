from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    make_response,
)
from flask_login import (
    login_user,
    login_required,
    logout_user,
)
from app.auth import auth_bp
from app.models import User


# =====================
# 로그인 (아이디 기억 기능 포함)
# =====================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        selected_dept = request.form.get("department", "").strip()
        remember = request.form.get("remember_id")

        user = User.query.filter_by(username=username).first()

        # ✅ 사용자 검증
        if user and user.password == password:

            # ✅ 세션 초기화 (이전 로그인 흔적 완전 제거)
            session.clear()

            # ✅ (1) 총관리자 예외 처리 — 부서 선택 없이 로그인 가능
            if user.is_superadmin:
                login_user(user)
                session["user_id"] = user.id
                session["username"] = user.username
                session["department"] = selected_dept or "관리자"
                session["is_admin"] = True
                session["is_superadmin"] = True

                resp = make_response(redirect(url_for("calendar.calendar_page")))
                if remember:
                    resp.set_cookie("saved_username", username, max_age=60 * 60 * 24 * 30)
                else:
                    resp.delete_cookie("saved_username")

                flash(f"총관리자({user.username})로 로그인되었습니다.", "success")
                return resp

            # ✅ (2) 일반 사용자 / 부서관리자 → 부서 선택 및 일치 필요
            if not selected_dept:
                error = "부서를 선택해야 로그인할 수 있습니다."
            elif selected_dept != user.department:
                error = f"⚠️ 선택한 부서({selected_dept})가 사용자 정보({user.department})와 일치하지 않습니다."
            else:
                # ✅ 정상 로그인
                login_user(user)
                session["user_id"] = user.id
                session["username"] = user.username
                session["department"] = user.department
                session["is_admin"] = user.is_admin
                session["is_superadmin"] = user.is_superadmin

                resp = make_response(redirect(url_for("calendar.calendar_page")))
                if remember:
                    resp.set_cookie("saved_username", username, max_age=60 * 60 * 24 * 30)
                else:
                    resp.delete_cookie("saved_username")

                flash(f"{user.name or user.username}님 환영합니다! ({user.department})", "success")
                return resp

        else:
            error = "아이디 또는 비밀번호가 올바르지 않습니다."

    saved_username = request.cookies.get("saved_username", "")
    return render_template("login.html", error=error, saved_username=saved_username)


# =====================
# 로그아웃
# =====================
@auth_bp.route("/logout")
@login_required
def logout():
    session.clear()
    logout_user()
    flash("로그아웃되었습니다.", "info")
    return redirect(url_for("auth.login"))
