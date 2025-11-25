# app/newhire/routes.py
from flask import Blueprint, render_template, send_from_directory, request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
import os
import json
from app.models import db, NewHireChecklist

newhire_bp = Blueprint("newhire", __name__, url_prefix="/newhire")


# ============================================================================
# 📌 신규입사 체크리스트 페이지
# ============================================================================
@newhire_bp.route("/", methods=["GET", "POST"])
@login_required
def checklist():

    # 총관리자 접근 금지, 관리자만 가능
    if not (current_user.is_admin and not current_user.is_superadmin):
        flash("관리자만 접근 가능합니다.", "error")
        return redirect(url_for("calendar.calendar_page"))

    # -----------------------------
    # 체크리스트 로드 또는 생성
    # -----------------------------
    checklist = NewHireChecklist.query.filter_by(
        department=current_user.department
    ).first()

    if not checklist:
        checklist = NewHireChecklist(
            department=current_user.department,
            items=json.dumps({})
        )
        db.session.add(checklist)
        db.session.commit()

    # 현재 체크된 항목
    items_json = json.loads(checklist.items or "{}")

    # =========================================================================
    # 📌 POST 처리 (save / reset)
    # =========================================================================
    if request.method == "POST":
        action = request.form.get("action")

        # -----------------------------
        # 저장(save)
        # -----------------------------
        if action == "save":
            item_keys = request.form.getlist("item_key")
            checked_keys = request.form.getlist("item_state")

            updated = {key: (key in checked_keys) for key in item_keys}

            checklist.items = json.dumps(updated)
            db.session.commit()

            flash("저장되었습니다.", "success")
            return redirect(url_for("newhire.checklist"))

        # -----------------------------
        # 초기화(reset)
        # -----------------------------
        elif action == "reset":
            checklist.items = json.dumps({})
            db.session.commit()

            flash("체크리스트가 초기화되었습니다.", "info")
            return redirect(url_for("newhire.checklist"))

    # =========================================================================
    # 📌 GET 요청 — 화면 표시
    # =========================================================================
    return render_template(
        "newhire_checklist.html",
        items_json=items_json
    )


# ============================================================================
# 📌 PDF/HWP 다운로드 기능 (Render + 로컬 공통 사용)
# ============================================================================
@newhire_bp.route("/download/<filename>")
@login_required
def download_file(filename):
    forms_dir = current_app.config["FORMS_FOLDER"]
    file_path = os.path.join(forms_dir, filename)

    if not os.path.exists(file_path):
        abort(404)

    # 모든 파일(PDF, HWP, JPG 등) 정상 다운로드 가능
    return send_from_directory(forms_dir, filename, as_attachment=True)
