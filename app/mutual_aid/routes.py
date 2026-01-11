from datetime import datetime, date
from flask import render_template, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import MutualAidOfficer, MutualAidLedger, User, MutualAidYearFinal
from . import mutual_aid_bp
from sqlalchemy import func, case


def get_active_officers_obj(year: int):
    officers = MutualAidOfficer.query.filter_by(active=True, year=year).all()
    out = {"president": None, "treasurer": None}
    for o in officers:
        if o.role in out:
            out[o.role] = o.user
    return out

def is_officer(user, role=None, year=None):
    q = MutualAidOfficer.query.filter_by(user_id=user.id, active=True)
    if year is not None:
        q = q.filter_by(year=year)
    if role:
        q = q.filter_by(role=role)
    return db.session.query(q.exists()).scalar()

def can_mutual_aid_edit(user, year: int):
    if (user.department or "").strip() == "총무과":
        return True
    return is_officer(user, "president", year=year)

@mutual_aid_bp.route("/", methods=["GET"])
@login_required
def index():
    now_y = datetime.now().year
    try:
        selected_year = int(request.args.get("year") or now_y)
    except:
        selected_year = now_y

    officers = get_active_officers_obj(selected_year)
    can_edit = can_mutual_aid_edit(current_user, selected_year)

    # ✅ year 목록: 원장에 있는 year들 + 최근 3년(24/25 포함) 보정
    years = [y for (y,) in db.session.query(MutualAidLedger.year)
             .distinct()
             .order_by(MutualAidLedger.year.asc())
             .all()]

    base_years = [now_y - 2, now_y - 1, now_y]  # 예: 2024, 2025, 2026
    for y in base_years:
        if y not in years:
            years.append(y)

    # 선택년도도 혹시 빠졌으면 포함
    if selected_year not in years:
        years.append(selected_year)

    years = sorted(set(years))


    # ✅ 선택년도 원장 조회
    entries = (MutualAidLedger.query
               .filter_by(year=selected_year)
               .order_by(MutualAidLedger.entry_date.desc(), MutualAidLedger.id.desc())
               .all())
    
    # ✅ 요약 계산
    prev_year = selected_year - 1

    # ✅ (1) 이전년도 결산 잔액이 있으면 그 값을 이월로 사용
    prev_final = MutualAidYearFinal.query.filter_by(year=prev_year, finalized=True).first()
    if prev_final:
        carryover = int(prev_final.closing_balance)
    else:
        # ✅ (2) 결산이 없으면 기존 방식(누적)으로 계산
        prev_income = db.session.query(func.coalesce(func.sum(MutualAidLedger.amount), 0)) \
            .filter(MutualAidLedger.entry_type == "income", MutualAidLedger.year < selected_year) \
            .scalar() or 0

        prev_expense = db.session.query(func.coalesce(func.sum(MutualAidLedger.amount), 0)) \
            .filter(MutualAidLedger.entry_type == "expense", MutualAidLedger.year < selected_year) \
            .scalar() or 0

        carryover = int(prev_income) - int(prev_expense)

    # ✅ 결산 여부(선택년도)
    is_finalized = bool(MutualAidYearFinal.query.filter_by(year=selected_year, finalized=True).first())


    # 2) 선택년도 수입/지출(현재 entries 기준)
    income_total = sum(e.amount for e in entries if e.entry_type == "income")
    expense_total = sum(e.amount for e in entries if e.entry_type == "expense")

    # 3) 선택년도 잔액(이월 포함)
    balance = int(carryover) + int(income_total) - int(expense_total)

    # ✅ 템플릿에서 바로 쓰기 좋게 포맷 문자열도 같이 전달
    carryover_fmt = f"{carryover:,}"
    income_total_fmt = f"{income_total:,}"
    expense_total_fmt = f"{expense_total:,}"
    balance_fmt = f"{balance:,}"


    # ✅ 총관리자만 드롭바 사용자 목록 제공
    all_users = []
    if current_user.is_superadmin:
        all_users = (User.query
                    .filter(User.is_admin == True, User.is_superadmin == False)
                    .order_by(User.department.asc(), User.name.asc())
                    .all())

    return render_template(
        "mutual_aid.html",
        officers=type("O", (), officers),
        years=years,
        selected_year=selected_year,
        all_users=all_users,
        can_edit=can_edit,

        # ✅ 추가로 내려줄 값들
        entries=entries,
        income_total_fmt=income_total_fmt,
        expense_total_fmt=expense_total_fmt,
        balance_fmt=balance_fmt,
        prev_year=prev_year,
        carryover_fmt=carryover_fmt,
        is_finalized=is_finalized,
    )


