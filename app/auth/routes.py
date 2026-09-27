from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    make_response,
    jsonify,
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
# ✅ 아이디는 대소문자 무시: 입력은 소문자로 정규화
        username_raw = request.form.get("username", "").strip()
        username = username_raw.lower()

        password = request.form.get("password", "").strip()
        selected_dept = request.form.get("department", "").strip()
        remember = request.form.get("remember_id")

        user = User.query.filter_by(username=username).first()

        if user and user.password == password:

            # ✅ 퇴사자만 로그인 차단
            if (user.employment_status or "재직중") == "퇴사":
                error = "퇴사 처리된 계정입니다. 로그인할 수 없습니다."

            else:
                # ✅ 기존 정상 로그인 처리
                session.clear()

                if user.is_superadmin:
                    login_user(user)
                    session["user_id"] = user.id
                    session["username"] = user.username
                    session["department"] = selected_dept or "관리자"
                    session["is_admin"] = True
                    session["is_superadmin"] = True

                    resp = make_response(
                        redirect(url_for("calendar.calendar_page"))
                    )

                    if remember:
                        resp.set_cookie(
                            "saved_username",
                            username,
                            max_age=60 * 60 * 24 * 30
                        )
                    else:
                        resp.delete_cookie("saved_username")

                    flash(
                        f"총관리자({user.username})로 로그인되었습니다.",
                        "success"
                    )
                    return resp

                if not selected_dept:
                    error = "부서를 선택해야 로그인할 수 있습니다."

                elif selected_dept != user.department:
                    error = (
                        f"⚠️ 선택한 부서({selected_dept})가 "
                        f"사용자 정보({user.department})와 일치하지 않습니다."
                    )

                else:
                    login_user(user)

                    session["user_id"] = user.id
                    session["username"] = user.username
                    session["department"] = user.department
                    session["is_admin"] = user.is_admin
                    session["is_superadmin"] = user.is_superadmin

                    resp = make_response(
                        redirect(url_for("calendar.calendar_page"))
                    )

                    if remember:
                        resp.set_cookie(
                            "saved_username",
                            username,
                            max_age=60 * 60 * 24 * 30
                        )
                    else:
                        resp.delete_cookie("saved_username")

                    flash(
                        f"{user.name or user.username}님 환영합니다! "
                        f"({user.department})",
                        "success"
                    )
                    return resp

        else:
            error = "아이디 또는 비밀번호가 올바르지 않습니다."

    saved_username = request.cookies.get("saved_username", "")
    return render_template("login.html", error=error, saved_username=saved_username)


# =====================================================
# 🧪 임시 PC 원격제어 테스트
# 로그인 화면 버튼 → Render 서버 도달 여부만 확인
# 테스트 완료 후 삭제
# =====================================================
@auth_bp.route("/remote-test/command", methods=["POST"])
def remote_test_command():
    data = request.get_json(silent=True) or {}

    command = (data.get("command") or "").strip()

    # 테스트에서는 이 명령 하나만 허용
    if command != "open_notepad":
        return jsonify({
            "ok": False,
            "message": "허용되지 않은 테스트 명령입니다."
        }), 400

    print("=" * 50)
    print("🧪 REMOTE PC TEST")
    print("명령 수신: open_notepad")
    print("=" * 50)

    return jsonify({
        "ok": True,
        "message": "Render 서버가 PC 테스트 명령을 정상적으로 받았습니다."
    })
    

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
