# app/vacation_form/routes.py

from flask import render_template, abort
from flask_login import login_required, current_user

from app.models import User  # ✅ models.py에 User 모델 존재
from . import vacation_form_bp
from datetime import date, datetime


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


def _join_date_key(v: str):
    """
    join_date가 문자열이라 안전하게 파싱해서 정렬 키로 사용.
    형식이 이상하거나 없으면 맨 뒤로 보냄.
    """
    s = (v or "").strip()
    if not s:
        return date.max
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return date.max


def _display_name(u: User) -> str:
    return (u.first_name or u.name or u.username or "").strip()


@vacation_form_bp.route("/", methods=["GET"])
@login_required
def index():
    if not getattr(current_user, "is_superadmin", False):
        abort(403)

    dept_map = []
    for dept in DEPARTMENTS:
        users = User.query.filter_by(department=dept).all()

        # ✅ 입사일(빠른 순) → 이름(가나다)
        users.sort(key=lambda u: (_join_date_key(getattr(u, "join_date", None)), _display_name(u)))

        dept_map.append({"dept": dept, "members": users})

    return render_template("vacation_form/index.html", dept_map=dept_map)
