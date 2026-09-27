import os
import json

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    make_response,
    jsonify,
    current_app,
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
# Render ↔ 병원 PC 연결 확인용
# 테스트 완료 후 삭제
# =====================================================

def _remote_test_file():
    return os.path.join(
        current_app.config["STORAGE_ROOT"],
        "remote_test_command.json"
    )


# -----------------------------------------------------
# 로그인 화면 버튼 → 명령 저장
# -----------------------------------------------------
@auth_bp.route("/remote-test/command", methods=["POST"])
def remote_test_command():
    data = request.get_json(silent=True) or {}

    command = (data.get("command") or "").strip()
    pin = (data.get("pin") or "").strip()

    expected_pin = os.environ.get("REMOTE_TEST_PIN", "").strip()

    # PIN 설정 여부 + 일치 여부 확인
    if not expected_pin or pin != expected_pin:
        return jsonify({
            "ok": False,
            "message": "테스트 PIN이 올바르지 않습니다."
        }), 403

    # 테스트에서는 메모장 실행만 허용
    if command != "open_notepad":
        return jsonify({
            "ok": False,
            "message": "허용되지 않은 테스트 명령입니다."
        }), 400

    command_data = {
        "command": "open_notepad",
        "status": "pending"
    }

    with open(
        _remote_test_file(),
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            command_data,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("🧪 PC 명령 저장: open_notepad")

    return jsonify({
        "ok": True,
        "message": "PC에 메모장 실행 명령을 저장했습니다."
    })


# -----------------------------------------------------
# 병원 PC Agent → 명령 확인
# -----------------------------------------------------
@auth_bp.route("/remote-test/agent-poll", methods=["GET"])
def remote_test_agent_poll():

    token = (
        request.headers.get("X-PC-AGENT-TOKEN", "")
        or ""
    ).strip()

    expected_token = (
        os.environ.get("PC_AGENT_TOKEN", "")
        or ""
    ).strip()

    if not expected_token or token != expected_token:
        return jsonify({
            "ok": False,
            "message": "인증 실패"
        }), 403

    path = _remote_test_file()

    # 아직 명령 없음
    if not os.path.exists(path):
        return jsonify({
            "ok": True,
            "command": None
        })

    try:
        with open(path, "r", encoding="utf-8") as f:
            command_data = json.load(f)
    except Exception:
        return jsonify({
            "ok": True,
            "command": None
        })

    # 이미 PC가 가져간 명령
    if command_data.get("status") != "pending":
        return jsonify({
            "ok": True,
            "command": None
        })

    command = command_data.get("command")

    # 가져간 것으로 표시
    command_data["status"] = "dispatched"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            command_data,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(f"🖥️ PC Agent가 명령 가져감: {command}")

    return jsonify({
        "ok": True,
        "command": command
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
