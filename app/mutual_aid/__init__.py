from flask import Blueprint

mutual_aid_bp = Blueprint(
    "mutual_aid",
    __name__,
    url_prefix="/mutual-aid"
)

from . import routes  # noqa
