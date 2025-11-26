
from datetime import date, datetime

def _completed_months(start: date, end: date) -> int:
    """입사일부터 종료일까지 경과한 개월 수 (포함식)"""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def calculate_annual_leave(join_date_str: str, basis: date = None) -> int:
    """입사일 기준 누적 연차 계산 (신규 지급 규칙 적용)"""
    if not join_date_str:
        return 0

    try:
        jd = datetime.strptime(join_date_str, "%Y-%m-%d").date()
    except Exception:
        return 0

    if basis is None:
        basis = date.today()

    if basis < jd:
        return 0

    total = 0
    first_anniv = date(jd.year + 1, jd.month, jd.day)

    # ---------------------------------------------------------
    # 1) 첫해 월차 (월 1개, 최대 11개월)
    #     ※ 2017-06-01 이후 입사자에게만 적용
    # ---------------------------------------------------------
    cutoff_date = date(2017, 6, 1)
    
    # 2017-06-01 이전 입사자는 월차 발생 없음
    if jd < cutoff_date:
        months_first = 0
    
    else:
        # 기존 첫해 월차 계산
        if basis >= first_anniv:
            months_first = 11
        else:
            months_first = min(11, _completed_months(jd, basis))
    
    total += months_first

    # ---------------------------------------------------------
    # 2) 근속연차 지급 (네가 요청한 규칙으로 재작성)
    # ---------------------------------------------------------
    if basis >= first_anniv:
        years_after = basis.year - first_anniv.year
        if (basis.month, basis.day) < (first_anniv.month, first_anniv.day):
            years_after -= 1

        for i in range(years_after + 1):
            grant_date = date(first_anniv.year + i, jd.month, jd.day)
            if grant_date > basis:
                break

            # 연차 지급 규칙 적용
            if i <= 1:
                total += 15            # 0, 1년차
            elif i <= 3:
                total += 16            # 2, 3년차
            elif i <= 5:
                total += 17            # 4, 5년차
            elif i <= 7:
                total += 18            # 6, 7년차
            elif i <= 9:
                total += 19            # 8, 9년차
            elif i <= 11:
                total += 20            # 10, 11년차
            elif i <= 20:
                total += 25            # 12~20년차
            else:
                total += 25            # 21년차 이상 → 계속 25개

    return total
