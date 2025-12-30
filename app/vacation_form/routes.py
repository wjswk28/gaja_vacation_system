# app/vacation_form/routes.py

from flask import render_template, abort
from flask_login import login_required, current_user

from app.models import User  # ✅ models.py에 User 모델 존재
from . import vacation_form_bp


# ✅ 휴가계 페이지에서 사용할 부서 목록
# - 이미 프로젝트 어딘가에 공용 DEPARTMENTS가 있으면 그걸 import해서 쓰는 게 베스트
DEPARTMENTS = [
    "도수", "물리치료", "병동", "상담실", "수술실", "심사과",
    "원무과", "외래", "총무과", "홍보", "진단검사", "영양",
    "의료진", "임원진", "약제부"  # ✅ 새 부서
]


def _display_name(u: User) -> str:
    """
    ✅ 버튼에 표시할 이름 규칙
    - 너 models.py를 보면 first_name / name / username이 섞여 있을 수 있어서
      안전하게 우선순위로 표시
    """
    return (u.first_name or u.name or u.username or "").strip()


@vacation_form_bp.route("/", methods=["GET"])
@login_required
def index():
    # ✅ 총관리자 전용 (원하면 is_admin까지 허용으로 변경 가능)
    if not getattr(current_user, "is_superadmin", False):
        abort(403)

    dept_map = []

    for dept in DEPARTMENTS:
        users = User.query.filter_by(department=dept).all()

        # ✅ 한글 이름 정렬 안정적으로 (name/first_name/username 혼재 대비)
        users.sort(key=lambda x: _display_name(x))

        dept_map.append({
            "dept": dept,
            "members": users,
        })

    return render_template("vacation_form/index.html", dept_map=dept_map)