@mutual_aid_bp.route("/admin/appoint", methods=["POST"])
@login_required
def appoint_officer():
    if not current_user.is_superadmin:
        return jsonify({"status": "error", "message": "권한이 없습니다."}), 403

    data = request.get_json(silent=True) or {}
    role = (data.get("role") or "").strip()
    user_id = data.get("user_id")
    year = data.get("year")

    if role != "president":
        return jsonify({"status": "error", "message": "지원하지 않는 role 입니다."}), 400
    if not user_id:
        return jsonify({"status": "error", "message": "사용자를 선택해주세요."}), 400

    try:
        year = int(year)
    except:
        return jsonify({"status": "error", "message": "year가 올바르지 않습니다."}), 400

    user = User.query.get(int(user_id))
    if not user:
        return jsonify({"status": "error", "message": "사용자를 찾을 수 없습니다."}), 404

    # ✅ 기존 상조회장(해당 연도)만 비활성화
    prev = MutualAidOfficer.query.filter_by(role="president", year=year, active=True).first()
    if prev:
        prev.active = False
        prev.ended_at = datetime.utcnow()

    # ✅ 신규 등록(해당 연도)
    new_off = MutualAidOfficer(
        role="president",
        year=year,
        user_id=user.id,
        active=True,
        appointed_by_id=current_user.id,
        appointed_at=datetime.utcnow(),
    )
    db.session.add(new_off)
    db.session.commit()

    return jsonify({"status": "success", "message": "선임 완료"})


@mutual_aid_bp.route("/ledger/add", methods=["POST"])
@login_required
def ledger_add():
    data = request.get_json(silent=True) or {}

    entry_date_str = (data.get("entry_date") or "").strip()  # "2026-01-09"
    entry_type = (data.get("entry_type") or "").strip()      # "income" | "expense"
    title = (data.get("title") or "").strip()
    amount_raw = data.get("amount")

    try:
        d = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
    except:
        return jsonify({"status": "error", "message": "날짜 형식이 올바르지 않습니다."}), 400
    
    if not can_mutual_aid_edit(current_user, d.year):
        return jsonify({"status": "error", "message": "입력 권한이 없습니다."}), 403
    
    # ✅ 결산된 연도는 입력 금지
    if MutualAidYearFinal.query.filter_by(year=d.year, finalized=True).first():
        return jsonify({"status": "error", "message": f"{d.year}년은 결산되어 입력할 수 없습니다."}), 400
    
    if entry_type not in ("income", "expense"):
        return jsonify({"status": "error", "message": "구분(income/expense)이 올바르지 않습니다."}), 400

    if not title:
        return jsonify({"status": "error", "message": "내용(항목명)을 입력해주세요."}), 400

    try:
        amount = int(str(amount_raw).replace(",", "").strip())
    except:
        return jsonify({"status": "error", "message": "금액이 올바르지 않습니다."}), 400

    if amount <= 0:
        return jsonify({"status": "error", "message": "금액은 0보다 커야 합니다."}), 400

    row = MutualAidLedger(
        entry_date=d,
        year=d.year,
        entry_type=entry_type,
        title=title,
        amount=amount,
        created_by_id=current_user.id,
    )
    try:
        db.session.add(row)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"DB 저장 실패: {str(e)}"}), 500

    return jsonify({"status": "success", "message": "등록 완료"})

@mutual_aid_bp.route("/ledger/delete/<int:ledger_id>", methods=["POST"])
@login_required
def ledger_delete(ledger_id):
    row = MutualAidLedger.query.get(ledger_id)
    if not row:
        return jsonify({"status": "error", "message": "내역을 찾을 수 없습니다."}), 404

    if not can_mutual_aid_edit(current_user, row.year):
        return jsonify({"status": "error", "message": "삭제 권한이 없습니다."}), 403
    
    # ✅ 결산된 연도는 삭제 금지
    if MutualAidYearFinal.query.filter_by(year=row.year, finalized=True).first():
        return jsonify({"status": "error", "message": f"{row.year}년은 결산되어 삭제할 수 없습니다."}), 400

    db.session.delete(row)
    db.session.commit()
    return jsonify({"status": "success", "message": "삭제 완료"})

