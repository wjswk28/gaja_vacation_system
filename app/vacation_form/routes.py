# app/vacation_form/routes.py
import os
from flask import render_template, abort, request, jsonify, send_file, current_app
from flask_login import login_required, current_user
from app import db
from app.models import (
    User, UserMonthConfirm, DeptMonthFinal, DeptMonthRoster,
    MonthLock, MonthSignToggle, ApprovalRoleUser
)
from . import vacation_form_bp
from datetime import date, datetime
import calendar
from pathlib import Path
from app.vacation_form.utils import build_vacation_forms_xlsx

# ✅ 휴가계 페이지에서 사용할 부서 목록
# - 이미 프로젝트 어딘가에 공용 DEPARTMENTS가 있으면 그걸 import해서 쓰는 게 베스트
DEPARTMENTS = [
    "도수", "물리치료", "병동", "상담실", "수술실", "심사과",
    "원무과", "외래", "총무과", "홍보", "진단검사", "영양",
    "영상의학과", "임원진", "약제부"  # ✅ 새 부서
]
ADMIN_HEAD_DEPTS = {"도수", "물리치료", "심사과", "원무과", "총무과", "홍보", "진단검사", "영양", "약제부", "영상의학과"}
NURSE_HEAD_DEPTS = {"상담실", "수술실", "외래"}



def _can_confirm_target_month(year: int, month: int) -> bool:

    today = date.today()
    last_day = calendar.monthrange(year, month)[1]
    start_day = 29 if last_day >= 29 else last_day
    start = date(year, month, start_day)

    next_year, next_month = year, month + 1
    if next_month == 13:
        next_month = 1
        next_year += 1

    end = date(next_year, next_month, 4)
    return start <= today <= end



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

def _dept_targets(dept: str, y: int, m: int):
    """
    ✅ 휴가계 대상자(전원 기준)
    - 1순위: DeptMonthRoster(스냅샷) 있으면 그걸 사용
    - 없으면: 현재 User에서 재직 + 대상자 True만 사용
    """
    snap = DeptMonthRoster.query.filter_by(department=dept, year=y, month=m).all()
    if snap:
        ids = [r.user_id for r in snap]
        users = User.query.filter(User.id.in_(ids)).all()
        # 스냅샷 순서 유지(입사일 정렬은 필요하면 여기서 다시)
        id_to_u = {u.id: u for u in users}
        return [id_to_u[i] for i in ids if i in id_to_u]

    # 스냅샷 없으면 현재 상태 기준
    return (
        User.query
        .filter_by(department=dept)
        .filter(User.employment_status == "재직중")
        .filter(User.is_vacation_form_target == True)
        .all()
    )

