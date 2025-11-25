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
    """입사일 기준 누적 연차 계산"""
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

    # 첫해 월차 (최대 11개월)
    if basis >= first_anniv:
        months_first = 11
    else:
        months_first = min(11, _completed_months(jd, basis))
    total += months_first

    # 1주년 이후 연차
    if basis >= first_anniv:
        years_after = (basis.year - first_anniv.year)
        if (basis.month, basis.day) < (first_anniv.month, first_anniv.day):
            years_after -= 1

        for i in range(years_after + 1):
            grant_date = date(first_anniv.year + i, jd.month, jd.day)
            if grant_date > basis:
                break
            if i <= 1:
                total += 15
            elif i <= 3:
                total += 16
            else:
                total += 17

    return total
