# app/newhire/__init__.py
from flask import Blueprint

newhire_bp = Blueprint(
    "newhire",
    __name__,
    url_prefix="/newhire"
)

from app.newhire import routes  # noqa
