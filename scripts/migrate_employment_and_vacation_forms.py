"""
migrate_employment_and_vacation_forms.py

✅ 하는 일
1) user 테이블에 재직/휴가계 관련 컬럼 추가
   - employment_status (default '재직')
   - status_changed_at (DATE)
   - resign_date (DATE)
   - is_vacation_form_target (default 1)
   - join_date_date (DATE)  # join_date 문자열의 Date 버전

2) 휴가계 확정/생성 흐름 테이블 생성
   - user_month_confirms
   - dept_month_rosters
   - dept_month_finals
   - dept_month_exports

3) (선택) join_date -> join_date_date 백필(가능한 값만)

⚠️ 실행 전
- app/models.py 에 위 컬럼/테이블(Model) 정의가 먼저 반영되어 있어야 합니다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import inspect, text as sql_text

try:
    from app import create_app, db
    from app.models import User  # noqa: F401
except Exception as e:
    raise SystemExit(f"❌ import 실패: {e}\n- scripts 폴더 위치가 프로젝트 루트인지 확인하세요.")


def _parse_join_date(s: Optional[str]):
    """join_date 문자열을 date로 파싱 (YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD 지원)."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def add_column_if_missing(table: str, col: str, ddl: str):
    insp = inspect(db.engine)
    cols = [c["name"] for c in insp.get_columns(table)]
    if col in cols:
        print(f"✅ column exists: {table}.{col}")
        return False
    db.session.execute(sql_text(ddl))
    print(f"✅ added column: {table}.{col}")
    return True


def table_exists(table: str) -> bool:
    insp = inspect(db.engine)
    return table in insp.get_table_names()


def main():
    app = create_app()
    with app.app_context():
        print("🔎 DB engine:", db.engine)

        # 1) user 컬럼 추가
        add_column_if_missing(
            "user",
            "employment_status",
            "ALTER TABLE user ADD COLUMN employment_status VARCHAR(10) NOT NULL DEFAULT '재직'",
        )
        add_column_if_missing(
            "user",
            "status_changed_at",
            "ALTER TABLE user ADD COLUMN status_changed_at DATE",
        )
        add_column_if_missing(
            "user",
            "resign_date",
            "ALTER TABLE user ADD COLUMN resign_date DATE",
        )
        add_column_if_missing(
            "user",
            "is_vacation_form_target",
            "ALTER TABLE user ADD COLUMN is_vacation_form_target BOOLEAN NOT NULL DEFAULT 1",
        )
        add_column_if_missing(
            "user",
            "join_date_date",
            "ALTER TABLE user ADD COLUMN join_date_date DATE",
        )

        # 기본값 보정(혹시 NULL로 남아있으면 채움)
        db.session.execute(sql_text(
            "UPDATE user SET employment_status='재직' WHERE employment_status IS NULL OR employment_status=''"
        ))
        db.session.execute(sql_text(
            "UPDATE user SET is_vacation_form_target=1 WHERE is_vacation_form_target IS NULL"
        ))
        db.session.commit()
        print("✅ defaults backfilled (employment_status / is_vacation_form_target)")

        # 2) 새 테이블 생성 (Model 기준)
        db.create_all()
        print("✅ db.create_all() done")

        for t in ["user_month_confirms", "dept_month_rosters", "dept_month_finals", "dept_month_exports"]:
            print(("✅" if table_exists(t) else "❌"), "table:", t)

        # 3) join_date -> join_date_date 백필 (가능한 데이터만)
        try:
            users = db.session.execute(sql_text(
                "SELECT id, join_date, join_date_date FROM user"
            )).mappings().all()

            filled = 0
            for u in users:
                if u.get("join_date_date"):
                    continue
                jd = _parse_join_date(u.get("join_date"))
                if not jd:
                    continue
                db.session.execute(
                    sql_text("UPDATE user SET join_date_date = :d WHERE id = :id"),
                    {"d": jd.isoformat(), "id": u["id"]},
                )
                filled += 1

            db.session.commit()
            print(f"✅ join_date_date backfilled: {filled} rows")
        except Exception as e:
            db.session.rollback()
            print("⚠️ join_date_date backfill skipped due to error:", e)

        print("🎉 migration finished.")


if __name__ == "__main__":
    main()
