from flask import Blueprint

schedule_bp = Blueprint(
    "schedule",
    __name__,
    url_prefix="/schedule"
)

from app.schedule import routes  # noqa
