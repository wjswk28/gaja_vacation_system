from flask import Blueprint

vacation_form_bp = Blueprint(
    "vacation_form",
    __name__,
    url_prefix="/vacation_form"
)
from . import routes  # noqa
