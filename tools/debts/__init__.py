"""Shop tab (دفتر الدين): purchases on credit per shop, payments, and an archive.

Each shop has an open account: purchases add to the debt, payments subtract. When a
payment brings a shop's balance to zero (or below), its open entries move to the archive
as one closed account; any overpayment carries into the new account as credit.
"""
import json
import os
import secrets
import time
from functools import wraps
from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

bp = Blueprint("debts", __name__, template_folder="../../templates")

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "debts.json")
IRAQ = timezone(timedelta(hours=3))
DEFAULT_SHOPS = ["دكان أحمد أنس", "دكان ابن هذال", "دكان عمار (مخضر)", "مول حبش"]
UNLOCK_SECONDS = 3600      # the PIN is asked again after an hour
MAX_TRIES, LOCK_SECONDS = 5, 15 * 60
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def load():
    try:
        with open(STATE) as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {"shops": [{"id": _id(), "name": n} for n in DEFAULT_SHOPS]}
        save(s)  # pin the default shops' ids
    s.setdefault("shops", [])
    s.setdefault("entries", [])
    s.setdefault("archive", [])
    return s


def save(s):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


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
    """The book opens with its own PIN (no hub password needed once the PIN is set)."""
    @wraps(f)
    def w(*a, **k):
        if session.get("debts_until", 0) < time.time():
            session.pop("debts_until", None)
            return redirect(url_for("debts.lock"))
        session["debts_until"] = time.time() + UNLOCK_SECONDS
        return f(*a, **k)
    return w


def valid_pin(p):
    return len(p) == 6 and p.isdigit()


@bp.route("/lock", methods=["GET", "POST"])
def lock():
    s = load()
    setup = not s.get("pin")
    if setup and not session.get("admin"):
        # First-time setup needs the hub admin password, so nobody else can claim the PIN.
        return redirect(url_for("login", next=url_for("debts.lock")))
    wait = int(s.get("locked_until", 0) - time.time())
    if request.method == "POST":
        check_csrf()
        pin = request.form.get("pin", "").translate(DIGITS).strip()
        if setup:
            if not valid_pin(pin) or pin != request.form.get("pin2", "").translate(DIGITS).strip():
                flash("الرمز لازم 6 أرقام، ونفس الرمز بالخانتين")
            else:
                s["pin"] = generate_password_hash(pin)
                save(s)
                session["debts_until"] = time.time() + UNLOCK_SECONDS
                return redirect(url_for("debts.dashboard"))
        elif wait > 0:
            pass
        elif check_password_hash(s["pin"], pin):
            s["fails"], s["locked_until"] = 0, 0
            save(s)
            session["debts_until"] = time.time() + UNLOCK_SECONDS
            return redirect(url_for("debts.dashboard"))
        else:
            s["fails"] = s.get("fails", 0) + 1
            if s["fails"] >= MAX_TRIES:
                s["fails"], s["locked_until"] = 0, time.time() + LOCK_SECONDS
                wait = LOCK_SECONDS
            else:
                flash(f"الرمز غلط (باقي {MAX_TRIES - s['fails']} محاولات)")
            save(s)
    return render_template("debts/lock.html", setup=setup, wait=max(wait, 0))


@bp.route("/logout", methods=["POST"])
def logout():
    check_csrf()
    session.pop("debts_until", None)
    return redirect(url_for("debts.lock"))


@bp.route("/pin", methods=["POST"])
@pin_required
def change_pin():
    check_csrf()
    s = load()
    new = request.form.get("new", "").translate(DIGITS).strip()
    if not check_password_hash(s["pin"], request.form.get("old", "").translate(DIGITS).strip()):
        flash("الرمز الحالي غلط")
    elif not valid_pin(new):
        flash("الرمز الجديد لازم 6 أرقام")
    else:
        s["pin"] = generate_password_hash(new)
        save(s)
        flash("✔ تغيّر الرمز")
    return redirect(url_for("debts.dashboard"))


@bp.app_template_filter("iqd")
def iqd(n):
    return f"{n:,}"


@bp.route("/")
@pin_required
def dashboard():
    s = load()
    shops = []
    for sh in s["shops"]:
        items = sorted(open_entries(s, sh["id"]), key=lambda e: (e["date"], e["created"]), reverse=True)
        shops.append({**sh, "balance": balance(items), "entries": items,
                      "since": items[-1]["date"] if items else None})
    shops.sort(key=lambda x: -x["balance"])
    total = sum(max(x["balance"], 0) for x in shops)
    return render_template("debts/dashboard.html", shops=shops, total=total, archive=s["archive"],
                           today=today(), pick=request.args.get("shop", ""))


@bp.route("/add", methods=["POST"])
@pin_required
def add():
    check_csrf()
    s = load()
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
    save(s)
    return redirect(url_for("debts.dashboard"))


@bp.route("/delete", methods=["POST"])
@pin_required
def delete():
    check_csrf()
    s = load()
    s["entries"] = [e for e in s["entries"] if e["id"] != request.form.get("id")]
    save(s)
    return redirect(url_for("debts.dashboard"))


@bp.route("/shop", methods=["POST"])
@pin_required
def shop():
    check_csrf()
    s = load()
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
    save(s)
    return redirect(url_for("debts.dashboard"))
