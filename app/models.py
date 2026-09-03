from datetime import datetime, date, timedelta
from flask_login import UserMixin
from datetime import datetime, date
from app import db, login_manager
from sqlalchemy.orm import validates
import os
import uuid

EMPLOYMENT_STATUSES = (
    "재직중",
    "육아휴직",
    "출산휴가",
    "장기병가",
    "무급휴가",
    "퇴사",
)

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

    # ✅ username 저장 시 무조건 소문자/공백정리 강제
    @validates("username")
    def _normalize_username(self, key, value):
        return (value or "").strip().lower()

    # ✅ NEW: 전화번호
    phone = db.Column(db.String(20), nullable=True)  # 예: 010-1234-5678

    is_admin = db.Column(db.Boolean, default=False)
    is_superadmin = db.Column(db.Boolean, default=False)
    alt_leave = db.Column(db.Float, default=0)    # 부여된 대체연차 일수
    signature_image = db.Column(db.String(255), nullable=True)   #서명 파일

    # ✅ 직원 상태
    # 허용값:
    # 재직중 | 육아휴직 | 출산휴가 | 장기병가 | 무급휴가 | 퇴사
    employment_status = db.Column(
        db.String(20),
        default="재직중",
        nullable=False,
        index=True,
    )

    # 마지막 상태 변경일
    status_changed_at = db.Column(db.Date, nullable=True)

    # 퇴사 상태일 때만 사용
    resign_date = db.Column(db.Date, nullable=True)

    # 상태 적용 기간
    # 육아휴직·출산휴가·장기병가·무급휴가 등에 공통 사용
    status_start_date = db.Column(db.Date, nullable=True)
    status_end_date = db.Column(db.Date, nullable=True)

    # ✅ NEW: 휴가계 대상자 여부(기본 True)
    is_vacation_form_target = db.Column(db.Boolean, default=True, nullable=False)

    # ✅ NEW: join_date(문자열)과 별개로 Date 타입(안전 마이그레이션)
    join_date_date = db.Column(db.Date, nullable=True)
    
    @property
    def total_alt_leave(self):
        from app.models import AltLeaveLog

        logs = AltLeaveLog.query.all()

        return sum(
            float(log.add_days or 0)
            for log in logs
            if alt_leave_log_has_user(log, self)
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
    is_alt = db.Column(db.Boolean, default=False, nullable=False)  # ✅ 대체연차 처리 여부


class NewHireChecklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(50))       # 관리자의 부서 기준
    items = db.Column(db.Text)                  # 체크 항목 JSON


def alt_leave_log_has_user(log, user):
    """
    대체연차 일괄부여 로그의 department_summary에서
    해당 직원이 실제 대상자인지 정확히 확인한다.

    - first_name 한 글자로 찾지 않음
    - 부서 일치 확인
    - 전체 이름을 직원 단위로 정확히 비교
    """
    summary = (log.department_summary or "").strip()

    department = (user.department or "기타").strip()

    full_name = (
        user.name
        or f"{(user.last_name or '').strip()}{(user.first_name or '').strip()}"
        or user.username
        or ""
    ).strip()

    if not summary or not department or not full_name:
        return False

    marker = f"{department}("
    start = summary.find(marker)

    if start == -1:
        return False

    names_start = start + len(marker)
    names_end = summary.find(")", names_start)

    if names_end == -1:
        return False

    names_text = summary[names_start:names_end]

    names = [
        name.strip()
        for name in names_text.split(",")
        if name.strip()
    ]

    return full_name in names


class AltLeaveLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    grant_date = db.Column(db.DateTime, default=now_kst)   # 부여일
    apply_date = db.Column(db.Date, nullable=False)                # 적용일자
    reason = db.Column(db.String(255), nullable=True)              # 사유
    add_days = db.Column(db.Float, nullable=False, default=0.0)    # 부여일수
    granted_by = db.Column(db.String(50), nullable=False)          # 부여자 이름
    department_summary = db.Column(db.String(500), nullable=True)  # 부서 + 부서원 요약 문자열

