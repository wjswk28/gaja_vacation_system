import os
import shutil
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv
load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)

    # =============================
    # 🔹 BASE & 저장소(STORAGE_ROOT) 설정
    # - Render 재시작에도 남기려면 /var/data 사용
    # - 환경변수 STORAGE_ROOT가 있으면 그걸 최우선
    # =============================
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))

    # ✅ Render 디스크가 실제로 있으면 무조건 /var/data 사용 (환경변수 의존 X)
    if os.path.exists("/var/data"):
        STORAGE_ROOT = "/var/data"
    else:
        STORAGE_ROOT = os.path.join(BASE_DIR, "..", "instance")

    os.makedirs(STORAGE_ROOT, exist_ok=True)
    app.config["STORAGE_ROOT"] = STORAGE_ROOT
    print("✅ STORAGE_ROOT:", STORAGE_ROOT)


    # =============================
    # 폴더 설정
    # =============================
    app.config["UPLOAD_FOLDER"] = os.path.join(STORAGE_ROOT, "uploads")
    app.config["FORMS_FOLDER"] = os.path.join(STORAGE_ROOT, "forms")
    app.config["EXCEL_OUTPUT"] = os.path.join(STORAGE_ROOT, "excel_output")
    app.config["HOLIDAY_CACHE_DIR"] = os.path.join(STORAGE_ROOT, "holiday_cache")

    # ✅ 서명 폴더 추가 (Render 재시작해도 유지)
    app.config["SIGNATURES_FOLDER"] = os.path.join(STORAGE_ROOT, "signatures")

    for key in ["UPLOAD_FOLDER", "FORMS_FOLDER", "EXCEL_OUTPUT", "HOLIDAY_CACHE_DIR", "SIGNATURES_FOLDER"]:
        os.makedirs(app.config[key], exist_ok=True)

    # =============================
    # SECRET_KEY / DATABASE
    # =============================
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY",
        "gaja_yonsei_hospital_secure_key_2025"
    )
    
    app.config["HOLIDAY_API_KEY"] = os.environ.get("HOLIDAY_API_KEY", "")

    if os.path.exists("/var/data"):
        DB_PATH = "/var/data/database.db"
    else:
        DB_PATH = os.path.join(STORAGE_ROOT, "database.db")

    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    print("✅ 현재 사용하는 DB 파일:", DB_PATH)

    # =============================
    # DB & Login 초기화
    # =============================
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    # =============================
    # 모델 import
    # =============================
    from app.models import User, init_master
    from app.calendar_page.routes import calendar_api_bp

    # =============================
    # Blueprint 등록
    # =============================
    from app.auth.routes import auth_bp
    from app.calendar_page.routes import calendar_bp
    from app.employee.routes import employee_bp
    from app.vacation.routes import vacation_bp
    from app.schedule.routes import schedule_bp
    from app.birthday.routes import birthday_bp
    from app.events.routes import events_bp
    from app.myinfo.routes import myinfo_bp
    from app.newhire.routes import newhire_bp
    from app.altleave.routes import altleave_bp
    from app.vacation_form import vacation_form_bp

    bp_list = [
        auth_bp, calendar_bp, employee_bp, vacation_bp,
        schedule_bp, birthday_bp, events_bp, myinfo_bp,
        newhire_bp, altleave_bp, calendar_api_bp, vacation_form_bp
    ]
    for bp in bp_list:
        app.register_blueprint(bp)

    # =============================
    # Root → 로그인페이지 리다이렉트
    # =============================
    @app.route("/")
    def index():
        return redirect(url_for("auth.login"))

    # =============================
    # DB 생성 + master 계정
    # =============================
    with app.app_context():
        db.create_all()
        init_master()

    # =============================
    # 폴더 자동 복사 기능
    # =============================
    def ensure_persistent_dirs():
        base = app.config["STORAGE_ROOT"]

        src_forms = os.path.join(BASE_DIR, "..", "forms")
        dst_forms = os.path.join(base, "forms")

        if os.path.exists(src_forms):
            for filename in os.listdir(src_forms):
                src_file = os.path.join(src_forms, filename)
                dst_file = os.path.join(dst_forms, filename)
                if not os.path.exists(dst_file):
                    shutil.copy(src_file, dst_file)
                    print(f"📄 복사됨: {src_file} → {dst_file}")

    ensure_persistent_dirs()

    return app
