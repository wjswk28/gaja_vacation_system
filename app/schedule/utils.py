from openpyxl.styles import Border, Side, Alignment, PatternFill, Font
from copy import copy


# ================================================================
#  공통 스타일 요소
# ================================================================
THIN = Side(style="thin", color="000000")
MEDIUM = Side(style="medium", color="000000")
SUNDAY_FILL = PatternFill("solid", "FFB0B0")


# ================================================================
# 1) 기본 thin 테두리
# ================================================================
def thin_border():
    return Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# ================================================================
# 2) 한쪽만 thin
# ================================================================
def thin_side():
    return Side(style="thin", color="000000")


# ================================================================
# 3) 직원 행 테두리: 상하 medium / 좌우 thin
# ================================================================
def uniform_mixed_border(cell):
    cell.border = Border(left=THIN, right=THIN, top=MEDIUM, bottom=MEDIUM)


# ================================================================
# 4) 행 복제용 - 모든 스타일 안전 복사
# ================================================================
def copy_cell_style(src, tgt):
    """src 셀의 모든 스타일(font, fill, border, alignment)을 tgt에 복사"""

    if src.has_style:
        tgt.font = copy(src.font)
        tgt.fill = copy(src.fill)
        tgt.border = copy(src.border)
        tgt.alignment = copy(src.alignment)
    else:
        tgt.border = thin_border()
        tgt.alignment = Alignment(horizontal="center", vertical="center")


# ================================================================
# 5) 특정 열(A, B, AI, AJ)을 굵은 테두리로 설정
# ================================================================
def set_strong_border(cell):
    """A/B열, AI/AJ열 등에 굵은 테두리 적용"""
    cell.border = Border(left=MEDIUM, right=MEDIUM, top=MEDIUM, bottom=MEDIUM)


# ================================================================
# 6) 특별한 날짜용 셀 스타일 (일요일)
# ================================================================
def set_sunday_style(cell):
    cell.fill = SUNDAY_FILL
    cell.alignment = Alignment(horizontal="center", vertical="center")


# ================================================================
# 7) 행 높이 설정
# ================================================================
def set_row_height(ws, row, height=30):
    ws.row_dimensions[row].height = height


# ================================================================
# 8) 직원 이름 인덱스 찾기(업그레이드)
# ================================================================
def find_name_index(name, name_list):
    """
    부분 일치 + 앞글자 유사도 기반으로 직원 index 찾기
    이름이 '홍길동'인데 리스트에 '길동'만 있어도 매칭
    이름이 '홍길동'인데 리스트에 '홍'만 있어도 매칭
    """

    # 1) 완전 일치 우선
    for i, n in enumerate(name_list):
        if name == n:
            return i

    # 2) 부분 포함 매칭
    for i, n in enumerate(name_list):
        if name in n or n in name:
            return i

    # 3) 첫 글자 같으면 가중치 매칭
    for i, n in enumerate(name_list):
        if n[0] == name[0]:
            return i

    return None


# ================================================================
# 9) 특정 날짜의 medium 라인 생성 (일요일 / 5일 간격)
# ================================================================
def apply_special_day_border(cell, day):
    """
    day 값에 따라 상하 굵은 medium border 적용
    예:
      - 일요일: medium 라인
      - 5일 간격: medium 라인
    """
    is_sunday = (day % 7 == 0)
    is_five_gap = (day % 5 == 0)

    if is_sunday or is_five_gap:
        cell.border = Border(left=THIN, right=THIN, top=MEDIUM, bottom=MEDIUM)
    else:
        cell.border = thin_border()
