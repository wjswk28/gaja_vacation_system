from flask import Blueprint

vacation_bp = Blueprint(
    "vacation",
    __name__,
    url_prefix="/vacation"
)

from app.vacation import routes  # noqa
