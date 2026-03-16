from functools import wraps
from flask import session, redirect, url_for


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_bp.admin_login"))
        return f(*args, **kwargs)
    return wrapper
