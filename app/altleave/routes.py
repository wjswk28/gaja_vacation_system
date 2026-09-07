# app/altleave/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from app.models import (
    User,
    Vacation,
    AltLeaveLog,
    AltLeaveRecipient,
)
from sqlalchemy import or_, and_, func

altleave_bp = Blueprint("altleave", __name__, url_prefix="/altleave")

# =====================================================
# 대체연차 사용 일수
# =====================================================
ALT_LEAVE_DAY_MAP = {
    "연차": 1.0,
    "반차": 0.5,       # 과거 데이터 호환
    "반차(전)": 0.5,
    "반차(후)": 0.5,
    "반반차": 0.25,
    "토연차": 0.75,
}


def _get_used_alt_leave_days(user_id):
    """
    직원별 실제 대체연차 사용량

    기준:
    - 승인된 휴가
    - is_alt=True
    - target_user_id 우선
    - 과거 데이터는 target_user_id가 NULL일 때 user_id 사용
    """

    events = (
        Vacation.query
        .filter(
            Vacation.approved.is_(True),
            Vacation.is_alt.is_(True),
            Vacation.type.in_(
                list(ALT_LEAVE_DAY_MAP.keys())
            ),
            or_(
                Vacation.target_user_id == user_id,
                and_(
                    Vacation.target_user_id.is_(None),
                    Vacation.user_id == user_id,
                )
            )
        )
        .all()
    )

    used_days = sum(
        float(
            ALT_LEAVE_DAY_MAP.get(
                (event.type or "").strip(),
                0.0
            )
        )
        for event in events
    )

    return round(used_days, 2)

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
        User.query
        .filter(User.is_superadmin == False)
        .filter(User.employment_status == "재직중")
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
        selected_users = (
            User.query
            .filter(User.id.in_(user_ids))
            .filter(User.employment_status == "재직중")
            .filter(User.is_superadmin == False)
            .all()
        )

        if len(selected_users) != len(set(user_ids)):
            flash(
                "재직중인 직원에게만 대체연차를 부여할 수 있습니다.",
                "error"
            )
            return redirect(url_for("altleave.grant_alt_leave"))

        # 부서별 이름 요약 만들기
        dept_map = {}
        for user in selected_users:
            dept_map.setdefault(user.department or "기타", []).append(user.name)

        dept_summary = ", ".join(
            [f"{dept}({', '.join(names)})" for dept, names in dept_map.items()]
        )

        # =====================================================
        # 대체연차 지급 로그 생성
        # =====================================================
        log = AltLeaveLog(
            apply_date=apply_date,
            reason=reason,
            add_days=add_days,
            granted_by=current_user.name,
            department_summary=dept_summary
        )

        db.session.add(log)

        # ✅ INSERT 전에 log.id를 받기 위해 flush
        # commit은 아직 하지 않음
        db.session.flush()


        # =====================================================
        # 실제 지급 대상자를 user_id로 저장
        # =====================================================
        for u in selected_users:
            recipient = AltLeaveRecipient(
                log_id=log.id,
                user_id=u.id,
                add_days=add_days,
            )

            db.session.add(recipient)


        # ✅ User.alt_leave는 더 이상 수정하지 않는다.
        # 잔여 대체연차는 앞으로
        #
        # AltLeaveRecipient 총 부여
        # -
        # Vacation.is_alt 실제 사용
        #
        # 으로 계산한다.

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


