from flask import (
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    session,
    current_app,
    flash,
    send_from_directory,
    abort
)
from flask_login import login_required, current_user
from datetime import datetime, date
from app.employee import employee_bp
from app.models import (
    User,
    Vacation,
    EMPLOYMENT_STATUSES,
    AltLeaveLog,
    AltLeaveRecipient,
)
from app import db
from sqlalchemy import or_, and_
import os
from werkzeug.utils import secure_filename
import uuid
import secrets
import string

# =====================================================
# 연차/대체연차 시스템 제외 부서
# =====================================================
LEAVE_EXCLUDED_DEPARTMENTS = {
    "병동",
    "의료진",
}


# ✅ 한글(가나다) 정렬용 키
def hangul_sort_key(text: str):
    text = (text or "").strip()

    def char_key(ch: str):
        code = ord(ch)
        # 한글 음절(가~힣)
        if 0xAC00 <= code <= 0xD7A3:
            s = code - 0xAC00
            cho = s // 588
            jung = (s % 588) // 28
            jong = s % 28
            return (0, cho, jung, jong)
        # 영문/숫자
        if ch.isalnum():
            return (1, ch.lower())
        # 기타 문자
        return (2, code)

    return [char_key(ch) for ch in text]

def can_manage_employment_status():
    """
    직원 상태 변경 권한

    가능:
    1. master / 총관리자
    2. 총무과 소속 관리자

    불가:
    - 총무과 일반 직원
    - 다른 부서 관리자
    - 일반 직원
    """
    # master / 총관리자
    if bool(getattr(current_user, "is_superadmin", False)):
        return True

    department = (
        getattr(current_user, "department", "")
        or ""
    ).strip()

    is_admin = bool(
        getattr(current_user, "is_admin", False)
    )

    # 총무과이면서 관리자일 때만 허용
    return department == "총무과" and is_admin