@vacation_form_bp.route("/", methods=["GET"])
@login_required
def index():
    is_super = bool(getattr(current_user, "is_superadmin", False))
    is_mgr = bool(getattr(current_user, "is_admin", False)) and (not is_super)

    # ✅ 총관리자 or 중간관리자만 접근
    if not (is_super or is_mgr):
        abort(403)

    # ✅ 보여줄 부서 목록
    if is_super:
        view_depts = DEPARTMENTS[:]   # 전체 부서
    else:
        my_dept = (current_user.department or "").strip()
        if not my_dept:
            abort(403)
        view_depts = [my_dept]        # 내 부서만

    # ✅ 조회할 년/월 (없으면 기본값: 1~4일이면 전월, 그 외엔 이번달)
    y = request.args.get("year", type=int)
    m = request.args.get("month", type=int)

    today = date.today()
    if not y or not m:
        if today.day <= 4:
            # 전월
            if today.month == 1:
                y, m = today.year - 1, 12
            else:
                y, m = today.year, today.month - 1
        else:
            y, m = today.year, today.month

    confirmed_ids = set(
        r.user_id for r in UserMonthConfirm.query.filter_by(year=y, month=m).all()
    )

    dept_map = []
    dept_stats = {}  # ✅ 추가

    for dept in view_depts:
        # ✅ 휴가계 대상자 기준(재직 + is_vacation_form_target, 스냅샷 있으면 스냅샷 우선)
        users = _dept_targets(dept, y, m)
        users.sort(key=lambda u: (_join_date_key(getattr(u, "join_date", None)), _display_name(u)))

        total = len(users)
        confirmed = sum(1 for u in users if u.id in confirmed_ids)
        locked = MonthLock.query.filter_by(department=dept, year=y, month=m, locked=True).first() is not None
        dept_stats[dept] = {"total": total, "confirmed": confirmed, "locked": locked}

        dept_map.append({"dept": dept, "members": users})

    finalized_depts = set(
        r.department for r in DeptMonthFinal.query.filter_by(year=y, month=m).all()
        if r.finalized_at
    )

    # ✅ 병원장 후보: 의료진만
    director_candidates = (
        User.query
        .filter_by(department="의료진")
        .filter(User.employment_status == "재직중")
        .order_by(User.name.asc())
        .all()
    )

    # ✅ 부장 후보: 중간관리자만(총관리자 제외)
    chief_candidates = (
        User.query
        .filter(User.is_admin == True)
        .filter(User.is_superadmin == False)
        .filter(User.employment_status == "재직중")
        .order_by(User.department.asc(), User.name.asc())
        .all()
    )

    # ✅ 현재 지정된 role→user_id 맵(선택값 유지용)
    role_map = {r.role: r.user_id for r in ApprovalRoleUser.query.all()}
    can_confirm = _can_confirm_target_month(y, m)

    return render_template(
        "vacation_form/index.html",
        dept_map=dept_map,
        year=y,
        month=m,
        confirmed_ids=confirmed_ids,
        dept_stats=dept_stats,
        finalized_depts=finalized_depts,
        is_super=is_super,   # ✅ 추가
        is_mgr=is_mgr,       # ✅ 추가
        director_candidates=director_candidates,
        chief_candidates=chief_candidates,
        role_map=role_map,
        can_confirm=can_confirm,
    )

@vacation_form_bp.get("/template")
@login_required
def download_vacation_form_template():
    # ✅ index()와 동일한 권한
    is_super = bool(getattr(current_user, "is_superadmin", False))
    is_mgr = bool(getattr(current_user, "is_admin", False)) and (not is_super)
    if not (is_super or is_mgr):
        abort(403)

    dept = (request.args.get("dept") or "").strip()
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)

    # ✅ 중간관리자는 자기 부서만 다운로드 가능
    if is_mgr:
        my_dept = (current_user.department or "").strip()
        if dept != my_dept:
            abort(403)

    # ✅ 템플릿 파일 경로: 프로젝트폴더/forms/vacation_form.xlsx
    # current_app.root_path = .../프로젝트폴더/app
    template_path = Path(current_app.root_path).parent / "forms" / "vacation_form.xlsx"
    if not template_path.exists():
        abort(404, description=f"휴가계 템플릿을 찾을 수 없습니다: {template_path}")

    # ✅ 다운로드 파일명(예쁘게)
    safe_dept = (dept or "부서").replace("/", "_").replace("\\", "_").replace("..", "")
    suffix = ""
    if year and month:
        suffix = f"_{year}_{month:02d}"
    download_name = f"휴가계_{safe_dept}{suffix}.xlsx"

    return send_file(
        template_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        conditional=True,
        max_age=0,
    )