class AltLeaveRecipient(db.Model):
    """
    대체연차 지급 대상 직원 저장

    AltLeaveLog 1건에 여러 명의 직원이 연결될 수 있다.
    이름 문자열이 아니라 user_id로 실제 지급 대상자를 관리한다.
    """
    __tablename__ = "alt_leave_recipients"

    id = db.Column(db.Integer, primary_key=True)

    # 어떤 대체연차 지급건인지
    log_id = db.Column(
        db.Integer,
        db.ForeignKey("alt_leave_log.id"),
        nullable=False,
        index=True,
    )

    # 실제 지급받은 직원
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )

    # 해당 직원에게 실제 지급된 일수
    add_days = db.Column(
        db.Float,
        nullable=False,
        default=0.0,
    )

    # 관계
    user = db.relationship(
        "User",
        foreign_keys=[user_id],
    )

    log = db.relationship(
        "AltLeaveLog",
        foreign_keys=[log_id],
        backref=db.backref(
            "recipients",
            lazy=True,
            cascade="all, delete-orphan",
        ),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "log_id",
            "user_id",
            name="uq_alt_leave_recipient_log_user",
        ),
    )

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

class MonthSignToggle(db.Model):
    __tablename__ = "month_sign_toggle"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)

    director_on = db.Column(db.Boolean, default=False)      # 병원장
    admin_head_on = db.Column(db.Boolean, default=False)    # 행정부장
    nurse_head_on = db.Column(db.Boolean, default=False)    # 간호부장

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("year", "month", name="uq_month_sign_toggle"),)

class ApprovalRoleUser(db.Model):
    __tablename__ = "approval_role_user"

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(30), unique=True, nullable=False)  
    # "director" | "admin_head" | "nurse_head"

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User")

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class MutualAidOfficer(db.Model):
    __tablename__ = "mutual_aid_officers"

    id = db.Column(db.Integer, primary_key=True)

    # president=상조회장, treasurer=총무
    role = db.Column(db.String(20), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    user = db.relationship("User", foreign_keys=[user_id])
    
    active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    appointed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    appointed_by = db.relationship("User", foreign_keys=[appointed_by_id])

    appointed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)

class MutualAidLedger(db.Model):
    __tablename__ = "mutual_aid_ledger"

    id = db.Column(db.Integer, primary_key=True)

    # ✅ 이 날짜 기준으로 "년도 필터링" 할 거라서 year를 따로 저장
    entry_date = db.Column(db.Date, nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)

    # income=수입 / expense=지출
    entry_type = db.Column(db.String(10), nullable=False, index=True)

    # 표시용(예: 회비, 경조금, 물품구입 등)
    title = db.Column(db.String(120), nullable=False)

    # ✅ 금액: 원 단위 정수(권장)
    amount = db.Column(db.Integer, nullable=False)

    memo = db.Column(db.Text, nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @property
    def signed_amount(self) -> int:
        """계산용: 수입은 +, 지출은 - 로 반환"""
        return self.amount if self.entry_type == "income" else -self.amount

    def set_year(self):
        """entry_date 기반으로 year 자동 세팅(라우트에서 호출)"""
        if self.entry_date:
            self.year = int(self.entry_date.year)

class MutualAidYearFinal(db.Model):
    __tablename__ = "mutual_aid_year_finals"

    year = db.Column(db.Integer, primary_key=True)  # 2024, 2025...
    finalized = db.Column(db.Boolean, default=True, nullable=False)
    closing_balance = db.Column(db.Integer, default=0, nullable=False)  # 그 해 결산 잔액
    finalized_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    finalized_at = db.Column(db.DateTime)

    finalized_by = db.relationship("User", foreign_keys=[finalized_by_id])

class MutualAidAttachment(db.Model):
    __tablename__ = "mutual_aid_attachments"

    id = db.Column(db.Integer, primary_key=True)

    ledger_id = db.Column(db.Integer, db.ForeignKey("mutual_aid_ledger.id"), nullable=False, index=True)
    ledger = db.relationship("MutualAidLedger", backref=db.backref("attachments", lazy=True, cascade="all, delete-orphan"))

    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)   # uuid 기반 파일명
    mime_type = db.Column(db.String(100), nullable=True)
    size = db.Column(db.Integer, nullable=True)

    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_id])

    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)      

class PracticeStudent(db.Model):
    __tablename__ = "practice_students"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<PracticeStudent {self.name}>"
    
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