# ==========================
# 대체연차 지급이력 삭제
# ==========================
@altleave_bp.route("/delete/<int:log_id>", methods=["POST"])
@login_required
def delete_log(log_id):

    # ✅ 총관리자만 삭제 가능
    if not current_user.is_superadmin:
        flash(
            "삭제 권한이 없습니다.",
            "error"
        )
        return redirect(
            url_for("altleave.grant_alt_leave")
        )

    log = AltLeaveLog.query.get_or_404(log_id)

    # =====================================================
    # 1) 이 지급건의 실제 대상자 조회
    # =====================================================
    recipients = (
        AltLeaveRecipient.query
        .filter_by(log_id=log.id)
        .all()
    )

    # =====================================================
    # 과거 이관 전 로그 등 Recipient 정보가 없는 경우
    # 자동 안전검사가 불가능하므로 삭제 차단
    # =====================================================
    if not recipients:
        flash(
            "이 지급이력은 실제 지급 대상자 정보가 없어 "
            "안전하게 삭제 여부를 확인할 수 없습니다.",
            "error"
        )
        return redirect(
            url_for("altleave.grant_alt_leave")
        )

    blocked_users = []

    # =====================================================
    # 2) 직원별 삭제 가능 여부 검사
    # =====================================================
    for recipient in recipients:

        user_id = recipient.user_id

        delete_days = float(
            recipient.add_days or 0.0
        )

        # ---------------------------------------------
        # 현재까지 총 부여된 대체연차
        # ---------------------------------------------
        total_granted = (
            db.session.query(
                func.coalesce(
                    func.sum(
                        AltLeaveRecipient.add_days
                    ),
                    0.0
                )
            )
            .filter(
                AltLeaveRecipient.user_id == user_id
            )
            .scalar()
        )

        total_granted = float(
            total_granted or 0.0
        )

        # ---------------------------------------------
        # 이 지급건을 삭제했을 때 남는 총 부여량
        # ---------------------------------------------
        granted_after_delete = round(
            total_granted - delete_days,
            2
        )

        # ---------------------------------------------
        # 현재 실제 사용한 대체연차
        # ---------------------------------------------
        used_alt = _get_used_alt_leave_days(
            user_id
        )

        # ---------------------------------------------
        # 삭제 후 부여량보다 이미 사용한 양이 많으면
        # 지급이력 삭제 불가
        # ---------------------------------------------
        if granted_after_delete < used_alt - 0.000001:

            user = (
                recipient.user
                or db.session.get(User, user_id)
            )

            if user:
                user_name = (
                    user.name
                    or user.username
                    or f"user_id={user_id}"
                )

                department = (
                    user.department
                    or "부서없음"
                )

            else:
                user_name = f"user_id={user_id}"
                department = "직원정보없음"

            blocked_users.append({
                "department": department,
                "name": user_name,
                "granted_after": granted_after_delete,
                "used": used_alt,
            })

    # =====================================================
    # 3) 한 명이라도 문제가 있으면
    #    지급건 전체 삭제 차단
    # =====================================================
    if blocked_users:

        preview = blocked_users[:5]

        detail = ", ".join(
            (
                f"{row['department']} {row['name']} "
                f"(삭제 후 부여 "
                f"{row['granted_after']:.2f}일 / "
                f"사용 {row['used']:.2f}일)"
            )
            for row in preview
        )

        if len(blocked_users) > 5:
            detail += (
                f" 외 {len(blocked_users) - 5}명"
            )

        flash(
            "이 지급이력은 삭제할 수 없습니다. "
            "삭제하면 이미 사용한 대체연차보다 "
            "총 부여량이 적어지는 직원이 있습니다. "
            + detail,
            "error"
        )

        return redirect(
            url_for("altleave.grant_alt_leave")
        )

    # =====================================================
    # 4) 안전한 경우에만 실제 삭제
    # =====================================================
    try:
        db.session.delete(log)
        db.session.commit()

    except Exception as e:

        db.session.rollback()

        print(
            "❌ 대체연차 지급이력 삭제 오류:",
            e
        )

        flash(
            "대체연차 지급이력 삭제 중 오류가 발생했습니다.",
            "error"
        )

        return redirect(
            url_for("altleave.grant_alt_leave")
        )

    flash(
        "대체연차 지급이력이 삭제되었습니다.",
        "success"
    )

    return redirect(
        url_for("altleave.grant_alt_leave")
    )