# =====================================
# 직원 목록
# =====================================
@employee_bp.route("/list")
@login_required
def employee_list():
    user = current_user

    selected_status = (
        request.args.get("status", "재직중")
        or "재직중"
    ).strip()

    allowed_status_filters = {
        "전체",
        "재직중",
        "육아휴직",
        "출산휴가",
        "장기병가",
        "무급휴가",
        "퇴사",
    }

    if selected_status not in allowed_status_filters:
        selected_status = "재직중"

    # 🔹 총관리자 → 모든 부서 선택 가능 (직원이 없어도 기본 부서 항상 노출, '관리자'는 제외)
    if user.is_superadmin:
        # 1) 기본 부서 (직원이 없어도 드롭다운에 항상 보여줄 부서)
        base_departments = [
            "의료진",
            "임원진",
            "수술실",
            "물리치료",
            "도수",
            "외래",
            "영상의학과",
            "원무과",
            "병동",
            "총무과",
            "심사과",
            "홍보",
            "진단검사",
            "상담실",
            "영양",
            "약제부",
        ]
        
        dept_order = {d: i for i, d in enumerate(base_departments)}
        
        # 2) DB에 실제 존재하는 부서들 (None, '관리자' 제외)
        db_departments = (
            db.session.query(User.department)
            .distinct()
            .filter(User.department.isnot(None), User.department != "관리자")
            .all()
        )
        db_dept_list = [row[0] for row in db_departments]

        # 3) 기본 부서 + DB 부서 합쳐서 중복 제거 후 정렬
        # ✅ base_departments 순서 유지 + 추가 부서는 뒤에 가나다
        base_set = set(base_departments)
        extra_depts = sorted([d for d in db_dept_list if d and d not in base_set])
        departments = base_departments + extra_depts

        # 4) 현재 선택된 부서 (URL 파라미터가 없으면 "전체" 기본값)
        current_dept = request.args.get("dept", "all").strip()
        if not current_dept:
            current_dept = "all"

        # 5) 선택된 부서의 직원 목록
        if current_dept == "all":
            query = User.query.filter(
                User.department.isnot(None),
                User.department != "관리자"
            )

            if selected_status != "전체":
                query = query.filter(
                    User.employment_status == selected_status
                )

            employees_raw = query.all()
        else:
            if current_dept:
                query = User.query.filter(
                    User.department == current_dept
                )

                if selected_status != "전체":
                    query = query.filter(
                        User.employment_status == selected_status
                    )

                employees_raw = query.all()
            else:
                employees_raw = []


    # 🔹 일반 관리자 / 일반 사용자 → 자기 부서만
    else:
        current_dept = user.department
        departments = None

        if current_dept:
            query = User.query.filter(
                User.department == current_dept
            )

            if selected_status != "전체":
                query = query.filter(
                    User.employment_status == selected_status
                )

            employees_raw = query.all()
        else:
            employees_raw = []

    # =========================
    # 연차 / 대체연차 계산용 뷰 모델
    # =========================
    
    output = []
    for emp in employees_raw:
    
        # -------------------------
        # 1) 총 발생 연차 계산
        # -------------------------
        try:
            from app.leave_utils import calculate_annual_leave
            total_leave = calculate_annual_leave(emp.join_date)
        except Exception:
            total_leave = float(emp.remaining_days or 0.0)
    
        # 도입 전 사용 연차
        used_before = float(emp.used_before_system or 0.0)
    
        # -------------------------
        # 2) 승인된 휴가로 사용 연차 계산
        # -------------------------
        approved_vacs = Vacation.query.filter(
            Vacation.approved == True,
            or_(
                Vacation.target_user_id == emp.id,
                and_(
                    Vacation.target_user_id.is_(None),
                    Vacation.user_id == emp.id
                )
            )
        ).all()
    
        used_from_events = 0.0
        alt_used_from_events = 0.0

        for v in approved_vacs:
            t = (v.type or "").strip()

            if t == "연차":
                days = 1.0
            elif t == "토연차":
                days = 0.75
            elif t in ["반차", "반차(전)", "반차(후)"]:
                days = 0.5
            elif t == "반반차":
                days = 0.25
            else:
                days = 0.0

            used_from_events += days

            # ✅ 총무과/master가 대체연차로 지정한 휴가만 대체연차 사용으로 계산
            if bool(getattr(v, "is_alt", False)):
                alt_used_from_events += days

        used_total = round(used_before + used_from_events, 2)
        alt_used_total = round(alt_used_from_events, 2)
        annual_used_total = round(used_total - alt_used_total, 2)
    
        # -------------------------
        # 3) 총 발생 대체연차 계산
        #    ✅ 이름 문자열 검색 금지
        #    ✅ AltLeaveRecipient.user_id 기준
        # -------------------------
        if (emp.department or "").strip() in LEAVE_EXCLUDED_DEPARTMENTS:
            alt_total = 0.0
            alt_log_rows = []

        else:
            recipients = (
                AltLeaveRecipient.query
                .filter_by(user_id=emp.id)
                .all()
            )

            # ✅ 실제 이 직원에게 지급된 대체연차만 합산
            alt_total = round(
                sum(float(r.add_days or 0) for r in recipients),
                2
            )

            alt_log_rows = []

            for recipient in recipients:
                log = recipient.log

                if not log:
                    continue

                alt_log_rows.append({
                    "grant_date": log.grant_date,
                    "apply_date": log.apply_date,
                    "reason": log.reason,
                    "add_days": recipient.add_days,
                    "granted_by": log.granted_by,
                    "department_summary": log.department_summary,
                })
    
        # -------------------------
        # 4) 잔여 계산
        # -------------------------
        leave_excluded = (
            (emp.department or "").strip()
            in LEAVE_EXCLUDED_DEPARTMENTS
        )

        if leave_excluded:
            # ✅ 병동/의료진은 연차 시스템 미사용
            total_leave = 0.0
            used_total = 0.0
            annual_used_total = 0.0

            alt_total = 0.0
            alt_used_total = 0.0

            annual_left = 0.0
            alt_left = 0.0

        else:
            # ✅ 일반 부서
            alt_left = round(
                float(alt_total or 0) - alt_used_total,
                2
            )

            annual_left = round(
                float(total_leave or 0) - annual_used_total,
                2
            )
    
        # -------------------------
        # 5) 출력 데이터 구성
        # -------------------------
        output.append({
            "id": emp.id,
            "department": emp.department,   # ✅ 추가
            "name": emp.name or emp.username,
            "username": emp.username,
            "employment_status": emp.employment_status or "재직중",
            "status_changed_at": emp.status_changed_at,
            "resign_date": emp.resign_date,
            "join_date": emp.join_date,
            "total_leave": total_leave,
            "used_total": used_total,
            "remaining_days": annual_left,
            "alt_total": alt_total,
            "total_alt_leave": alt_total,
            "alt_left": alt_left,
            "is_admin": emp.is_admin,

            # ✅ 추가
            "phone": emp.phone,

            # ✅ 추가
            "signature_image": emp.signature_image,
        })

    sort = request.args.get("sort", "").strip()  # "", "name", "join_date"

    if sort == "name":
        output.sort(key=lambda x: hangul_sort_key(x.get("name")))

    elif sort == "join_date":
        from datetime import date
        def join_key(x):
            jd = x.get("join_date")
            return jd if jd else date.max
        output.sort(key=join_key)

    else:
        # ✅ 정렬 파라미터가 없을 때만 기본 정렬 (전체 보기)
        if user.is_superadmin and current_dept == "all":
            from datetime import date, datetime

            def join_key(v):
                jd = v.get("join_date")
                if jd is None:
                    return date.max
                if isinstance(jd, datetime):
                    return jd.date()
                return jd  # Date 타입이면 그대로 OK

            # ✅ 부서(지정 순서) → 입사일(빠른순) → 이름(가나다)
            output.sort(key=lambda x: (
                dept_order.get(x.get("department"), 9999),
                join_key(x),
                hangul_sort_key(x.get("name"))
            ))

    return render_template(
        "employee_list.html",
        employees=output,
        current_dept=current_dept,
        departments=departments,
        is_superadmin=user.is_superadmin,
        sort=sort,  # ✅ 추가
        selected_status=selected_status,
        can_manage_status=can_manage_employment_status(),
    )


