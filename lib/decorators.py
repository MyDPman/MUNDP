from functools import wraps

from flask import abort, g, redirect, request, url_for


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not getattr(g, "user", None):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def roles_required(*allowed_roles):
    """Allow only users whose role is in allowed_roles. Admins always pass."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = getattr(g, "user", None)
            if not user:
                return redirect(url_for("login", next=request.path))
            if user["role"] != "admin" and user["role"] not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = getattr(g, "user", None)
        if not user:
            return redirect(url_for("login", next=request.path))
        if user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapper
