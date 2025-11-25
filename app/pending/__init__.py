# app/pending/__init__.py
from flask import Blueprint

pending_bp = Blueprint(
    "pending",        # 👉 엔드포인트 prefix: pending.***
    __name__,
    url_prefix="/pending"
)

from app.pending import routes  # 아래 routes.py를 가져옴
