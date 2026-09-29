"""apps1monitor hub: one Flask site, many sub-pages (tools).

Each tool lives in tools/<name>/ as a Blueprint and registers itself in TOOLS.
The old LinkedIn Autopost app is mounted unchanged under /linkedin.
"""
import json
import os
import secrets
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)
CFG = os.path.join(DATA, "hub.json")


def load_cfg():
    try:
        with open(CFG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cfg(c):
    with open(CFG, "w") as f:
        json.dump(c, f, indent=2)


app = Flask(__name__)
_c = load_cfg()
if not _c.get("secret_key"):
    _c["secret_key"] = secrets.token_hex(32)
    save_cfg(_c)
app.secret_key = _c["secret_key"]
app.config.update(SESSION_COOKIE_NAME="hub_session", SESSION_COOKIE_SECURE=True,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

# Registry of sub-pages shown on the home page: (title, description, icon, url)
TOOLS = [
    ("مدير إعلان الكود الذهبي", "الحملات، الطلبيات، والتواصل عبر واتساب", "📣", "/goldencode/"),
    ("مدير LinkedIn", "جدولة ونشر البوستات تلقائياً", "💼", "/linkedin/"),
    ("رائج · Viraliq", "منشورات الترند اليومية مع موافقة من تيليجرام", "🔥", "/viraliq/"),
    ("جلسات دورة تطبيق الموبايل", "8 جلسات × ساعتين، چك لست لكل جلسة", "📱", "/course/"),
]


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def check_csrf():
    if request.form.get("csrf") != session.get("csrf"):
        abort(400)


def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*a, **k)
    return w


@app.context_processor
def inject():
    return {"csrf": csrf_token()}


@app.route("/login", methods=["GET", "POST"])
def login():
    c = load_cfg()
    first = not c.get("password")
    if request.method == "POST":
        check_csrf()
        pw = request.form.get("password", "")
        if first:
            if len(pw) < 8:
                flash("كلمة السر لازم 8 أحرف أو أكثر")
                return render_template("login.html", first=first)
            c["password"] = generate_password_hash(pw)
            save_cfg(c)
        elif not check_password_hash(c["password"], pw):
            flash("كلمة السر غلط")
            return render_template("login.html", first=first)
        session["admin"] = True
        nxt = request.args.get("next", "/")
        return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")
    return render_template("login.html", first=first)


@app.route("/logout", methods=["POST"])
def logout():
    check_csrf()
    session.pop("admin", None)
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    return render_template("home.html", tools=TOOLS)


@app.route("/health")
def health():
    return "ok"


from tools.goldencode import bp as goldencode_bp  # noqa: E402
app.register_blueprint(goldencode_bp, url_prefix="/goldencode")

from tools.viraliq import bp as viraliq_bp  # noqa: E402
app.register_blueprint(viraliq_bp, url_prefix="/viraliq")

from tools.course import bp as course_bp  # noqa: E402
app.register_blueprint(course_bp, url_prefix="/course")
