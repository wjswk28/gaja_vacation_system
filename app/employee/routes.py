from flask import (
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    session,
    flash
)
from flask_login import login_required, current_user
from datetime import datetime, date
from app.employee import employee_bp
from app.models import User, Vacation
from app import db
from sqlalchemy import or_


# =====================================
# 직원 목록
# =====================================
@employee_bp.route("/list")
@login_required
def employee_list():
    user = current_user

    # 🔹 총관리자 → 모든 부서 선택 가능 (직원이 없어도 기본 부서 항상 노출, '관리자'는 제외)
    if user.is_superadmin:
        # 1) 기본 부서 (직원이 없어도 드롭다운에 항상 보여줄 부서)
        base_departments = [
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
        ]

        # 2) DB에 실제 존재하는 부서들 (None, '관리자' 제외)
        db_departments = (
            db.session.query(User.department)
            .distinct()
            .filter(User.department.isnot(None), User.department != "관리자")
            .all()
        )
        db_dept_list = [row[0] for row in db_departments]

        # 3) 기본 부서 + DB 부서 합쳐서 중복 제거 후 정렬
        departments = sorted(set(base_departments + db_dept_list))

        # 4) 현재 선택된 부서 (URL 파라미터가 없으면 첫 번째 부서를 기본값으로)
        current_dept = request.args.get("dept", "").strip()
        if not current_dept:
            current_dept = departments[0] if departments else ""

        # 5) 선택된 부서의 직원 목록
        if current_dept:
            employees_raw = User.query.filter_by(department=current_dept).all()
        else:
            employees_raw = []

    # 🔹 일반 관리자 / 일반 사용자 → 자기 부서만
    else:
        current_dept = user.department
        departments = None  # 템플릿에서 드롭다운 숨길 때 사용
        employees_raw = User.query.filter_by(department=current_dept).all() if current_dept else []

        # =========================
    # 연차 / 대체연차 계산용 뷰 모델
    # =========================
    output = []
    for emp in employees_raw:
        # 🔹 총 연차 (입사일 기준 계산, 실패 시 기존 remaining_days 사용)
        try:
            from app.leave_utils import calculate_annual_leave
            total_leave = calculate_annual_leave(emp.join_date)
        except Exception:
            total_leave = float(emp.remaining_days or 0)

        # 🔹 시스템 도입 전 사용 연차
        used_before = float(emp.used_before_system or 0.0)

        # 🔹 Vacation 테이블에서 승인된 휴가만 집계
        approved_vacs = Vacation.query.filter(
            Vacation.approved.is_(True),
            or_(Vacation.user_id == emp.id,
                Vacation.target_user_id == emp.id)
        ).all()

        used_from_events = 0.0
        for v in approved_vacs:
            t = (v.type or "").strip()

            # ✅ 연차/반차/반반차/토연차만 "사용 연차"로 계산
            if t == "연차":
                used_from_events += 1.0
            elif t == "토연차":
                used_from_events += 0.75
            elif t in ["반차", "반차(전)", "반차(후)"]:
                used_from_events += 0.5
            elif t == "반반차":
                used_from_events += 0.25
            # 병가, 예비군, 탄력근무, 근무자 등은 여기선 0으로 둠

        # 🔹 최종 사용 연차 = (도입 전) + (승인된 일정)
        used_total = round(used_before + used_from_events, 2)

        # ---------------------------------------------------------
        # 대체연차 계산 (AltLeaveLog 기반 / 정확한 이름 매칭)
        # ---------------------------------------------------------
        from app.models import AltLeaveLog
        
        # 직원 정식 이름
        name_key = (emp.first_name or emp.name or emp.username).strip()
        
        logs_all = AltLeaveLog.query.order_by(AltLeaveLog.grant_date.desc()).all()
        
        my_alt_logs = []
        
        for log in logs_all:
            summary = log.department_summary or ""
            
            # summary 예시: "수술실(김영선, 이주현)"
            if "(" in summary and ")" in summary:
                inside = summary.split("(")[1].split(")")[0]
                names = [n.strip() for n in inside.split(",")]
                
                if name_key in names:
                    my_alt_logs.append(log)
        
        # 실제 총 발생 대체연차 계산
        alt_total = sum(log.add_days for log in my_alt_logs)



        # 🔹 대체연차 우선 차감 로직
        if used_total <= alt_total:
            alt_left = round(alt_total - used_total, 2)
            annual_left = float(total_leave)    # 그대로 유지
        else:
            remain_use = used_total - alt_total
            alt_left = 0.0
            annual_left = round(float(total_leave) - remain_use, 2)   # ← 음수 허용


        output.append({
            "id": emp.id,
            "name": emp.name or emp.username,
            "username": emp.username,
            "join_date": emp.join_date,
            "total_leave": total_leave,
            "used_total": used_total,           # 직원관리 테이블의 '사용'
            "remaining_days": annual_left,      # 직원관리 테이블의 '잔여'
            "alt_total": alt_total,             # 총 발생 대체연차 (이제 total_alt_leave)
            "total_alt_leave": alt_total,       # ⭐ 템플릿에서 emp.total_alt_leave 를 쓰므로 반드시 필요
            "alt_left": alt_left,               # 남은 대체연차 (alt_leave 기반)
            "is_admin": emp.is_admin,
        })


    return render_template(
        "employee_list.html",
        employees=output,
        current_dept=current_dept,
        departments=departments,
        is_superadmin=user.is_superadmin,
    )

