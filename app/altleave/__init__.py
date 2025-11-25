# app/altleave/__init__.py
from flask import Blueprint

altleave_bp = Blueprint(
    "altleave",
    __name__,
    url_prefix="/altleave"
)

from app.altleave import routes  # noqa
