from flask import Blueprint

myinfo_bp = Blueprint(
    "myinfo",
    __name__,
    url_prefix="/myinfo"
)

from app.myinfo import routes  # noqa
