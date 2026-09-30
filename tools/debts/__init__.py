"""Shop tab (دفتر الدين): purchases on credit per shop, payments, and an archive.

Each shop has an open account: purchases add to the debt, payments subtract. When a
payment brings a shop's balance to zero (or below), its open entries move to the archive
as one closed account; any overpayment carries into the new account as credit.

Each 6-digit PIN opens its own book (shops, entries, archive), so several people can
keep separate books. The page needs no hub login.
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

bp = Blueprint("debts", __name__, template_folder="../../templates")

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "debts.json")
IRAQ = timezone(timedelta(hours=3))
DEFAULT_SHOPS = ["دكان أحمد أنس", "دكان ابن هذال", "دكان عمار (مخضر)", "مول حبش"]
UNLOCK_SECONDS = 3600      # the PIN is asked again after an hour
MAX_TRIES, LOCK_SECONDS = 5, 15 * 60  # per IP
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def load_db():
    try:
        with open(STATE) as f:
            db = json.load(f)
    except (OSError, ValueError):
        db = {}
    if "books" not in db:  # single-book file from before PINs picked the book
        legacy = db
        db = {"books": {}, "tries": {}}
        if legacy.get("pin"):
            db["legacy"] = legacy  # moved to its PIN's book on the first unlock
        elif legacy.get("entries") or legacy.get("archive"):
            db["unclaimed"] = legacy  # given to the first book created
    db.setdefault("tries", {})
    return db


def save_db(db):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def new_book(name, base=None):
    b = {k: v for k, v in (base or {}).items() if k in ("shops", "entries", "archive")}
    b["name"] = name
    if "shops" not in b:
        b["shops"] = [{"id": _id(), "name": n} for n in DEFAULT_SHOPS]
    b.setdefault("entries", [])
    b.setdefault("archive", [])
    return b


def pin_key(pin):
    """Book id for a PIN: keyed with the site secret, so the data file alone can't reveal PINs."""
    return hmac.new(current_app.secret_key.encode(), pin.encode(), hashlib.sha256).hexdigest()


def book():
    db = load_db()
    return db, db["books"][session["debts_book"]]


def _id():
    return secrets.token_hex(4)


def today():
    return datetime.now(IRAQ).strftime("%Y-%m-%d")


def parse_amount(raw):
    t = (raw or "").translate(DIGITS).replace(",", "").replace("٬", "").replace(" ", "")
    return int(t) if t.isdigit() and 0 < int(t) < 10**10 else None


