from flask import request, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from app.models import Vacation
from app.models import User
from . import events_bp


@events_bp.route("", methods=["GET"])
@login_required
def get_events():
    """FullCalendar에서 일정 가져가는 API (Blueprint 버전)"""

    my_only = request.args.get("my") == "1"
    selected_dept = (
        request.args.get("dept")
        or current_user.department
        or "수술실"
    )

    query = Vacation.query.join(
        User, Vacation.user_id == User.id
    )

    # 총관리자는 부서 선택 가능
    if current_user.is_superadmin:
        query = query.filter(User.department == selected_dept)
    else:
        query = query.filter(User.department == current_user.department)

    # 내 일정만 보기
    if my_only:
        my_names = {
            current_user.first_name,
            current_user.name,
            current_user.username
        }

        query = query.filter(
            (
                # 1) 일반 휴가 → 내가 신청한 일정
                (Vacation.type != "근무자") &
                (
                    (Vacation.user_id == current_user.id) |
                    (Vacation.target_user_id == current_user.id) |
                    (Vacation.name.in_(my_names))
                )
            )
            |
            (
                # 2) 근무자 일정 → name 이 나일 때만!
                (Vacation.type == "근무자") &
                (Vacation.name.in_(my_names))
            )
        )



    events = query.all()

    # 일정 색상
    color_map = {
        "연차": "#ef4444",
        "반차": "#f97316",
        "반차(전)": "#f97316",
        "반차(후)": "#fb923c",
        "반반차": "#eab308",
        "병가": "#10b981",
        "예비군": "#6366f1",
        "탄력근무": "#6b7280",
        "근무자": "#38bdf8",
        "토연차": "#8b5cf6",
    }

    event_list = []
    for e in events:
        name = e.name or "?"
        etype = e.type or "기타"
        approved = getattr(e, "approved", False)

        color = color_map.get(etype, "#22c55e") if approved else "#9ca3af"

        start = e.start_date.isoformat()
        end = e.end_date.isoformat()

        short_name = name[-2:] if len(name) > 2 else name

        # 🔵 타입 정리 (공백 제거)
        etype_clean = (etype or "").strip()

        # ===============================
        #  🔵 탄력근무일 경우 시간 표시
        # ===============================
        if etype_clean == "탄력근무":
            # + 부호 붙이기
            hour_sign = "+" if (e.hours is not None and e.hours > 0) else ""
            hour_display = f"{hour_sign}{e.hours}h"  # 예: +1.5h, -0.5h

            # 👉 최종 제목: 혜진 (탄력 +1.5h)
            title = f"{short_name} ({hour_display})"
        else:
            # 그 외 일반 휴가
            title = f"{short_name} ({etype_clean})"

        # 🔴 대기중 표시
        if not approved:
            title += " [신청]"


        # 승인되지 않은 일정은 관리자/본인만 표시
        is_my_event = (
            e.user_id == current_user.id or
            e.target_user_id == current_user.id
        )
        if not approved:
            if not (current_user.is_admin or current_user.is_superadmin or is_my_event):
                continue

        event_list.append({
            "id": e.id,
            "title": title,
            "start": start,
            "end": end,
            "color": color,
            "type": etype,
            "approved": approved,
        })

    return jsonify(event_list)
