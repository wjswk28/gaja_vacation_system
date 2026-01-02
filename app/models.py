from datetime import datetime, date, timedelta
from flask_login import UserMixin
from datetime import datetime
from app import db, login_manager

# =====================
# DB 모델
# =====================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    # ✅ 이름 관련
    last_name = db.Column(db.String(20))          # 성
    first_name = db.Column(db.String(20))         # 이름
    name = db.Column(db.String(50))               # full name (성+이름)

    # ✅ 기타
    department = db.Column(db.String(50), default="수술실")
    join_date = db.Column(db.String(20))
    remaining_days = db.Column(db.Integer, default=15)
    used_before_system = db.Column(db.Float, default=0)
    birthday = db.Column(db.String(20))
    address = db.Column(db.String(100))           # 주소

    # ✅ NEW: 전화번호
    phone = db.Column(db.String(20), nullable=True)  # 예: 010-1234-5678

    is_admin = db.Column(db.Boolean, default=False)
    is_superadmin = db.Column(db.Boolean, default=False)
    alt_leave = db.Column(db.Float, default=0)    # 부여된 대체연차 일수
    signature_image = db.Column(db.String(255), nullable=True)   #서명 파일

        # ✅ NEW: 재직 상태 / 휴가계 대상자 / 퇴사일 (휴가계 전원 기준용)
    # - employment_status: '재직' | '휴직' | '퇴사'
    employment_status = db.Column(db.String(10), default="재직", nullable=False)
    status_changed_at = db.Column(db.Date, nullable=True)  # 상태 변경일(선택)
    resign_date = db.Column(db.Date, nullable=True)        # 퇴사일(선택)

    # ✅ NEW: 휴가계 대상자 여부(기본 True)
    is_vacation_form_target = db.Column(db.Boolean, default=True, nullable=False)

    # ✅ NEW: join_date(문자열)과 별개로 Date 타입(안전 마이그레이션)
    join_date_date = db.Column(db.Date, nullable=True)
    
    @property
    def total_alt_leave(self):
        from app.models import AltLeaveLog
        # 사용자 이름 키 (부서요약문과 동일기준)
        name_key = self.first_name or self.name or self.username

        logs = AltLeaveLog.query.all()

        # department_summary 문자열에 이름이 포함되면 해당 로그는 이 사용자에게 부여된 것
        return sum(
            log.add_days for log in logs
            if name_key and name_key in (log.department_summary or "")
        )

def now_kst():
    return datetime.utcnow() + timedelta(hours=9)

class Vacation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))          # 작성자
    target_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)  # 대상 직원
    name = db.Column(db.String(50))
    department = db.Column(db.String(50))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    type = db.Column(db.String(20))
    hours = db.Column(db.Float, nullable=True)    # 탄력근무 시간
    is_flex = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=now_kst)
    approved = db.Column(db.Boolean, default=False)  # 승인 여부
    memo = db.Column(db.String(255), nullable=True)
    start_time = db.Column(db.String(5), nullable=True)  # "08:00"
    end_time = db.Column(db.String(5), nullable=True)    # "17:00"

    user = db.relationship("User", foreign_keys=[user_id])
    target_user = db.relationship("User", foreign_keys=[target_user_id])


class NewHireChecklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(50))       # 관리자의 부서 기준
    items = db.Column(db.Text)                  # 체크 항목 JSON


class AltLeaveLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    grant_date = db.Column(db.DateTime, default=now_kst)   # 부여일
    apply_date = db.Column(db.Date, nullable=False)                # 적용일자
    reason = db.Column(db.String(255), nullable=True)              # 사유
    add_days = db.Column(db.Float, nullable=False, default=0.0)    # 부여일수
    granted_by = db.Column(db.String(50), nullable=False)          # 부여자 이름
    department_summary = db.Column(db.String(500), nullable=True)  # 부서 + 부서원 요약 문자열

class MonthLock(db.Model):
    __tablename__ = "month_locks"

    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(50), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)

    locked = db.Column(db.Boolean, default=False, nullable=False)
    locked_at = db.Column(db.DateTime, nullable=True)
    locked_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("department", "year", "month", name="uq_month_lock"),
    )

# =======================================================
# ✅ 휴가계 확정/생성 흐름용 테이블들
# - 1) 일반사용자: 월 Confirm(확인)
# - 2) 중간관리자: 부서 최종확인
# - 3) 총관리자: 휴가계 엑셀 생성/다운로드 관리
# - (추가) 부서 월 대상자 스냅샷(명단 고정)
# =======================================================

class UserMonthConfirm(db.Model):
    __tablename__ = "user_month_confirms"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)
    confirmed_at = db.Column(db.DateTime, default=now_kst, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "year", "month", name="uq_user_month_confirm"),
    )


class DeptMonthRoster(db.Model):
    __tablename__ = "dept_month_rosters"
    # ✅ 전원 기준을 '계산' 대신 '스냅샷'으로 고정하고 싶을 때 쓰는 테이블
    # - (department, year, month)의 대상자 user_id 목록을 행(row)로 저장

    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(50), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=now_kst, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("department", "year", "month", "user_id", name="uq_dept_month_roster"),
    )


class DeptMonthFinal(db.Model):
    __tablename__ = "dept_month_finals"

    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(50), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)

    finalized_at = db.Column(db.DateTime, nullable=True)
    finalized_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    note = db.Column(db.String(255), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("department", "year", "month", name="uq_dept_month_final"),
    )


class DeptMonthExport(db.Model):
    __tablename__ = "dept_month_exports"

    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(50), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)

    generated_at = db.Column(db.DateTime, nullable=True)
    generated_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    file_path = db.Column(db.String(255), nullable=True)
    file_version = db.Column(db.Integer, default=1, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("department", "year", "month", name="uq_dept_month_export"),
    )

# =====================
# 로그인 user loader
# =====================
@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None


# =====================
# 초기 데이터 세팅 (master만 생성/업데이트)
# =====================
def init_master():
    """
    앱 시작 시 호출됨.
    - username='master' 계정을 생성하거나, 기존 계정을 업데이트.
    """
    master = User.query.filter_by(username="master").first()

    if master:
        master.password = "1234"
        master.name = "총관리자"
        master.department = "관리자"
        master.is_admin = True
        master.is_superadmin = True
        print("🔁 master 계정 업데이트 완료")
    else:
        master = User(
            username="master",
            password="1234",
            name="총관리자",
            department="관리자",
            is_admin=True,
            is_superadmin=True,
        )
        db.session.add(master)
        print("✨ master 계정 생성 완료")

    db.session.commit()
    print("✅ 초기 데이터 세팅 완료 (master만 존재)")