def parse_date(raw):
    try:
        return datetime.strptime((raw or "").translate(DIGITS), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return today()


def balance(entries):
    return sum(e["amount"] if e["kind"] == "buy" else -e["amount"] for e in entries)


def open_entries(s, shop_id):
    return [e for e in s["entries"] if e["shop"] == shop_id]


def settle_if_zero(s, shop):
    """Archive the shop's open account once it is paid off; keep any overpayment as credit."""
    items = open_entries(s, shop["id"])
    bal = balance(items)
    if not items or bal > 0 or not any(e["kind"] == "buy" for e in items):
        return False
    items.sort(key=lambda e: (e["date"], e["created"]))
    s["archive"].insert(0, {
        "id": _id(), "shop": shop["id"], "shop_name": shop["name"],
        "from": items[0]["date"], "to": items[-1]["date"], "closed": today(),
        "bought": sum(e["amount"] for e in items if e["kind"] == "buy"),
        "paid": sum(e["amount"] for e in items if e["kind"] == "pay"),
        "entries": items,
    })
    s["entries"] = [e for e in s["entries"] if e["shop"] != shop["id"]]
    if bal < 0:
        s["entries"].append({"id": _id(), "shop": shop["id"], "kind": "pay", "amount": -bal,
                             "date": today(), "note": "رصيد زايد من الحساب السابق", "created": _now()})
    return True


def _now():
    return datetime.now(IRAQ).strftime("%Y-%m-%d %H:%M:%S")


def _admin():
    from app import check_csrf
    return check_csrf


check_csrf = _admin()


def pin_required(f):
    """Every page works on the book of the PIN typed at /lock; no hub login involved."""
    @wraps(f)
    def w(*a, **k):
        key = session.get("debts_book")
        if not key or session.get("debts_until", 0) < time.time() or key not in load_db()["books"]:
            session.pop("debts_book", None)
            return redirect(url_for("debts.lock"))
        session["debts_until"] = time.time() + UNLOCK_SECONDS
        return f(*a, **k)
    return w


def valid_pin(p):
    return len(p) == 6 and p.isdigit()


def form_pin(field):
    return request.form.get(field, "").translate(DIGITS).strip()


def client_ip():
    return request.headers.get("X-Real-IP", request.remote_addr or "?")


def locked_for(db):
    t = db["tries"].get(client_ip(), {})
    return max(int(t.get("until", 0) - time.time()), 0)


def failed(db):
    """Count a wrong PIN (or a taken one at sign-up) against this IP; returns tries left."""
    now = time.time()
    db["tries"] = {ip: t for ip, t in db["tries"].items() if t.get("until", 0) > now or t.get("last", 0) > now - LOCK_SECONDS}
    t = db["tries"].setdefault(client_ip(), {"n": 0})
    t["n"], t["last"] = t["n"] + 1, now
    if t["n"] >= MAX_TRIES:
        t["n"], t["until"] = 0, now + LOCK_SECONDS
        return 0
    return MAX_TRIES - t["n"]


def open_book(key):
    session["debts_book"] = key
    session["debts_until"] = time.time() + UNLOCK_SECONDS
    return redirect(url_for("debts.dashboard"))


@bp.route("/lock", methods=["GET", "POST"])
def lock():
    db = load_db()
    signup = request.args.get("new") == "1"
    wait = locked_for(db)
    if request.method == "POST" and not wait:
        check_csrf()
        pin = form_pin("pin")
        key = pin_key(pin) if valid_pin(pin) else None
        legacy = db.get("legacy")
        taken = key in db["books"] or (legacy and valid_pin(pin) and check_password_hash(legacy["pin"], pin))
        if signup:
            name = request.form.get("name", "").strip()[:40]
            if not name or not valid_pin(pin) or pin != form_pin("pin2"):
                flash("اكتب اسمك، والرمز 6 أرقام ونفسه بالخانتين")
            elif taken:
                left = failed(db)
                save_db(db)
                flash("هذا الرمز مستخدم، اختار رمز غيره" if left else "محاولات كثيرة")
                wait = locked_for(db)
            else:
                db["books"][key] = new_book(name, db.pop("unclaimed", None))
                save_db(db)
                return open_book(key)
        elif key in db["books"]:
            db["tries"].pop(client_ip(), None)
            save_db(db)
            return open_book(key)
        elif taken:  # the old single book: it becomes this PIN's book
            db["books"][key] = new_book("دفتري", db.pop("legacy"))
            db["tries"].pop(client_ip(), None)
            save_db(db)
            return open_book(key)
        else:
            left = failed(db)
            save_db(db)
            if left:
                flash(f"الرمز غلط (باقي {left} محاولات)")
            wait = locked_for(db)
    return render_template("debts/lock.html", signup=signup, wait=wait)


@bp.route("/logout", methods=["POST"])
def logout():
    check_csrf()
    session.pop("debts_book", None)
    session.pop("debts_until", None)
    return redirect(url_for("debts.lock"))


@bp.route("/pin", methods=["POST"])
@pin_required
def change_pin():
    check_csrf()
    db, s = book()
    old, new = form_pin("old"), form_pin("new")
    if not valid_pin(old) or pin_key(old) != session["debts_book"]:
        flash("الرمز الحالي غلط")
    elif not valid_pin(new):
        flash("الرمز الجديد لازم 6 أرقام")
    elif pin_key(new) in db["books"]:
        flash("هذا الرمز مستخدم، اختار رمز غيره")
    else:
        db["books"][pin_key(new)] = db["books"].pop(session["debts_book"])
        save_db(db)
        session["debts_book"] = pin_key(new)
        flash("✔ تغيّر الرمز")
    return redirect(url_for("debts.dashboard"))


@bp.app_template_filter("iqd")
def iqd(n):
    return f"{n:,}"


@bp.route("/")
@pin_required
def dashboard():
    db, s = book()
    shops = []
    for sh in s["shops"]:
        items = sorted(open_entries(s, sh["id"]), key=lambda e: (e["date"], e["created"]), reverse=True)
        shops.append({**sh, "balance": balance(items), "entries": items,
                      "since": items[-1]["date"] if items else None})
    shops.sort(key=lambda x: -x["balance"])
    total = sum(max(x["balance"], 0) for x in shops)
    return render_template("debts/dashboard.html", name=s.get("name", ""), shops=shops, total=total, archive=s["archive"],
                           today=today(), pick=request.args.get("shop", ""))


@bp.route("/add", methods=["POST"])
@pin_required
def add():
    check_csrf()
    db, s = book()
    shop = next((x for x in s["shops"] if x["id"] == request.form.get("shop")), None)
    kind = request.form.get("kind")
    bal = balance(open_entries(s, shop["id"])) if shop else 0
    amount = bal if kind == "payall" else parse_amount(request.form.get("amount"))
    if not shop or kind not in ("buy", "pay", "payall") or not amount or amount <= 0:
        flash("اختار الدكان واكتب المبلغ صح (أرقام بس)")
        return redirect(url_for("debts.dashboard"))
    s["entries"].append({"id": _id(), "shop": shop["id"], "kind": "buy" if kind == "buy" else "pay",
                         "amount": amount, "date": parse_date(request.form.get("date")),
                         "note": request.form.get("note", "").strip()[:300], "created": _now()})
    if kind != "buy" and settle_if_zero(s, shop):
        flash(f"✔ حساب {shop['name']} تصفّر وانتقل للأرشيف")
    save_db(db)
    return redirect(url_for("debts.dashboard"))


@bp.route("/delete", methods=["POST"])
@pin_required
def delete():
    check_csrf()
    db, s = book()
    s["entries"] = [e for e in s["entries"] if e["id"] != request.form.get("id")]
    save_db(db)
    return redirect(url_for("debts.dashboard"))


@bp.route("/shop", methods=["POST"])
@pin_required
def shop():
    check_csrf()
    db, s = book()
    action = request.form.get("action")
    name = request.form.get("name", "").strip()[:60]
    if action == "add" and name:
        s["shops"].append({"id": _id(), "name": name})
    elif action == "rename" and name:
        for x in s["shops"]:
            if x["id"] == request.form.get("id"):
                x["name"] = name
    elif action == "remove":
        sid = request.form.get("id")
        if open_entries(s, sid):
            flash("ما ينحذف: الدكان بي حساب مفتوح، سدده أول")
        else:
            s["shops"] = [x for x in s["shops"] if x["id"] != sid]
    save_db(db)
    return redirect(url_for("debts.dashboard"))
