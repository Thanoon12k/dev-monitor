"""WSGI entry: the hub at /, the legacy LinkedIn app at /linkedin.

/cron is forwarded to the LinkedIn app so the existing GitHub Actions job keeps working.
The LinkedIn app is behind the hub's "linkedin" PIN: once it is unlocked in the hub, the app
treats the visitor as its admin, so its own password is no longer asked for.
"""
import os
import sys
import time
from urllib.parse import quote

from werkzeug.middleware.dispatcher import DispatcherMiddleware

HERE = os.path.dirname(os.path.abspath(__file__))
LINKEDIN = os.environ.get("LINKEDIN_APP_DIR", "/home/apps1monitor/linkedin")
sys.path.insert(0, HERE)

from app import app as hub  # noqa: E402

mounts = {}
if os.path.isdir(LINKEDIN):
    sys.path.append(LINKEDIN)
    import importlib.util
    spec = importlib.util.spec_from_file_location("linkedin_app", os.path.join(LINKEDIN, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["linkedin_app"] = mod
    cwd = os.getcwd()
    os.chdir(LINKEDIN)
    spec.loader.exec_module(mod)
    os.chdir(cwd)
    mounts["/linkedin"] = mod.app
    LINKEDIN_PUBLIC = ("/cron", "/health", "/favicon.svg", "/favicon.ico")

    def hub_pin():
        from flask import redirect, request, session
        if request.path in LINKEDIN_PUBLIC:
            return None
        hub_session = hub.session_interface.open_session(hub, request) or {}
        if hub_session.get("unlocked", {}).get("linkedin", 0) > time.time():
            session["admin"] = True
            return None
        session.pop("admin", None)
        return redirect("/pin/linkedin?next=" + quote(request.script_root + request.path))

    mod.app.before_request_funcs.setdefault(None, []).insert(0, hub_pin)

    @hub.route("/cron")
    def cron_forward():
        from flask import request
        with mod.app.test_request_context("/cron", query_string=request.query_string):
            return mod.app.full_dispatch_request()

application = DispatcherMiddleware(hub, mounts)
