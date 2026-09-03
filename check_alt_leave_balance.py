import os
import sqlite3


if os.path.exists("/var/data/database.db"):
    DB_PATH = "/var/data/database.db"
else:
    DB_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "instance",
        "database.db",
    )


DEDUCTION_MAP = {
    "연차": 1.0,
    "반차": 0.5,
    "반차(전)": 0.5,
    "반차(후)": 0.5,
    "반반차": 0.25,
    "토연차": 0.75,
}


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    users = cur.execute("""
        SELECT
            id,
            name,
            username,
            department,
            alt_leave
        FROM user
        WHERE username != 'master'
        ORDER BY department, name
    """).fetchall()

    mismatch_count = 0

    print("=" * 90)
    print("대체연차 현재잔액 검증")
    print("=" * 90)

    for user in users:
        user_id = user["id"]

        # 1) 새 지급대상 테이블 기준 총 부여량
        granted = cur.execute("""
            SELECT COALESCE(SUM(add_days), 0)
            FROM alt_leave_recipients
            WHERE user_id = ?
        """, (user_id,)).fetchone()[0]

        granted = float(granted or 0)

        # 2) 실제 대체연차로 처리된 Vacation
        alt_vacations = cur.execute("""
            SELECT
                type,
                approved,
                start_date,
                id
            FROM vacation
            WHERE
                (target_user_id = ? OR
                    (target_user_id IS NULL AND user_id = ?))
                AND is_alt = 1
        """, (user_id, user_id)).fetchall()

        used = 0.0

        for vac in alt_vacations:
            vac_type = (vac["type"] or "").strip()
            used += DEDUCTION_MAP.get(vac_type, 0.0)

        used = round(used, 2)

        # 3) 이력 기반 예상 잔액
        expected = round(granted - used, 2)

        # 4) 현재 User.alt_leave
        actual = round(float(user["alt_leave"] or 0), 2)

        name = (
            (user["name"] or "").strip()
            or (user["username"] or "").strip()
        )

        department = (user["department"] or "").strip()

        if expected != actual:
            mismatch_count += 1

            print()
            print(
                f"❌ 불일치 | "
                f"{department} / {name} / user_id={user_id}"
            )
            print(f"   총 부여     : {granted:.2f}")
            print(f"   대체연차 사용: {used:.2f}")
            print(f"   예상 잔액   : {expected:.2f}")
            print(f"   DB 실제잔액 : {actual:.2f}")

    print()
    print("=" * 90)

    if mismatch_count == 0:
        print("✅ 모든 직원의 대체연차 잔액이 정확히 일치합니다.")
    else:
        print(f"⚠️ 잔액이 다른 직원: {mismatch_count}명")
        print("아직 DB 값은 수정하지 않았습니다.")

    print("=" * 90)

    conn.close()


if __name__ == "__main__":
    main()