# =======================
# 아이디 중복 체크 (AJAX)
# =======================
@employee_bp.route("/check_username")
@login_required
def check_username():
    """
    ?username=master 이런 식으로 GET 요청 보내서
    해당 아이디가 이미 존재하는지 True/False 를 돌려준다.
    엔드포인트 이름은 'employee.check_username' 이 된다.
    """
    username = request.args.get("username", "").strip()

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
        username   = request.form.get("username", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_name  = request.form.get("last_name", "").strip()
        department = request.form.get("department", "").strip()
        join_date  = request.form.get("join_date", "").strip()
        birthday   = request.form.get("birthday", "").strip()
        address    = request.form.get("address", "").strip()
        password   = request.form.get("password", "").strip()

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
            remaining_days=15,
            is_admin=False,
            is_superadmin=False,
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


    # =========================
    # GET: 폼 화면 렌더링 (여기가 중요!)
    # =========================

    # 🔹 총관리자면 = 드롭다운에 쓸 부서 목록 준비
    if user.is_superadmin:
        # 기본 부서 리스트
        base_departments = [
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
        ]

        # DB에 실제 존재하는 부서들(관리자 제외)
        db_departments = (
            db.session.query(User.department)
            .distinct()
            .filter(User.department.isnot(None), User.department != "관리자")
            .all()
        )
        db_dept_list = [d[0] for d in db_departments]

        dept_list = sorted(set(base_departments + db_dept_list))
        current_dept = None  # 템플릿에서 사용 X, 그냥 형태 맞추기용
    else:
        # 일반 관리자 → 자신의 부서만 고정
        dept_list = []
        current_dept = user.department

    return render_template(
        "employee_register.html",
        dept_list=dept_list,
        current_dept=current_dept,
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

    # 🔹 GET → 수정 폼 렌더링 (employee + dept_list 넘겨주기)
    return render_template(
        "edit_employee.html",
        employee=emp,
        dept_list=dept_list,
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


# =====================================
# 직원 삭제
# =====================================
@employee_bp.route("/delete/<int:emp_id>", methods=["POST"])
@login_required
def delete_employee(emp_id):
    if not current_user.is_superadmin:
        return jsonify({"status": "error", "message": "삭제 권한이 없습니다."})

    emp = User.query.get_or_404(emp_id)
    db.session.delete(emp)
    db.session.commit()

    return jsonify({
        "status": "success",
        "message": "직원이 삭제되었습니다."
    })