@vacation_form_bp.route("/dept_lock", methods=["POST"])
@login_required
def dept_lock():
    is_super = bool(getattr(current_user, "is_superadmin", False))
    is_mgr = bool(getattr(current_user, "is_admin", False)) and (not is_super)

    # ✅ 총관리자/중간관리자만
    if not (is_super or is_mgr):
        return jsonify({"status": "error", "message": "권한이 없습니다."}), 403

    data = request.get_json(silent=True) or {}
    dept = (data.get("dept") or "").strip()
    year = int(data.get("year") or 0)
    month = int(data.get("month") or 0)

    if not dept or year <= 0 or month <= 0:
        return jsonify({"status": "error", "message": "파라미터가 올바르지 않습니다."}), 400

    # ✅ 중간관리자는 자기 부서만 잠금 가능
    if is_mgr:
        my_dept = (current_user.department or "").strip()
        if dept != my_dept:
            return jsonify({"status": "error", "message": "내 부서만 확정할 수 있습니다."}), 403

    if (not is_super) and (not _can_confirm_target_month(year, month)):
        return jsonify({"status": "error", "message": "확정은 해당 월의 29일 ~ 다음 달 4일에만 가능합니다."}), 400

    # ✅ 전원 개인확정 완료 후에만 잠금 허용(원하면 조건 제거 가능)
    users = _dept_targets(dept, year, month)
    confirmed_ids = set(
        r.user_id for r in UserMonthConfirm.query.filter_by(year=year, month=month).all()
    )
    total = len(users)
    confirmed = sum(1 for u in users if u.id in confirmed_ids)
    if total > 0 and confirmed != total:
        return jsonify({"status": "error", "message": f"전원 확정({confirmed}/{total}) 후에만 가능합니다."}), 400
    
    # ✅ (추천) 확정 시점 대상자 스냅샷 저장
    # - 이후 인사변동(퇴사/대상자 변경)이 있어도 "그 달의 전원 기준"이 흔들리지 않게 함
    DeptMonthRoster.query.filter_by(department=dept, year=year, month=month).delete(synchronize_session=False)
    for u in users:
        db.session.add(DeptMonthRoster(department=dept, year=year, month=month, user_id=u.id))

    # ✅ 서명 등록 여부 체크
    # - 중간관리자는 서명 필수
    # - 총관리자(master)는 유지보수용 계정이므로 서명 없이도 잠금 가능
    if not is_super:
        sig = (getattr(current_user, "signature_image", None) or "").strip()
        if not sig:
            return jsonify({
                "status": "error",
                "message": "서명이 등록되어 있어야 확정할 수 있습니다. (내정보에서 서명 등록 후 확정하세요)"
            }), 400

    # ✅ month_lock 적용(잠금) + 누가 잠갔는지 기록(서명 삽입에 필요)
    lk = MonthLock.query.filter_by(department=dept, year=year, month=month).first()
    if not lk:
        lk = MonthLock(department=dept, year=year, month=month)

    lk.locked = True
    lk.locked_at = datetime.now()
    lk.locked_by = current_user.id

    db.session.add(lk)
    db.session.commit()


    # -------------------------------------------------------
    # ✅ 서명 삽입(기존 기능) 연결 자리
    # - 지금 업로드된 파일들에는 서명 삽입 함수가 없어서
    #   "어떤 함수를 호출해야 하는지"를 아직 정확히 못 찍어.
    # - 서명 삽입 함수/코드가 있는 파일을 올려주면
    #   여기 바로 아래에 정확히 붙여줄게.
    # -------------------------------------------------------

    return jsonify({"status": "success", "message": "부서 확정(잠금) 완료"})

