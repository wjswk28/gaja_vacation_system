import os
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv
load_dotenv()


db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)

    # =========================================
    # 🔹 Render 환경 여부 체크
    #    - Render에선 환경변수 RENDER_PLATFORM=true 로 설정
    # =========================================
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    IS_RENDER = os.environ.get("RENDER_PLATFORM") == "true"

    if IS_RENDER:
        # ✅ Render 서버에서는 /var/data 사용
        STORAGE_ROOT = "/var/data"
    else:
        # ✅ 로컬에서는 항상 프로젝트/instance 사용
        STORAGE_ROOT = os.path.join(BASE_DIR, "..", "instance")

    os.makedirs(STORAGE_ROOT, exist_ok=True)


    app.config["UPLOAD_FOLDER"] = os.path.join(STORAGE_ROOT, "uploads")
    app.config["FORMS_FOLDER"] = os.path.join(STORAGE_ROOT, "forms")
    app.config["EXCEL_OUTPUT"] = os.path.join(STORAGE_ROOT, "excel_output")
    app.config["HOLIDAY_API_KEY"] = os.getenv("HOLIDAY_API_KEY")


    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["FORMS_FOLDER"], exist_ok=True)
    os.makedirs(app.config["EXCEL_OUTPUT"], exist_ok=True)
    
    # 🔹 공휴일 캐시 폴더 추가 (연도별 JSON 저장용)
    app.config["HOLIDAY_CACHE_DIR"] = os.path.join(STORAGE_ROOT, "holiday_cache")
    os.makedirs(app.config["HOLIDAY_CACHE_DIR"], exist_ok=True)

    # =========================================
    # SECRET_KEY / DATABASE 설정
    # =========================================
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY",
        "gaja_yonsei_hospital_secure_key_2025"
    )

    if os.path.exists("/var/data"):
        DB_PATH = "/var/data/database.db"
    else:
        DB_PATH = os.path.join(STORAGE_ROOT, "database.db")

    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    print("✅ 현재 사용하는 DB 파일:", DB_PATH)

    # =========================================
    # DB & Login 초기화
    # =========================================
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    # =========================================
    # 모델 import (db.create_all 전에 필요)
    # =========================================
    from app.models import User, init_master  # ⬅️ init_master 추가
    from app.calendar_page.routes import calendar_api_bp

    # =========================================
    # Blueprint 등록
    # =========================================
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
    


    app.register_blueprint(auth_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(employee_bp)
    app.register_blueprint(vacation_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(birthday_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(myinfo_bp)
    app.register_blueprint(newhire_bp)
    app.register_blueprint(altleave_bp)
    app.register_blueprint(calendar_api_bp)

    # =========================================
    # ✅ 루트("/") 접속 시 로그인 페이지로 이동
    # =========================================
    @app.route("/")
    def index():
        # auth 블루프린트의 login 뷰로 리다이렉트
        return redirect(url_for("auth.login"))

    # =========================================
    # DB 생성 + master 계정 준비
    # =========================================
    with app.app_context():
        db.create_all()
        init_master()   # ⬅️ 여기서 master 생성/업데이트

    import shutil

    def ensure_persistent_dirs(app):
        base = app.config["STORAGE_ROOT"]

        # 필요한 폴더들
        folders = ["forms", "excel_output", "holiday_cache", "uploads"]
        for f in folders:
            os.makedirs(os.path.join(base, f), exist_ok=True)

        # forms 안에 기본 템플릿이 없으면 복사
        src_forms = os.path.join(os.path.dirname(__file__), "..", "forms")
        dst_forms = os.path.join(base, "forms")

        if os.path.exists(src_forms):
            for filename in os.listdir(src_forms):
                src_file = os.path.join(src_forms, filename)
                dst_file = os.path.join(dst_forms, filename)
                if not os.path.exists(dst_file):
                    shutil.copy(src_file, dst_file)
                    print(f"복사됨: {src_file} → {dst_file}")

    def create_app():
        app = Flask(__name__)
        ...
        ensure_persistent_dirs(app)
        
        return app

