import os
import re
import sqlite3
from collections import defaultdict


# =========================================================
# 설정
# =========================================================
# 지금은 반드시 True로 둡니다.
# 실제 DB INSERT는 하지 않고 매칭 결과만 확인합니다.
DRY_RUN = False

# =========================================================
# 과거에는 존재했지만 현재 User 테이블에서 삭제된 직원
# - 기존 AltLeaveLog 문자열 이력은 그대로 보존
# - AltLeaveRecipient 연결만 생성하지 않음
# =========================================================
LEGACY_DELETED_RECIPIENTS = {
    (7, "외래", "김혜원"),
}

# =========================================================
# DB 경로
# =========================================================
if os.path.exists("/var/data/database.db"):
    DB_PATH = "/var/data/database.db"
else:
    DB_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "instance",
        "database.db",
    )


# =========================================================
# 대체연차 부서요약 문자열 파싱
#
# 예:
# 수술실(김영선, 홍길동), 외래(송영신, 김윤정)
#
# →
# [
#   ("수술실", ["김영선", "홍길동"]),
#   ("외래", ["송영신", "김윤정"])
# ]
# =========================================================
def parse_department_summary(summary):
    summary = (summary or "").strip()

    if not summary:
        return []

    result = []

    pattern = re.compile(r"([^,()]+?)\(([^)]*)\)")

    for match in pattern.finditer(summary):
        department = match.group(1).strip()

        names = [
            name.strip()
            for name in match.group(2).split(",")
            if name.strip()
        ]

        if department and names:
            result.append((department, names))

    return result


# =========================================================
# 직원의 표준 이름
# 기존 대체연차 부여 페이지에서는 user.name을 저장했으므로
# user.name을 최우선으로 사용
# =========================================================
def get_full_name(row):
    name = (row["name"] or "").strip()

    if name:
        return name

    last_name = (row["last_name"] or "").strip()
    first_name = (row["first_name"] or "").strip()

    full_name = f"{last_name}{first_name}".strip()

    if full_name:
        return full_name

    return (row["username"] or "").strip()


