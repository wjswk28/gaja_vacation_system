# scripts/migrate_add_user_phone.py
from sqlalchemy import text
from app import create_app, db

TABLE_NAME = "user"      # ✅ 네 프로젝트는 FK가 "user.id"라서 user가 맞음
COLUMN_NAME = "phone"

def column_exists_sqlite(table_name: str, column_name: str) -> bool:
    rows = db.session.execute(text(f'PRAGMA table_info("{table_name}");')).fetchall()
    cols = [r[1] for r in rows]  # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
    return column_name in cols

def column_exists_postgres(table_name: str, column_name: str) -> bool:
    sql = """
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = :table_name
      AND column_name = :column_name
    LIMIT 1;
    """
    row = db.session.execute(
        text(sql),
        {"table_name": table_name, "column_name": column_name}
    ).fetchone()
    return row is not None

def main():
    app = create_app()
    with app.app_context():
        engine_name = db.engine.name  # sqlite / postgresql / mysql 등

        if engine_name == "sqlite":
            exists = column_exists_sqlite(TABLE_NAME, COLUMN_NAME)
        else:
            # Render에서 Postgres로 바뀌었을 가능성 대비
            exists = column_exists_postgres(TABLE_NAME, COLUMN_NAME)

        if exists:
            print("✅ Column already exists:", COLUMN_NAME)
            return

        # SQLite도 ALTER TABLE ADD COLUMN은 가능
        # VARCHAR(20)로 충분 (하이픈 포함)
        db.session.execute(
            text(f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN "{COLUMN_NAME}" VARCHAR(20);')
        )
        db.session.commit()
        print("✅ Added column:", COLUMN_NAME)

if __name__ == "__main__":
    main()