@vacation_form_bp.post("/user_confirm")
@login_required
def user_confirm():
    is_super = bool(getattr(current_user, "is_superadmin", False))
    is_mgr = bool(getattr(current_user, "is_admin", False)) and (not is_super)

    # ✅ 총관리자/중간관리자 허용
    if not (is_super or is_mgr):
        return jsonify({"status": "error", "message": "권한이 없습니다."}), 403

    data = request.get_json(silent=True) or {}
    user_id = int(data.get("user_id") or 0)
    year = int(data.get("year") or 0)
    month = int(data.get("month") or 0)

    if user_id <= 0 or year <= 0 or month <= 0:
        return jsonify({"status": "error", "message": "파라미터가 올바르지 않습니다."}), 400

    # ✅ 중간관리자만 기간 제한 적용 / master는 언제나 가능
    if (not is_super) and (not _can_confirm_target_month(year, month)):
        return jsonify({"status": "error", "message": "확정 가능한 기간이 아닙니다."}), 400

    target = db.session.get(User, user_id)
    if not target:
        return jsonify({"status": "error", "message": "대상 직원을 찾을 수 없습니다."}), 404

    my_dept = (current_user.department or "").strip()
    tgt_dept = (target.department or "").strip()

    # ✅ 중간관리자만 자기 부서 직원 제한
    if is_mgr and tgt_dept != my_dept:
        return jsonify({"status": "error", "message": "내 부서 직원만 확정할 수 있습니다."}), 403

    # ✅ 휴가계 대상자만
    targets = _dept_targets(tgt_dept, year, month)
    target_ids = {u.id for u in targets}
    if target.id not in target_ids:
        return jsonify({"status": "error", "message": "휴가계 대상자가 아닙니다."}), 400

    # ✅ 중간관리자만 잠금 후 변경 불가 / master는 가능
    locked = MonthLock.query.filter_by(department=tgt_dept, year=year, month=month, locked=True).first()
    if (not is_super) and locked:
        return jsonify({"status": "error", "message": "이미 부서 확정(잠금)된 달입니다."}), 400

    # ✅ 토글(있으면 삭제, 없으면 생성)
    rec = UserMonthConfirm.query.filter_by(user_id=target.id, year=year, month=month).first()
    if rec:
        db.session.delete(rec)
        confirmed_now = False
    else:
        rec = UserMonthConfirm(user_id=target.id, year=year, month=month)
        if hasattr(rec, "confirmed_at"):
            rec.confirmed_at = datetime.now()
        if hasattr(rec, "confirmed_by"):
            rec.confirmed_by = current_user.id
        db.session.add(rec)
        confirmed_now = True

    db.session.commit()

    confirmed_ids = set(
        r.user_id for r in UserMonthConfirm.query.filter_by(year=year, month=month).all()
    )
    total = len(targets)
    confirmed_cnt = sum(1 for u in targets if u.id in confirmed_ids)

    return jsonify({
        "status": "success",
        "dept": tgt_dept,
        "user_id": target.id,
        "confirmed": confirmed_now,
        "total": total,
        "confirmed_cnt": confirmed_cnt,
        "locked": bool(locked),
    })

@vacation_form_bp.route("/dept_unlock", methods=["POST"])
@login_required
def dept_unlock():
    # ✅ 총관리자만
    if not bool(getattr(current_user, "is_superadmin", False)):
        return jsonify({"status": "error", "message": "총관리자만 확정 해제할 수 있습니다."}), 403

    data = request.get_json(silent=True) or {}
    dept = (data.get("dept") or "").strip()
    year = int(data.get("year") or 0)
    month = int(data.get("month") or 0)

    if not dept or year <= 0 or month <= 0:
        return jsonify({"status": "error", "message": "파라미터가 올바르지 않습니다."}), 400

    lk = MonthLock.query.filter_by(department=dept, year=year, month=month).first()
    if not lk or not lk.locked:
        return jsonify({"status": "error", "message": "이미 확정 해제 상태입니다."}), 400

    # ✅ 확정 해제(잠금 해제)
    lk.locked = False
    lk.locked_at = None
    lk.locked_by = None

    db.session.add(lk)
    db.session.commit()

    return jsonify({"status": "success", "message": "확정 해제 완료"})

@vacation_form_bp.get("/sign-status")
@login_required
def sign_status():
    # ✅ 총관리자만
    if not bool(getattr(current_user, "is_superadmin", False)):
        return jsonify({"status": "error", "message": "권한이 없습니다."}), 403

    y = request.args.get("year", type=int)
    m = request.args.get("month", type=int)
    if not y or not m:
        return jsonify({"status": "error", "message": "year/month가 필요합니다."}), 400

    rec = MonthSignToggle.query.filter_by(year=y, month=m).first()
    return jsonify({
        "status": "ok",
        "year": y,
        "month": m,
        "director_on": bool(rec and rec.director_on),
        "admin_head_on": bool(rec and rec.admin_head_on),
        "nurse_head_on": bool(rec and rec.nurse_head_on),
    })