@mutual_aid_bp.route("/ledger/update/<int:ledger_id>", methods=["POST"])
@login_required
def ledger_update(ledger_id):
    row = MutualAidLedger.query.get(ledger_id)
    if not row:
        return jsonify({"status": "error", "message": "내역을 찾을 수 없습니다."}), 404

    if not can_mutual_aid_edit(current_user, row.year):
        return jsonify({"status": "error", "message": "수정 권한이 없습니다."}), 403
    
    # ✅ 결산된 연도는 수정 금지(기존 연도)
    if MutualAidYearFinal.query.filter_by(year=row.year, finalized=True).first():
        return jsonify({"status": "error", "message": f"{row.year}년은 결산되어 수정할 수 없습니다."}), 400

    data = request.get_json(silent=True) or {}

    entry_date_str = (data.get("entry_date") or "").strip()
    entry_type = (data.get("entry_type") or "").strip()
    title = (data.get("title") or "").strip()
    amount_raw = data.get("amount")

    try:
        d = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
    except:
        return jsonify({"status": "error", "message": "날짜 형식이 올바르지 않습니다."}), 400
    
    # ✅ 결산된 연도는 수정 금지(변경 연도)
    if MutualAidYearFinal.query.filter_by(year=d.year, finalized=True).first():
        return jsonify({"status": "error", "message": f"{d.year}년은 결산되어 수정할 수 없습니다."}), 400


    if entry_type not in ("income", "expense"):
        return jsonify({"status": "error", "message": "구분(income/expense)이 올바르지 않습니다."}), 400

    if not title:
        return jsonify({"status": "error", "message": "내용(항목명)을 입력해주세요."}), 400

    try:
        amount = int(str(amount_raw).replace(",", "").strip())
    except:
        return jsonify({"status": "error", "message": "금액이 올바르지 않습니다."}), 400

    if amount <= 0:
        return jsonify({"status": "error", "message": "금액은 0보다 커야 합니다."}), 400

    # ✅ update
    row.entry_date = d
    row.year = d.year
    row.entry_type = entry_type
    row.title = title
    row.amount = amount

    db.session.commit()
    return jsonify({"status": "success", "message": "수정 완료"})


@mutual_aid_bp.route("/finalize/<int:year>", methods=["POST"])
@login_required
def finalize_year(year):
    # ✅ 권한: 총무과 or 해당년도 상조회장
    if not can_mutual_aid_edit(current_user, year):
        return jsonify({"status": "error", "message": "결산 권한이 없습니다."}), 403

    # 이미 결산됐으면 막기
    if MutualAidYearFinal.query.filter_by(year=year, finalized=True).first():
        return jsonify({"status": "error", "message": "이미 결산된 연도입니다."}), 400

    # ✅ 결산 잔액 계산:
    # - 이월: 이전년도 결산 잔액(있으면) / 없으면 누적 fallback
    prev_year = year - 1
    prev_final = MutualAidYearFinal.query.filter_by(year=prev_year, finalized=True).first()
    if prev_final:
        carryover = int(prev_final.closing_balance)
    else:
        prev_income = db.session.query(func.coalesce(func.sum(MutualAidLedger.amount), 0)) \
            .filter(MutualAidLedger.entry_type == "income", MutualAidLedger.year < year).scalar() or 0
        prev_expense = db.session.query(func.coalesce(func.sum(MutualAidLedger.amount), 0)) \
            .filter(MutualAidLedger.entry_type == "expense", MutualAidLedger.year < year).scalar() or 0
        carryover = int(prev_income) - int(prev_expense)

    # 해당년도 수입/지출
    income_y = db.session.query(func.coalesce(func.sum(MutualAidLedger.amount), 0)) \
        .filter(MutualAidLedger.entry_type == "income", MutualAidLedger.year == year).scalar() or 0
    expense_y = db.session.query(func.coalesce(func.sum(MutualAidLedger.amount), 0)) \
        .filter(MutualAidLedger.entry_type == "expense", MutualAidLedger.year == year).scalar() or 0

    closing = int(carryover) + int(income_y) - int(expense_y)

    fin = MutualAidYearFinal(
        year=year,
        finalized=True,
        closing_balance=closing,
        finalized_by_id=current_user.id,
        finalized_at=datetime.utcnow(),
    )
    db.session.add(fin)
    db.session.commit()

    return jsonify({"status": "success", "message": f"{year}년 결산 완료", "closing_balance": closing})

@mutual_aid_bp.route("/finalize/unlock/<int:year>", methods=["POST"])
@login_required
def unfinalize_year(year):
    if not current_user.is_superadmin:
        return jsonify({"status": "error", "message": "총관리자만 결산 해제할 수 있습니다."}), 403

    fin = MutualAidYearFinal.query.filter_by(year=year, finalized=True).order_by(MutualAidYearFinal.id.desc()).first()
    if not fin:
        return jsonify({"status": "error", "message": "해당 연도는 결산 상태가 아닙니다."}), 404

    try:
        db.session.delete(fin)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"결산 해제 DB 오류: {str(e)}"}), 500

    return jsonify({"status": "success", "message": f"{year}년 결산 해제 완료"})