# =====================================
# 직원별 휴가 사용 내역
# =====================================

def vacation_used_days(vacation):
    """
    휴가 종류별 사용일수 계산
    직원관리 페이지 계산 기준과 동일하게 맞춤
    """
    t = (vacation.type or "").strip()

    if t == "연차":
        return 1.0
    elif t == "토연차":
        return 0.75
    elif t in ["반차", "반차(전)", "반차(후)"]:
        return 0.5
    elif t == "반반차":
        return 0.25

    # 사용 연차에 포함하지 않는 유형
    return 0.0


def can_view_employee_vacation_history(target_user):
    """
    직원별 휴가 사용 내역 접근 권한

    접근 가능:
    1. 총관리자 / master
    2. 해당 직원과 같은 부서의 관리자
    3. 총무과 직원
    """
    if current_user.is_superadmin:
        return True

    if current_user.department == "총무과":
        return True

    if current_user.is_admin and current_user.department == target_user.department:
        return True

    return False

def build_annual_leave_breakdown(join_date_value):
    """
    총 발생 연차 상세 계산 내역
    - 입사 1년 후부터 15개
    - 이후 2년마다 +1
    - 최대 25개
    - 2017-06-01 이후 입사자는 첫해 월차 최대 11개 추가
    """
    if not join_date_value:
        return [], 0.0

    if isinstance(join_date_value, str):
        try:
            join_date = datetime.strptime(join_date_value[:10], "%Y-%m-%d").date()
        except Exception:
            return [], 0.0
    else:
        join_date = join_date_value

    today = date.today()
    rows = []
    total = 0.0

    monthly_cutoff = date(2017, 6, 1)

    # ✅ 2017-06-01 이후 입사자: 첫해 월차 최대 11개
    if join_date >= monthly_cutoff:
        first_year_months = min(11, max(0, (min(today, date(join_date.year + 1, join_date.month, join_date.day)) - join_date).days // 30))
        if first_year_months > 0:
            rows.append({
                "year": join_date.year,
                "label": "입사 1년 미만 월차",
                "formula": f"1개월 개근 × {first_year_months}개월",
                "days": float(first_year_months),
            })
            total += float(first_year_months)

    # ✅ 입사 1년 후부터 매년 발생
    service_year = 1

    while True:
        grant_year = join_date.year + service_year
        grant_date = date(grant_year, join_date.month, join_date.day)

        if grant_date > today:
            break

        # 1~2년차 15개, 3~4년차 16개, 5~6년차 17개...
        annual_days = min(25, 15 + ((service_year - 1) // 2))

        rows.append({
            "year": grant_year,
            "label": f"{service_year}년차",
            "formula": f"15 + floor(({service_year} - 1) / 2)",
            "days": float(annual_days),
        })

        total += float(annual_days)
        service_year += 1

    return rows, round(total, 2)

@employee_bp.route("/vacation_history/<int:emp_id>")
@login_required
def employee_vacation_history(emp_id):
    target_user = User.query.get_or_404(emp_id)

    # ✅ 권한 체크
    if not can_view_employee_vacation_history(target_user):
        abort(403)

    # ✅ 해당 직원의 휴가 전체 조회
    # - 본인이 직접 신청한 휴가: user_id
    # - 관리자가 대신 등록한 휴가/일정: target_user_id
    vacations = (
        Vacation.query
        .filter(
            or_(
                # ✅ 현재 표준: 실제 휴가/일정 주인
                Vacation.target_user_id == target_user.id,

                # ✅ 예전 데이터 보완:
                # target_user_id가 비어 있는 옛날 기록만 user_id로 조회
                and_(
                    Vacation.target_user_id.is_(None),
                    Vacation.user_id == target_user.id
                )
            )
        )
        .order_by(
            Vacation.start_date.desc(),
            Vacation.created_at.desc()
        )
        .all()
    )
    exclude_history_types = ["탄력근무", "근무자", "일정"]

    # ✅ 휴가 상세 row 구성
    vacation_rows = []

    approved_used_from_events = 0.0
    alt_used_from_events = 0.0
    pending_count = 0
    approved_count = 0

    type_summary = {}

    for v in vacations:
        v_type = (v.type or "").strip()

        # ✅ 직원별 휴가 사용 내역에서는 연차와 무관한 항목 제외
        if v_type in exclude_history_types:
            continue

        used_days = vacation_used_days(v)

        if v.approved:
            approved_count += 1
            approved_used_from_events += used_days

            # ✅ 대체연차로 지정된 휴가만 대체연차 사용으로 계산
            if bool(getattr(v, "is_alt", False)):
                alt_used_from_events += used_days

            type_name = (v.type or "기타").strip()
            type_summary[type_name] = round(
                type_summary.get(type_name, 0.0) + used_days,
                2
            )
        else:
            pending_count += 1

        vacation_rows.append({
            "id": v.id,
            "start_date": v.start_date,
            "end_date": v.end_date,
            "type": v.type,
            "approved": v.approved,
            "used_days": used_days,
            "memo": v.memo,
            "start_time": v.start_time,
            "end_time": v.end_time,
            "created_at": v.created_at,
            "department": v.department,
            "is_alt": v.is_alt,
        })

    # ✅ 총 발생 연차 계산
    try:
        from app.leave_utils import calculate_annual_leave
        total_leave = calculate_annual_leave(target_user.join_date)
    except Exception:
        total_leave = float(target_user.remaining_days or 0.0)

    # ✅ 총 발생 연차 상세 계산 내역
    annual_breakdown_rows, annual_breakdown_total = build_annual_leave_breakdown(
        target_user.join_date
    )

    # ✅ 도입 전 사용 연차
    used_before = float(target_user.used_before_system or 0.0)

    # ✅ 총 사용 연차
    used_total = round(used_before + approved_used_from_events, 2)
    alt_used_total = round(alt_used_from_events, 2)
    annual_used_total = round(used_total - alt_used_total, 2)

    # =====================================================
    # ✅ 대체연차 총 발생 + 부여 이력
    # - AltLeaveRecipient.user_id로 정확하게 조회
    # - 이름 문자열 검색 완전 제거
    # =====================================================
    try:
        if (
            (target_user.department or "").strip()
            in LEAVE_EXCLUDED_DEPARTMENTS
        ):
            alt_total = 0.0
            alt_log_rows = []

        else:
            recipients = (
                AltLeaveRecipient.query
                .filter_by(user_id=target_user.id)
                .all()
            )

            alt_total = round(
                sum(
                    float(r.add_days or 0)
                    for r in recipients
                ),
                2
            )

            # ✅ 개인 대체연차 부여 이력
            alt_log_rows = []

            for recipient in recipients:
                log = recipient.log

                if not log:
                    continue

                alt_log_rows.append({
                    "grant_date": log.grant_date,
                    "apply_date": log.apply_date,
                    "reason": log.reason,
                    "add_days": recipient.add_days,
                    "granted_by": log.granted_by,
                    "department_summary": log.department_summary,
                })

            # ✅ 최근 적용일자 순
            alt_log_rows.sort(
                key=lambda row: (
                    row["apply_date"] or date.min,
                    row["grant_date"] or datetime.min,
                ),
                reverse=True,
            )

    except Exception as e:
        print(
            "⚠️ 대체연차 지급이력 조회 오류:",
            target_user.id,
            e
        )

        alt_total = 0.0
        alt_log_rows = []

    # =====================================================
    # ✅ 잔여 연차 / 대체연차
    # =====================================================
    leave_excluded = (
        (target_user.department or "").strip()
        in LEAVE_EXCLUDED_DEPARTMENTS
    )

    if leave_excluded:
        # 병동 / 의료진은 연차시스템 대상 제외
        total_leave = 0.0
        used_before = 0.0
        used_total = 0.0

        approved_used_from_events = 0.0
        alt_used_total = 0.0
        annual_used_total = 0.0

        alt_total = 0.0
        alt_left = 0.0
        annual_left = 0.0

        annual_breakdown_rows = []
        annual_breakdown_total = 0.0

    else:
        # ✅ 대체연차
        alt_left = round(
            float(alt_total or 0)
            - float(alt_used_total or 0),
            2
        )

        # ✅ 일반 연차
        annual_left = round(
            float(total_leave or 0)
            - float(annual_used_total or 0),
            2
        )

    summary = {
        "total_leave": total_leave,
        "used_before": used_before,
        "approved_used_from_events": round(approved_used_from_events, 2),
        "used_total": used_total,
        "annual_used_total": annual_used_total,
        "remaining_days": annual_left,
        "alt_total": round(alt_total, 2),
        "alt_used_total": alt_used_total,
        "alt_left": alt_left,
        "approved_count": approved_count,
        "pending_count": pending_count,
        "type_summary": type_summary,
    }

    return render_template(
        "employee_vacation_history.html",
        target_user=target_user,
        vacation_rows=vacation_rows,
        summary=summary,
        alt_log_rows=alt_log_rows,
        annual_breakdown_rows=annual_breakdown_rows,
        annual_breakdown_total=annual_breakdown_total,
    )

# =======================
# 아이디 중복 체크 (AJAX)
# =======================
@employee_bp.route("/check_username")
@login_required
def check_username():
    username = request.args.get("username", "").strip().lower()

    if not username:
        return jsonify({"exists": False})

    exists = User.query.filter_by(username=username).first() is not None
    return jsonify({"exists": exists})

# =====================================
# 직원 등록
# =====================================
@employee_bp.route("/register", methods=["GET", "POST"])
@login_required
def employee_register():
    user = current_user

    # ✅ 권한 체크
    if not (user.is_admin or user.is_superadmin):
        flash("직원 등록 권한이 없습니다.", "error")
        return redirect(url_for("calendar.calendar_page"))

    # =========================
    # POST: 실제 직원 등록 처리
    # =========================
    if request.method == "POST":
        username   = request.form.get("username", "").strip().lower()
        first_name = request.form.get("first_name", "").strip()
        last_name  = request.form.get("last_name", "").strip()
        department = request.form.get("department", "").strip()
        join_date  = request.form.get("join_date", "").strip()
        birthday   = request.form.get("birthday", "").strip()
        address    = request.form.get("address", "").strip()
        password   = request.form.get("password", "").strip()
        phone      = request.form.get("phone", "").strip()

        # 🔹 부서 미선택 방지
        if not department:
            flash("부서를 선택해주세요.", "error")
            return redirect(url_for("employee.employee_register"))
    
        # 🔹 아이디 중복 체크
        if User.query.filter_by(username=username).first():
            flash("이미 존재하는 아이디입니다.", "error")
            return redirect(url_for("employee.employee_register"))

        full_name = f"{last_name}{first_name}".strip()

        new_user = User(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            name=full_name,
            department=department,
            join_date=join_date,
            birthday=birthday,
            address=address,
            phone=phone,  # ✅ 추가
            remaining_days=15,
            is_admin=False,
            is_superadmin=False,
            # ✅ 신규 직원 기본 상태
            employment_status="재직중",
            status_changed_at=date.today(),
            resign_date=None,
        )

        db.session.add(new_user)
        db.session.commit()

        flash("직원 등록이 완료되었습니다.", "success")
        return redirect(url_for("employee.employee_list", dept=department))

    # =========================
    # GET: 폼 화면 렌더링 (여기가 드롭다운 핵심)
    # =========================

    if user.is_superadmin:
        # 🔹 기본 부서 리스트
        base_departments = [
            "의료진",
            "임원진",
            "수술실",
            "물리치료",
            "도수",
            "외래",
            "영상의학과",
            "원무과",
            "병동",
            "총무과",
            "심사과",
            "홍보",
            "진단검사",
            "상담실",
            "영양",
            "약제부",
        ]

        # 🔹 DB 에 실제 존재하는 부서들 (관리자 제외)
        db_departments = (
            db.session.query(User.department)
            .distinct()
            .filter(User.department.isnot(None), User.department != "관리자")
            .all()
        )
        # db_departments 는 [("수술실",), ("원무과",) ...] 이런 형태라 [0] 으로 값만 꺼냄
        db_dept_list = [row[0] for row in db_departments]

        dept_list = sorted(set(base_departments + db_dept_list))

        current_dept = None  # 총관리자는 고정 부서가 없으니 템플릿에서 안 씀
    else:
        # 🔹 일반 관리자 → 자신의 부서만 고정
        dept_list = []  # 드롭다운 안 쓰므로 빈 리스트
        current_dept = user.department

    return render_template(
        "employee_register.html",
        dept_list=dept_list,            # 총관리자면 부서 드롭다운에 사용
        current_dept=current_dept,      # 일반 관리자일 때 읽기전용 인풋에 사용
        is_superadmin=user.is_superadmin,
        is_admin=user.is_admin,
    )

# =====================================
# 직원 수정
# =====================================
@employee_bp.route("/edit/<int:emp_id>", methods=["GET", "POST"])
@login_required
def edit_employee(emp_id):
    # ✅ 권한 체크 (지금 쓰던 로직 그대로 유지)
    if not (current_user.is_admin or current_user.is_superadmin):
        flash("수정 권한이 없습니다.", "error")
        return redirect(url_for("employee.employee_list"))

    emp = User.query.get_or_404(emp_id)

    # ✅ 기본 부서 목록 (직원등록/직원관리와 맞춤)
    base_departments = [
        "의료진",
        "임원진",
        "수술실",
        "물리치료",
        "도수",
        "외래",
        "영상의학과",
        "원무과",
        "병동",
        "총무과",
        "심사과",
        "홍보",
        "진단검사",
        "상담실",
        "영양",
        "약제부",
    ]


    # DB에 실제 존재하는 부서들 (None, '관리자' 제외)
    db_departments = (
        db.session.query(User.department)
        .distinct()
        .filter(User.department.isnot(None), User.department != "관리자")
        .all()
    )
    db_dept_list = [row[0] for row in db_departments]

    # 최종 부서 리스트 (중복 제거 + 정렬)
    dept_list = sorted(set(base_departments + db_dept_list))

    if request.method == "POST":
        # 🔹 폼 값 읽기
        emp.first_name = request.form.get("first_name", "").strip()
        emp.last_name  = request.form.get("last_name", "").strip()
        emp.name       = f"{emp.last_name}{emp.first_name}".strip()

        emp.department = request.form.get("department", "").strip()
        emp.join_date  = request.form.get("join_date") or None
        emp.birthday   = request.form.get("birthday") or None
        emp.address    = request.form.get("address", "").strip()
        emp.phone      = request.form.get("phone", "").strip()

        # =====================================
        # 직원 상태 및 상태 기간 변경
        # master 또는 총무과 직원만 가능
        # =====================================
        if can_manage_employment_status():

            new_status = (
                request.form.get("employment_status")
                or emp.employment_status
                or "재직중"
            ).strip()

            if new_status not in EMPLOYMENT_STATUSES:
                flash("올바르지 않은 직원 상태입니다.", "error")
                return redirect(
                    url_for(
                        "employee.edit_employee",
                        emp_id=emp.id
                    )
                )

            status_start_raw = (
                request.form.get("status_start_date")
                or ""
            ).strip()

            status_end_raw = (
                request.form.get("status_end_date")
                or ""
            ).strip()

            try:
                new_status_start = (
                    datetime.strptime(
                        status_start_raw,
                        "%Y-%m-%d"
                    ).date()
                    if status_start_raw else None
                )

                new_status_end = (
                    datetime.strptime(
                        status_end_raw,
                        "%Y-%m-%d"
                    ).date()
                    if status_end_raw else None
                )

            except ValueError:
                flash(
                    "상태 시작일 또는 종료일의 날짜 형식이 올바르지 않습니다.",
                    "error"
                )
                return redirect(
                    url_for(
                        "employee.edit_employee",
                        emp_id=emp.id
                    )
                )

            old_status = (
                emp.employment_status
                or "재직중"
            ).strip()

            # ---------------------------------
            # 재직중
            # 날짜와 퇴사일 모두 비움
            # ---------------------------------
            if new_status == "재직중":
                emp.employment_status = "재직중"
                emp.status_start_date = None
                emp.status_end_date = None
                emp.resign_date = None

            # ---------------------------------
            # 퇴사
            # 시작일 필수, 종료일은 사용하지 않음
            # ---------------------------------
            elif new_status == "퇴사":
                if not new_status_start:
                    flash(
                        "퇴사 상태는 퇴사일을 입력해야 합니다.",
                        "error"
                    )
                    return redirect(
                        url_for(
                            "employee.edit_employee",
                            emp_id=emp.id
                        )
                    )

                emp.employment_status = "퇴사"
                emp.status_start_date = new_status_start
                emp.status_end_date = None
                emp.resign_date = new_status_start

                # 퇴사 시 관리자 권한 자동 해제
                emp.is_admin = False

            # ---------------------------------
            # 육아휴직·출산휴가·장기병가·무급휴가
            # 시작일과 종료일 모두 필수
            # ---------------------------------
            else:
                if not new_status_start or not new_status_end:
                    flash(
                        f"{new_status} 상태는 시작일과 종료일을 모두 입력해야 합니다.",
                        "error"
                    )
                    return redirect(
                        url_for(
                            "employee.edit_employee",
                            emp_id=emp.id
                        )
                    )

                if new_status_end < new_status_start:
                    flash(
                        "상태 종료일은 시작일보다 빠를 수 없습니다.",
                        "error"
                    )
                    return redirect(
                        url_for(
                            "employee.edit_employee",
                            emp_id=emp.id
                        )
                    )

                emp.employment_status = new_status
                emp.status_start_date = new_status_start
                emp.status_end_date = new_status_end
                emp.resign_date = None

            # 실제 상태가 바뀐 경우에만 상태 변경일 갱신
            if old_status != new_status:
                emp.status_changed_at = date.today()             

        # 비밀번호 수정 필드가 있으면 반영 (없으면 그냥 무시돼도 상관 없음)
        password = request.form.get("password")
        if password:
            emp.password = password
            
        # ✅ 시스템 도입 이전 사용 연차 저장
        used_before = request.form.get("used_before_system", "").strip()
        emp.used_before_system = float(used_before) if used_before else 0.0


        db.session.commit()

        flash("직원 정보가 수정되었습니다.", "success")
        # 수정한 부서로 돌아가도록 dept 파라미터 전달
        return redirect(url_for("employee.employee_list", dept=emp.department))

    # 🔹 GET → 수정 폼 렌더링
    pw_reset_msg = session.pop("pw_reset_msg", None)
    pw_reset_cat = session.pop("pw_reset_cat", None)

    return render_template(
        "edit_employee.html",
        employee=emp,
        dept_list=dept_list,
        pw_reset_msg=pw_reset_msg,
        pw_reset_cat=pw_reset_cat,
        can_manage_status=can_manage_employment_status(),
    )



# =====================================
# 관리자 지정 / 해제
# =====================================
@employee_bp.route("/toggle_admin/<int:emp_id>", methods=["POST"])
@login_required
def toggle_admin(emp_id):
    if not current_user.is_superadmin:
        return jsonify({"status": "error", "message": "총관리자만 변경 가능합니다."})

    emp = User.query.get_or_404(emp_id)
    emp.is_admin = not emp.is_admin
    db.session.commit()

    return jsonify({
        "status": "success",
        "message": "관리자 권한이 변경되었습니다."
    })

@employee_bp.route("/signature/<path:filename>")
@login_required
def signature_file(filename):
    if not (getattr(current_user, "is_superadmin", False) or getattr(current_user, "is_admin", False)):
        abort(403)


    sig_dir = current_app.config["SIGNATURES_FOLDER"]
    return send_from_directory(sig_dir, filename)


# =====================================
# 서명 이미지 업로드 (총관리자 전용)
# =====================================
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}

@employee_bp.route("/upload_signature", methods=["POST"])
@login_required
def upload_signature():
    if not current_user.is_superadmin:
        return jsonify({"status": "error", "message": "총관리자만 가능합니다."}), 403

    user_id = request.form.get("user_id")
    file = request.files.get("signature")

    if not user_id or not file or file.filename.strip() == "":
        return jsonify({"status": "error", "message": "잘못된 요청입니다."}), 400

    user = User.query.get_or_404(user_id)

    # 저장 폴더
    sig_dir = current_app.config["SIGNATURES_FOLDER"]
    os.makedirs(sig_dir, exist_ok=True)

    # 확장자 체크
    ext = os.path.splitext(file.filename.lower())[1]
    if ext not in ALLOWED_EXT:
        return jsonify({"status": "error", "message": "png/jpg/jpeg/webp만 업로드 가능합니다."}), 400

    # 기존 파일 삭제
    if user.signature_image:
        old_name = user.signature_image.split("/")[-1]
        old_path = os.path.join(sig_dir, old_name)
        if os.path.exists(old_path):
            os.remove(old_path)

    # 새 파일명
    new_name = secure_filename(f"sig_{user.id}_{uuid.uuid4().hex}{ext}")
    save_path = os.path.join(sig_dir, new_name)
    file.save(save_path)

    current_app.logger.info(
        "✅ SIGNATURE SAVED: path=%s exists=%s size=%s",
        save_path,
        os.path.exists(save_path),
        os.path.getsize(save_path) if os.path.exists(save_path) else -1
    )

    # DB 저장 (파일명만 저장하는 방식 권장)
    user.signature_image = new_name
    db.session.commit()

    # ✅ 프론트에서 바로 쓸 URL 같이 반환
    sig_url = url_for("employee.signature_file", filename=new_name)

    return jsonify({
        "status": "success",
        "message": "서명 이미지가 저장되었습니다.",
        "signature_filename": new_name,
        "signature_url": sig_url
    })

# =====================================
# 직원 완전 삭제 차단
# =====================================
@employee_bp.route("/delete/<int:emp_id>", methods=["POST"])
@login_required
def delete_employee(emp_id):
    return jsonify({
        "status": "error",
        "message": "직원 완전 삭제 기능은 중단되었습니다. 직원 상태를 변경해주세요."
    }), 403

# =====================================
# 직원 상태 변경
# 총무과 직원 또는 master만 가능
# =====================================
@employee_bp.route("/status/<int:emp_id>", methods=["POST"])
@login_required
def update_employee_status(emp_id):
    if not can_manage_employment_status():
        return jsonify({
            "status": "error",
            "message": "직원 상태는 총관리자와 총무과 관리자만 변경할 수 있습니다."
        }), 403

    emp = User.query.get_or_404(emp_id)

    # master 계정 자체는 상태 변경 금지
    if emp.is_superadmin or emp.username == "master":
        return jsonify({
            "status": "error",
            "message": "총관리자 계정의 상태는 변경할 수 없습니다."
        }), 400

    data = request.get_json(silent=True) or {}
    new_status = (data.get("employment_status") or "").strip()

    if new_status not in EMPLOYMENT_STATUSES:
        return jsonify({
            "status": "error",
            "message": "올바르지 않은 직원 상태입니다."
        }), 400

    old_status = emp.employment_status or "재직중"
    today = date.today()

    emp.employment_status = new_status
    emp.status_changed_at = today

    if new_status == "퇴사":
        emp.resign_date = today
        emp.status_start_date = today
        emp.status_end_date = None
        emp.is_admin = False

    elif new_status == "재직중":
        emp.resign_date = None
        emp.status_start_date = None
        emp.status_end_date = None

    else:
        # 육아휴직·출산휴가·장기병가·무급휴가
        emp.resign_date = None

        # 상태를 처음 변경한 날을 기본 시작일로 기록
        if old_status != new_status:
            emp.status_start_date = today

        # 종료일은 직원 수정 페이지에서 입력
        emp.status_end_date = None

    db.session.commit()

    return jsonify({
        "status": "success",
        "message": (
            f"{emp.name or emp.username} 직원의 상태가 "
            f"'{old_status}'에서 '{new_status}'(으)로 변경되었습니다."
        ),
        "employee_id": emp.id,
        "employment_status": emp.employment_status,
        "status_changed_at": (
            emp.status_changed_at.isoformat()
            if emp.status_changed_at else None
        ),
        "resign_date": (
            emp.resign_date.isoformat()
            if emp.resign_date else None
        ),
    })


# =====================================
# 서명 이미지 삭제 (총관리자 전용)
# =====================================
@employee_bp.route("/delete_signature/<int:user_id>", methods=["POST"])
@login_required
def delete_signature(user_id):
    if not current_user.is_superadmin:
        return jsonify({"status": "error", "message": "권한이 없습니다."}), 403

    user = User.query.get_or_404(user_id)

    # 파일 삭제
    if user.signature_image:
        sig_dir = current_app.config["SIGNATURES_FOLDER"]
        fname = user.signature_image.split("/")[-1]
        fpath = os.path.join(sig_dir, fname)
        if os.path.exists(fpath):
            os.remove(fpath)

    user.signature_image = None
    db.session.commit()

    return jsonify({"status": "success", "message": "서명이 삭제되었습니다."})

@employee_bp.route("/reset_password/<int:emp_id>", methods=["POST"])
@login_required
def reset_employee_password(emp_id):
    # ✅ 총관리자만
    if not current_user.is_superadmin:
        flash("총관리자만 비밀번호 초기화가 가능합니다.", "error")
        return redirect(url_for("employee.employee_list"))

    emp = User.query.get_or_404(emp_id)

    # ✅ 임시 비밀번호 생성 (영문+숫자 10자리)
    alphabet = string.ascii_letters + string.digits
    temp_pw = "".join(secrets.choice(alphabet) for _ in range(10))

    # ✅ 비밀번호 교체
    emp.password = temp_pw
    db.session.commit()

    # ✅ edit_employee와 동일한 dept_list 생성(렌더링에 필요)
    base_departments = [
        "의료진","임원진","수술실","물리치료","도수","외래","영상의학과","원무과","병동",
        "총무과","심사과","홍보","진단검사","상담실","영양","약제부",
    ]
    db_departments = (
        db.session.query(User.department)
        .distinct()
        .filter(User.department.isnot(None), User.department != "관리자")
        .all()
    )
    db_dept_list = [row[0] for row in db_departments]
    dept_list = sorted(set(base_departments + db_dept_list))

    # ✅ redirect/flash 없이 “바로” 렌더링 (무조건 화면에 표시됨)
    return render_template(
        "edit_employee.html",
        employee=emp,
        dept_list=dept_list,
        pw_reset_msg=f"✅ {emp.name or emp.username} 임시 비밀번호: {temp_pw}  (지금 복사해두세요)",
        pw_reset_cat="success",
        can_manage_status=can_manage_employment_status(),
    )




