from flask import Blueprint

birthday_bp = Blueprint(
    "birthday",
    __name__,
    url_prefix="/birthday"
)

from app.birthday import routes  # noqa
