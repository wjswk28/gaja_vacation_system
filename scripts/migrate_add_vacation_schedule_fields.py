# scripts/migrate_add_vacation_schedule_fields.py
from sqlalchemy import text
from app import create_app, db
from sqlalchemy.exc import OperationalError

def column_exists(table: str, col: str) -> bool:
    dialect = db.engine.dialect.name

    if dialect == "sqlite":
        rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        return any(r[1] == col for r in rows)

    # postgres/mysql 등 공통: information_schema 사용
    q = text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = :table AND column_name = :col
        LIMIT 1
    """)
    return db.session.execute(q, {"table": table, "col": col}).first() is not None

def add_column(table: str, col: str, ddl_type: str):
    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl_type}"))
    db.session.commit()
    print(f"✅ added {col}")

def main():
    app = create_app()
    with app.app_context():
        table = "vacation"  # models.py에 __tablename__ 없어서 기본이 vacation

        # memo: VARCHAR(255)
        if not column_exists(table, "memo"):
            add_column(table, "memo", "VARCHAR(255)")
        else:
            print("✅ Column already exists: memo")

        # start_time: VARCHAR(5)
        if not column_exists(table, "start_time"):
            add_column(table, "start_time", "VARCHAR(5)")
        else:
            print("✅ Column already exists: start_time")

        # end_time: VARCHAR(5)
        if not column_exists(table, "end_time"):
            add_column(table, "end_time", "VARCHAR(5)")
        else:
            print("✅ Column already exists: end_time")

        print("✅ migration done")

if __name__ == "__main__":
    main()