@vacation_form_bp.post("/sign-toggle")
@login_required
def sign_toggle():
    # ✅ 총관리자만
    if not bool(getattr(current_user, "is_superadmin", False)):
        return jsonify({"status": "error", "message": "권한이 없습니다."}), 403

    data = request.get_json(silent=True) or {}
    y = int(data.get("year") or 0)
    m = int(data.get("month") or 0)
    role = (data.get("role") or "").strip()  # director | admin_head | nurse_head

    if y <= 0 or m <= 0:
        return jsonify({"status": "error", "message": "year/month가 올바르지 않습니다."}), 400
    if role not in ("director", "admin_head", "nurse_head"):
        return jsonify({"status": "error", "message": "role이 올바르지 않습니다."}), 400

    rec = MonthSignToggle.query.filter_by(year=y, month=m).first()
    if not rec:
        rec = MonthSignToggle(year=y, month=m)
        db.session.add(rec)

    if role == "director":
        rec.director_on = not rec.director_on
        value = rec.director_on
    elif role == "admin_head":
        rec.admin_head_on = not rec.admin_head_on
        value = rec.admin_head_on
    else:
        rec.nurse_head_on = not rec.nurse_head_on
        value = rec.nurse_head_on

    db.session.commit()
    return jsonify({"status": "ok", "role": role, "value": bool(value)})

@vacation_form_bp.get("/approval-role-map")
@login_required
def approval_role_map():
    if not current_user.is_superadmin:
        return jsonify({"status":"error","message":"권한이 없습니다."}), 403

    rows = ApprovalRoleUser.query.all()
    out = {r.role: r.user_id for r in rows}
    return jsonify({"status":"ok","map": out})


@vacation_form_bp.post("/approval-role-map")
@login_required
def set_approval_role_map():
    if not current_user.is_superadmin:
        return jsonify({"status":"error","message":"권한이 없습니다."}), 403

    data = request.get_json(silent=True) or {}
    role = (data.get("role") or "").strip()
    user_id = int(data.get("user_id") or 0)

    if role not in ("director", "admin_head", "nurse_head"):
        return jsonify({"status":"error","message":"role이 올바르지 않습니다."}), 400
    u = db.session.get(User, user_id)
    if not u:
        return jsonify({"status":"error","message":"사용자를 찾을 수 없습니다."}), 400

    rec = ApprovalRoleUser.query.filter_by(role=role).first()
    if not rec:
        rec = ApprovalRoleUser(role=role, user_id=user_id)
        db.session.add(rec)
    else:
        rec.user_id = user_id

    db.session.commit()
    return jsonify({"status":"ok"})

