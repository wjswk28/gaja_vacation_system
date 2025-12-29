from flask import request, jsonify, send_file, current_app
from flask_login import login_required
from datetime import datetime
from app.schedule import schedule_bp
from app.models import User, Vacation, MonthLock
from app.schedule.utils import (
    thin_border,
    thin_side,
    uniform_mixed_border,
    find_name_index
)
import calendar
import io
import os
from app import db
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from copy import copy
from openpyxl.drawing.image import Image as XLImage

# --- 세로 굵은선 설정용 ---
THIN = Side(style="thin", color="000000")
MEDIUM = Side(style="medium", color="000000")

def apply_vertical_border(cell, left=False, right=False):
    cell.border = Border(
        left=MEDIUM if left else cell.border.left,
        right=MEDIUM if right else cell.border.right,
        top=cell.border.top,
        bottom=cell.border.bottom
    )

LEFT_MEDIUM_COLS = [1]  # A열 왼쪽 굵은선
RIGHT_MEDIUM_COLS = [2, 33, 34, 35, 36]  # B, AG, AH, AI, AJ 열 오른쪽 굵은선

# =========================================================
# 근무표 자동 생성 (블루프린트 버전)
# URL: /schedule/export/<dept>?year=2025&month=11
# =========================================================
@schedule_bp.route("/export/<dept>")
@login_required
def export_schedule(dept):

    # ====== 기본 날짜 ======
    year = request.args.get("year", type=int, default=datetime.now().year)
    month = request.args.get("month", type=int, default=datetime.now().month)
    last_day = calendar.monthrange(year, month)[1]

    # ====== 폼 파일 로드 ======
    FORM_DIR = current_app.config["FORMS_FOLDER"]
    TEMPLATE_FILE = "gaja_schedule.xlsx"
    template_path = os.path.join(FORM_DIR, TEMPLATE_FILE)

    if not os.path.exists(template_path):
        return jsonify({"error": f"기준 폼이 없습니다: {template_path}"}), 404

    wb = load_workbook(template_path)
    ws = wb[wb.sheetnames[0]]
    
    # ✅ 여기 추가: 시트 이름도 월에 맞게 변경
    ws.title = f"{month}월"

    # 제목 자동 갱신
    ws["A1"] = f"{year}년 {month}월 근무표 (부서: {dept})"

    # ====== 날짜 라벨(C7~) ======
    start_col = 3  # C열부터 날짜
    for day in range(1, last_day + 1):
        col = start_col + (day - 1)
        ws.cell(row=7, column=col).value = day
        weekday = datetime(year, month, day).weekday()
        if weekday == 6:  # 일요일
            ws.cell(row=7, column=col).fill = PatternFill(
                start_color="FFB0B0", end_color="FFB0B0", fill_type="solid"
            )

    # ====== 직원 목록 ======
    employees = (
        User.query.filter_by(department=dept)
        .order_by(User.join_date.asc())
        .all()
    )
    names = [e.name.strip() for e in employees]

    # ====== 행 복제 ======
    template_row = 8
    if len(names) > 1:
        ws.insert_rows(template_row + 1, len(names) - 1)

    # ====== 복제 + 스타일 ======
    for i, name in enumerate(names):
        target_row = template_row + i

        for col in range(1, 37):  # A~AJ 범위
            src = ws.cell(row=template_row, column=col)
            tgt = ws.cell(row=target_row, column=col)

            if src.has_style:
                try:
                    tgt.font = copy(src.font)
                    tgt.fill = copy(src.fill)
                    tgt.border = copy(src.border)
                    tgt.alignment = copy(src.alignment)
                except:
                    tgt.border = thin_border()
                    tgt.alignment = Alignment(horizontal="center", vertical="center")

            if i > 0:
                uniform_mixed_border(tgt)
                
        # --------------------------------------------------------
        # ⭐ 직원 행 복제 후 — 세로 굵은선(A,B,AG,AH,AI,AJ 열) 복구
        # --------------------------------------------------------

        # A열 왼쪽 굵은선
        apply_vertical_border(ws.cell(target_row, 1), left=True)

        # B, AG, AH, AI, AJ 오른쪽 굵은선
        for col in RIGHT_MEDIUM_COLS:
            apply_vertical_border(ws.cell(target_row, col), right=True)


        # --------------------------
        # 순번(A), 이름(B) 값 설정
        # --------------------------
        ws[f"A{target_row}"].value = i + 1
        ws[f"B{target_row}"].value = name
        ws[f"A{target_row}"].alignment = Alignment(horizontal="center", vertical="center")
        ws[f"B{target_row}"].alignment = Alignment(horizontal="center", vertical="center")

    # ====== 모든 셀 기본 값 채우기 ======
    thin = Side(style="thin", color="000000")
    fill_white = PatternFill("solid", "FFFFFF")
    fill_sunday = PatternFill("solid", "FFB0B0")

    for i, name in enumerate(names):
        row = 8 + i
        for day in range(1, last_day + 1):
            col = 3 + (day - 1)
            cell = ws.cell(row=row, column=col)

            weekday = datetime(year, month, day).weekday()
            if weekday <= 4:  # 평일
                cell.value = "·"
                cell.fill = fill_white
            elif weekday == 5:  # 토요일
                cell.value = "/"
                cell.fill = fill_white
            else:  # 일요일
                cell.value = ""
                cell.fill = fill_sunday

            cell.alignment = Alignment(horizontal="center", vertical="center")

    # ====== 승인된 일정 불러오기 ======
    events = (
        Vacation.query.filter_by(department=dept)
        .filter(Vacation.approved == True)
        .filter(Vacation.type != "탄력근무")
        .all()
    )

    # ====== 이벤트 덮어쓰기 ======
    for e in events:
        if e.start_date.year != year or e.start_date.month != month:
            continue

        idx = find_name_index(e.name.strip(), names)
        if idx is None:
            continue

        row = 8 + idx
        col = 3 + e.start_date.day - 1

        value = e.type
        if value in ["반차(전)", "반차(후)"]:
            value = "반차"

        weekday = e.start_date.weekday()

        if weekday == 5:  # 토요일
            if value == "근무자":
                value = "·"
            elif value == "토연차":
                value = "토연차"   # ← 토연차 그대로 표시
            else:
                value = "/"        # ← 나머지 토요일 일정만 "/"


        cell = ws.cell(row=row, column=col)
        cell.value = value

        # 긴 텍스트 자동 축소
        if len(str(value)) >= 3:
            cell.alignment = Alignment(
                shrinkToFit=True, horizontal="center", vertical="center"
            )
        else:
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # 테두리 보정
        medium = Side(style="medium", color="000000")
        cell.border = Border(left=thin, right=thin, top=medium, bottom=medium)

    # ====== 합계 (AI, AJ) ======
    weights = {"연차": 1.0, "반차": 0.5, "반반차": 0.25, "토연차": 0.75}
    sick_types = ["병가", "예비군"]

    for i, user in enumerate(employees):
        row = 8 + i

        # 이 직원의 이벤트만 선택 (ID 기반 → 100% 정확)
        user_events = [
            v for v in events
            if v.user_id == user.id and v.start_date.month == month
        ]

        # 연차 합계 (반차 합치기 / 토연차 0.75 반영)
        total_leave = sum(
            weights.get(
                "반차" if v.type in ["반차(전)", "반차(후)"] else v.type,
                0
            )
            for v in user_events
        )

        # 병가 / 예비군
        total_sick = sum(1 for v in user_events if v.type in sick_types)

        # AI (연차)
        ai = ws[f"AI{row}"]
        ai.value = total_leave
        ai.alignment = Alignment(horizontal="center", vertical="center", shrinkToFit=True)

        # AJ (병가/예비군)
        aj = ws[f"AJ{row}"]
        aj.value = total_sick
        aj.alignment = Alignment(horizontal="center", vertical="center")



    # ====== 인쇄 설정 ======
    last_row = 8 + len(names) - 1
    ws.print_area = f"A1:AJ{last_row}"

    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_margins.left = 0.2
    ws.page_margins.right = 0.2
    ws.page_margins.top = 0.3
    ws.page_margins.bottom = 0.3
    ws.page_setup.horizontalCentered = True
    ws.page_setup.verticalCentered = True
    ws.print_title_rows = "1:7"

    # =========================================================
    # ✅ (확정된 달이면) 중간관리자 서명 이미지를 AA3에 삽입
    # =========================================================
    dept_key = (dept or "").strip()
    lk = MonthLock.query.filter_by(department=dept_key, year=year, month=month).first()

    if lk and lk.locked and lk.locked_by:
        signer = db.session.get(User, int(lk.locked_by))
        sig_name = (getattr(signer, "signature_image", "") or "").strip() if signer else ""

        # ✅ DB에 "파일명만" 저장했다는 전제: /var/data(or instance)/signatures/<파일명>
        sig_path = (
            os.path.join(current_app.config["SIGNATURES_FOLDER"], sig_name)
            if sig_name else None
        )

        if sig_path and os.path.exists(sig_path):
            try:
                img = XLImage(sig_path)

                # ✅ (선택) 표시 크기 고정: 칸 덮어 “늘어난 것처럼” 보이는 현상 줄이기
                # 필요 없으면 주석처리 가능
                img.width = 282
                img.height = 60

                ws.add_image(img, "AA3")

            except Exception as e:
                # ✅ Pillow 미설치/이미지 손상 등으로 500 터지는 걸 방지
                current_app.logger.exception(
                    "SIGNATURE INSERT FAILED: dept=%s y=%s m=%s locked_by=%s sig=%s path=%s err=%s",
                    dept_key, year, month, lk.locked_by, sig_name, sig_path, repr(e)
                )
        else:
            current_app.logger.warning(
                "Month locked but signature file missing. dept=%s %04d-%02d locked_by=%s sig=%s path=%s",
                dept_key, year, month, lk.locked_by, sig_name, sig_path
            )

    # ====== 파일 저장 후 전송 ======
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"{dept}_근무표_{year}_{month:02d}.xlsx"
    )
