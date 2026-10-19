"""apps1monitor hub: one Flask site, many sub-pages (tools).

Each tool lives in tools/<name>/ as a Blueprint and registers itself in TOOLS.
The old LinkedIn Autopost app is mounted unchanged under /linkedin.
The home page is open; each tool is locked with its own 4-digit PIN (hashes in data/hub.json,
"pins"). Five wrong PINs lock that tool for 15 minutes, doubling each time up to a day.
"""
import json
import os
import secrets
import time
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
    ("أول 10 دولار", "عشر طرق أونلاين للربح، ومعطيات تنطيها لـ Claude ويتحقق منها", "💵", "/money/"),
    ("مدير المنصات", "منشور واحد ينتشر بلينكدإن، فيسبوك، إنستغرام، تيك توك، تيليجرام والمدونة", "🛰️", "/social/"),
]
PIN_TOOLS = {u.strip("/"): (t, i) for t, d, i, u in TOOLS if u != "/linkedin/"}  # blueprint name -> (title, icon)
UNLOCK_HOURS = 12


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def check_csrf():
    if request.form.get("csrf") != session.get("csrf"):
        abort(400)


def unlocked(tool):
    return session.get("unlocked", {}).get(tool, 0) > time.time()


def login_required(f):
    """Each tool's pages need that tool's PIN (the tool is the request's blueprint)."""
    @wraps(f)
    def w(*a, **k):
        tool = request.blueprint
        if tool not in PIN_TOOLS:
            abort(403)
        if not unlocked(tool):
            return redirect(url_for("pin", tool=tool, next=request.path))
        return f(*a, **k)
    return w


@app.context_processor
def inject():
    tool = request.blueprint if request.blueprint in PIN_TOOLS and unlocked(request.blueprint) else None
    return {"csrf": csrf_token(), "any_unlocked": any(unlocked(t) for t in PIN_TOOLS), "cur_tool": tool}


def lock_wait(c, tool):
    """Seconds this tool stays locked after wrong PINs (0 = open)."""
    return max(0, int(c.get("pin_fail", {}).get(tool, {}).get("until", 0) - time.time()))


def valid_pin(p):
    return len(p) == 4 and p.isdigit()


@app.route("/pin/<tool>", methods=["GET", "POST"])
def pin(tool):
    """Enter a tool's PIN; set it when the tool has none yet; change it while unlocked (?change=1)."""
    if tool not in PIN_TOOLS:
        abort(404)
    c = load_cfg()
    pins = c.setdefault("pins", {})
    mode = "set" if not pins.get(tool) else ("change" if request.args.get("change") and unlocked(tool) else "enter")
    nxt = request.args.get("next", "")
    nxt = nxt if nxt.startswith("/" + tool + "/") and not nxt.startswith("//") else "/" + tool + "/"
    title, icon = PIN_TOOLS[tool]
    if request.method == "POST":
        check_csrf()
        f = request.form
        pin_, wait = f.get("pin", "").strip(), lock_wait(c, tool)
        if mode == "enter":
            if wait:
                flash(f"مقفول بسبب محاولات غلط، جرّب بعد {wait // 60 + 1} دقيقة")
            elif check_password_hash(pins[tool], pin_):
                c.get("pin_fail", {}).pop(tool, None)
                save_cfg(c)
                session["unlocked"] = {**{t: u for t, u in session.get("unlocked", {}).items() if u > time.time()},
                                       tool: time.time() + UNLOCK_HOURS * 3600}
                return redirect(nxt)
            else:
                time.sleep(1)
                fail = c.setdefault("pin_fail", {}).setdefault(tool, {"n": 0})
                fail["n"] += 1
                if fail["n"] % 5 == 0:
                    fail["until"] = time.time() + min(900 * 2 ** (fail["n"] // 5 - 1), 86400)
                save_cfg(c)
                flash("الرمز غلط")
        else:  # set or change
            if not valid_pin(pin_) or pin_ != f.get("pin2", "").strip():
                flash("الرمز لازم 4 أرقام، ونفسه بالخانتين")
            elif mode == "set" and c.get("password") and not check_password_hash(c["password"], f.get("password", "")):
                time.sleep(1)
                flash("كلمة سر الموقع القديمة غلط")
            else:
                pins[tool] = generate_password_hash(pin_)
                save_cfg(c)
                session["unlocked"] = {**session.get("unlocked", {}), tool: time.time() + UNLOCK_HOURS * 3600}
                flash("✅ انحفظ الرمز")
                return redirect(nxt)
    return render_template("pin.html", tool=tool, title=title, icon=icon, mode=mode, nxt=nxt,
                           need_password=mode == "set" and bool(c.get("password")), wait=lock_wait(c, tool))


@app.route("/lock", methods=["POST"])
def lock():
    """Lock one tool (form field "tool") or all of them."""
    check_csrf()
    tool = request.form.get("tool")
    session["unlocked"] = {t: u for t, u in session.get("unlocked", {}).items() if tool and t != tool}
    return redirect("/")


@app.route("/login")
def login():  # old bookmarks
    return redirect("/")


@app.route("/")
def home():
    return render_template("home.html", tools=TOOLS, open_tools={t for t in PIN_TOOLS if unlocked(t)})


@app.route("/health")
def health():
    return "ok"


from tools.goldencode import bp as goldencode_bp  # noqa: E402
app.register_blueprint(goldencode_bp, url_prefix="/goldencode")

from tools.viraliq import bp as viraliq_bp  # noqa: E402
app.register_blueprint(viraliq_bp, url_prefix="/viraliq")

from tools.course import bp as course_bp  # noqa: E402
app.register_blueprint(course_bp, url_prefix="/course")

from tools.money import bp as money_bp  # noqa: E402
app.register_blueprint(money_bp, url_prefix="/money")

from tools.social import bp as social_bp  # noqa: E402
app.register_blueprint(social_bp, url_prefix="/social")