@vacation_form_bp.get("/download")
@login_required
def download_vacation_forms():
    is_super = bool(getattr(current_user, "is_superadmin", False))
    is_mgr = bool(getattr(current_user, "is_admin", False)) and (not is_super)

    if not (is_super or is_mgr):
        abort(403)

    dept = (request.args.get("dept") or "").strip()
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)

    if not dept or not year or not month:
        return jsonify({"status": "error", "message": "dept/year/month가 필요합니다."}), 400

    # ✅ 중간관리자는 자기 부서만
    if is_mgr:
        my_dept = (current_user.department or "").strip()
        if dept != my_dept:
            abort(403)

    # ✅ 조건 1) 부서 확정(잠금) 되어 있어야 함
    locked = MonthLock.query.filter_by(department=dept, year=year, month=month, locked=True).first()
    if not locked:
        return jsonify({"status": "error", "message": "부서 확정(잠금) 후 다운로드할 수 있습니다."}), 400

    # ✅ 조건 2) 전원 개인 확정 완료
    targets = _dept_targets(dept, year, month)
    confirmed_ids = set(
        r.user_id for r in UserMonthConfirm.query.filter_by(year=year, month=month).all()
    )
    total = len(targets)
    confirmed = sum(1 for u in targets if u.id in confirmed_ids)
    if total > 0 and confirmed != total:
        return jsonify({"status": "error", "message": f"전원 확정({confirmed}/{total}) 후에만 가능합니다."}), 400

    # ✅ 템플릿 경로: 프로젝트폴더/forms/vacation_form.xlsx
    template_path = Path(current_app.root_path).parent / "forms" / "vacation_form.xlsx"
    if not template_path.exists():
        abort(404, description=f"휴가계 템플릿을 찾을 수 없습니다: {template_path}")

    # ✅ 대상자 정렬(현재 너 index()와 동일하게 입사일 + 이름 정렬 추천)
    targets.sort(key=lambda u: (_join_date_key(getattr(u, "join_date", None)), _display_name(u)))

    sig_folder = current_app.config["SIGNATURES_FOLDER"]  # 근무표와 동일

    def _sig_abs_path(user: User, sig_folder: str) -> str | None:
        sig = (getattr(user, "signature_image", "") or "").strip()
        if not sig:
            return None
        # 절대경로 저장된 경우
        if os.path.isabs(sig) and os.path.exists(sig):
            return sig
        # 파일명만 signatures 폴더에서 찾기
        p = Path(sig_folder) / Path(sig).name
        return str(p) if p.exists() else None


    header_signatures = {}

    # ✅ 1) 부서장(I3) = 이 부서/월을 잠근(확정한) 중간관리자 서명
    lk = MonthLock.query.filter_by(department=dept, year=year, month=month, locked=True).first()
    if lk and lk.locked_by:
        dept_head_user = db.session.get(User, lk.locked_by)
        if dept_head_user:
            p = _sig_abs_path(dept_head_user, sig_folder)
            if p:
                header_signatures["I3"] = p

    # ✅ 2) 총관리자 토글 서명(L3/O3)
    # - MonthSignToggle: 해당 월에 어떤 결재라인을 찍을지 on/off
    # - ApprovalRoleUser: role별 실제 서명자(사용자) 지정
    tog = MonthSignToggle.query.filter_by(year=year, month=month).first()
    role_map = {r.role: r.user_id for r in ApprovalRoleUser.query.all()}

    # ✅ (부장 toggle) L3: 부서에 따라 "행정부장/간호부장" 자동 선택
    # - ADMIN_HEAD_DEPTS 소속 부서면 admin_head_on 토글만 반영
    # - NURSE_HEAD_DEPTS 소속 부서면 nurse_head_on 토글만 반영
    # - 둘 다 아니면(예: 의료진/임원진 등) 아무 것도 안 넣음(원하면 규칙 추가 가능)

    boss_role = None
    boss_toggle_on = False

    if dept in ADMIN_HEAD_DEPTS:
        boss_role = "admin_head"
        boss_toggle_on = bool(tog and getattr(tog, "admin_head_on", False))
    elif dept in NURSE_HEAD_DEPTS:
        boss_role = "nurse_head"
        boss_toggle_on = bool(tog and getattr(tog, "nurse_head_on", False))

    if boss_role and boss_toggle_on:
        uid = role_map.get(boss_role)
        if uid:
            u = db.session.get(User, uid)
            if u:
                p = _sig_abs_path(u, sig_folder)
                if p:
                    header_signatures["L3"] = p

    # (병원장) O3
    if tog and getattr(tog, "director_on", False):
        uid = role_map.get("director")
        if uid:
            u = db.session.get(User, uid)
            if u:
                p = _sig_abs_path(u, sig_folder)
                if p:
                    header_signatures["O3"] = p


    try:
        xlsx_io = build_vacation_forms_xlsx(
            str(template_path),
            targets,
            year=year,
            month=month,
            signatures_folder=sig_folder,
            header_signatures=header_signatures,
        )
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    safe_dept = dept.replace("/", "_").replace("\\", "_").replace("..", "")
    download_name = f"휴가계_{safe_dept}_{year}_{month:02d}.xlsx"

    return send_file(
        xlsx_io,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        max_age=0,
    )

