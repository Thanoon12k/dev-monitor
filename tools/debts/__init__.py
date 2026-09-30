"""Shop tab (دفتر الدين): purchases on credit per shop, payments, and an archive.

Each shop has an open account: purchases add to the debt, payments subtract. When a
payment brings a shop's balance to zero (or below), its open entries move to the archive
as one closed account; any overpayment carries into the new account as credit.
"""
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for

bp = Blueprint("debts", __name__, template_folder="../../templates")

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "debts.json")
IRAQ = timezone(timedelta(hours=3))
DEFAULT_SHOPS = ["دكان أحمد أنس", "دكان ابن هذال", "دكان عمار (مخضر)", "مول حبش"]
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
    from app import check_csrf, login_required
    return check_csrf, login_required


check_csrf, login_required = _admin()


@bp.app_template_filter("iqd")
def iqd(n):
    return f"{n:,}"


@bp.route("/")
@login_required
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
@login_required
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
@login_required
def delete():
    check_csrf()
    s = load()
    s["entries"] = [e for e in s["entries"] if e["id"] != request.form.get("id")]
    save(s)
    return redirect(url_for("debts.dashboard"))


@bp.route("/shop", methods=["POST"])
@login_required
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