def main():
    print("=" * 70)
    print("대체연차 지급대상 이전 검사")
    print("DB:", DB_PATH)
    print("DRY_RUN:", DRY_RUN)
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # -----------------------------------------------------
    # 새 테이블 존재 여부
    # -----------------------------------------------------
    table_exists = cur.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name='alt_leave_recipients'
        """
    ).fetchone()

    if not table_exists:
        print()
        print("❌ alt_leave_recipients 테이블이 없습니다.")
        print("models.py 반영 및 Render 배포 상태를 확인해주세요.")
        conn.close()
        return

    # -----------------------------------------------------
    # 직원 읽기
    # -----------------------------------------------------
    users = cur.execute(
        """
        SELECT
            id,
            username,
            name,
            last_name,
            first_name,
            department,
            employment_status
        FROM user
        ORDER BY id
        """
    ).fetchall()

    # (부서, 전체이름) → User 목록
    users_by_dept_name = defaultdict(list)

    # 전체이름 → User 목록
    users_by_name = defaultdict(list)

    for user in users:
        full_name = get_full_name(user)
        department = (user["department"] or "").strip()

        if not full_name:
            continue

        users_by_name[full_name].append(user)

        if department:
            users_by_dept_name[
                (department, full_name)
            ].append(user)

    # -----------------------------------------------------
    # 기존 지급 로그
    # -----------------------------------------------------
    logs = cur.execute(
        """
        SELECT
            id,
            grant_date,
            apply_date,
            reason,
            add_days,
            granted_by,
            department_summary
        FROM alt_leave_log
        ORDER BY id
        """
    ).fetchall()

    # 이미 이전된 것
    existing_rows = cur.execute(
        """
        SELECT log_id, user_id
        FROM alt_leave_recipients
        """
    ).fetchall()

    existing_pairs = {
        (row["log_id"], row["user_id"])
        for row in existing_rows
    }

    planned = []
    unmatched = []
    ambiguous = []
    already_exists = 0

    print()
    print(f"총 AltLeaveLog: {len(logs)}건")
    print()

    # =====================================================
    # 로그별 검사
    # =====================================================
    for log in logs:
        log_id = log["id"]

        print("-" * 70)
        print(
            f"[LOG #{log_id}] "
            f"적용일={log['apply_date']} / "
            f"사유={log['reason']} / "
            f"{log['add_days']}일"
        )

        parsed = parse_department_summary(
            log["department_summary"]
        )

        if not parsed:
            msg = (
                log_id,
                "",
                "",
                "department_summary를 해석할 수 없음",
            )
            unmatched.append(msg)

            print(
                "  ❌ department_summary를 "
                "해석할 수 없습니다."
            )
            continue

        seen_user_ids = set()

        for department, names in parsed:
            for employee_name in names:

                # -----------------------------------------
                # 1순위
                # 현재 부서 + 전체 이름 정확히 일치
                # -----------------------------------------
                matches = users_by_dept_name.get(
                    (department, employee_name),
                    [],
                )

                match_type = "EXACT"

                # -----------------------------------------
                # 2순위
                # 부서가 바뀌었을 가능성
                #
                # 현재 부서에서는 못 찾았지만,
                # 같은 전체 이름의 직원이 병원 전체에서
                # 정확히 1명이라면 후보로 인정
                # -----------------------------------------
                if len(matches) == 0:
                    global_matches = users_by_name.get(
                        employee_name,
                        [],
                    )

                    if len(global_matches) == 1:
                        matches = global_matches
                        match_type = "NAME_ONLY"

                # -----------------------------------------
                # 정확히 1명 찾음
                # -----------------------------------------
                if len(matches) == 1:
                    user = matches[0]
                    user_id = user["id"]

                    # 같은 로그 안에서 동일 직원 중복 방지
                    if user_id in seen_user_ids:
                        print(
                            f"  ⚠️ 중복표기 무시: "
                            f"{department} / {employee_name} "
                            f"→ user_id={user_id}"
                        )
                        continue

                    seen_user_ids.add(user_id)

                    if (log_id, user_id) in existing_pairs:
                        already_exists += 1

                        print(
                            f"  ↪ 이미 이전됨: "
                            f"{department} / {employee_name} "
                            f"→ user_id={user_id}"
                        )
                        continue

                    planned.append(
                        (
                            log_id,
                            user_id,
                            float(log["add_days"] or 0),
                        )
                    )

                    current_dept = (
                        user["department"] or ""
                    ).strip()

                    if match_type == "EXACT":
                        print(
                            f"  ✅ {department} / "
                            f"{employee_name} "
                            f"→ user_id={user_id}"
                        )

                    else:
                        print(
                            f"  🟡 이름 단독 일치: "
                            f"기록부서={department} / "
                            f"현재부서={current_dept} / "
                            f"{employee_name} "
                            f"→ user_id={user_id}"
                        )

                # -----------------------------------------
                # 아무도 못 찾음
                # -----------------------------------------
                elif len(matches) == 0:

                    legacy_key = (
                        log_id,
                        department,
                        employee_name,
                    )

                    # ✅ 과거 직원 삭제로 현재 User 테이블에 없는 직원
                    if legacy_key in LEGACY_DELETED_RECIPIENTS:
                        print(
                            f"  ⚪ 과거 삭제 직원 - 연결 생략: "
                            f"{department} / {employee_name}"
                        )
                        continue

                    unmatched.append(
                        (
                            log_id,
                            department,
                            employee_name,
                            "직원을 찾지 못함",
                        )
                    )

                    print(
                        f"  ❌ 직원 못 찾음: "
                        f"{department} / {employee_name}"
                    )

                # -----------------------------------------
                # 동명이인 등 여러 명
                # -----------------------------------------
                else:
                    ids = [
                        user["id"]
                        for user in matches
                    ]

                    ambiguous.append(
                        (
                            log_id,
                            department,
                            employee_name,
                            ids,
                        )
                    )

                    print(
                        f"  ❌ 동명이인/모호함: "
                        f"{department} / {employee_name} "
                        f"→ 후보 user_id={ids}"
                    )

    # =====================================================
    # 최종 결과
    # =====================================================
    print()
    print("=" * 70)
    print("검사 결과")
    print("=" * 70)

    print(f"기존 로그 수       : {len(logs)}")
    print(f"이전 예정 대상자   : {len(planned)}")
    print(f"이미 이전된 대상자 : {already_exists}")
    print(f"직원 못 찾음       : {len(unmatched)}")
    print(f"동명이인/모호함    : {len(ambiguous)}")

    # -----------------------------------------------------
    # 문제내역
    # -----------------------------------------------------
    if unmatched:
        print()
        print("[직원 못 찾음]")
        for item in unmatched:
            print(" ", item)

    if ambiguous:
        print()
        print("[동명이인/모호함]")
        for item in ambiguous:
            print(" ", item)

    # =====================================================
    # DRY RUN
    # =====================================================
    if DRY_RUN:
        print()
        print("🟦 DRY RUN이므로 DB는 변경하지 않았습니다.")

        if unmatched or ambiguous:
            print(
                "⚠️ 매칭되지 않거나 모호한 직원이 있습니다."
            )
            print(
                "실제 이전 전에 위 항목을 먼저 확인해야 합니다."
            )
        else:
            print(
                "✅ 모든 지급 대상자가 정확히 매칭되었습니다."
            )
            print(
                "다음 단계에서 실제 DB 이전을 진행할 수 있습니다."
            )

        conn.close()
        return

    # =====================================================
    # 실제 이전 모드
    # 안전장치:
    # 하나라도 못 찾거나 모호하면 INSERT 자체를 하지 않음
    # =====================================================
    if unmatched or ambiguous:
        print()
        print(
            "❌ 안전을 위해 실제 이전을 중단했습니다."
        )
        print(
            "모든 대상자가 정확히 매칭된 후 다시 실행해주세요."
        )

        conn.close()
        return

    try:
        for log_id, user_id, add_days in planned:
            cur.execute(
                """
                INSERT OR IGNORE INTO alt_leave_recipients
                (
                    log_id,
                    user_id,
                    add_days
                )
                VALUES (?, ?, ?)
                """,
                (
                    log_id,
                    user_id,
                    add_days,
                ),
            )

        conn.commit()

        print()
        print(
            f"✅ 실제 이전 완료: "
            f"{len(planned)}건"
        )

    except Exception as e:
        conn.rollback()

        print()
        print("❌ 이전 중 오류 발생")
        print(e)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
