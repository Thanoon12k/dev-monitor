"""Golden Code ad manager: campaigns, public order form, orders dashboard."""
import os
import sqlite3
import urllib.parse
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

bp = Blueprint("goldencode", __name__, template_folder="../../templates")

PAGE_URL = "https://www.facebook.com/goldencode114"
WHATSAPP = "9647847569167"  # 07847569167
IRAQ = timezone(timedelta(hours=3))
STATUSES = [("new", "جديد"), ("contacted", "تم التواصل"), ("in_progress", "قيد التنفيذ"),
            ("done", "تم التسليم"), ("cancelled", "ملغي")]
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "goldencode.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, platform TEXT, budget REAL DEFAULT 0,
  spent REAL DEFAULT 0, reach INTEGER DEFAULT 0, clicks INTEGER DEFAULT 0,
  start_date TEXT, end_date TEXT, status TEXT DEFAULT 'active', notes TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, service TEXT,
  details TEXT, campaign_id INTEGER, price REAL DEFAULT 0, status TEXT DEFAULT 'new',
  created TEXT);
"""


def db():
    if "gc_db" not in g:
        g.gc_db = sqlite3.connect(DB)
        g.gc_db.row_factory = sqlite3.Row
        g.gc_db.executescript(SCHEMA)
    return g.gc_db


@bp.teardown_app_request
def _close(_):
    c = g.pop("gc_db", None)
    if c:
        c.close()


def now():
    return datetime.now(IRAQ).strftime("%Y-%m-%d %H:%M")


def wa_link(phone, text=""):
    p = "".join(ch for ch in phone if ch.isdigit())
    if p.startswith("0"):
        p = "964" + p[1:]
    return "https://wa.me/" + p + ("?text=" + urllib.parse.quote(text) if text else "")


def _admin():
    from app import check_csrf, login_required
    return check_csrf, login_required


check_csrf, login_required = _admin()


@bp.app_template_global()
def gc_wa(phone, text=""):
    return wa_link(phone, text)


# ---------- public ----------

@bp.route("/order", methods=["GET", "POST"])
def order():
    """Public form the ad links to: /goldencode/order?c=<campaign id>"""
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        phone = request.form.get("phone", "").strip()[:30]
        if not name or sum(ch.isdigit() for ch in phone) < 10 or request.form.get("website"):
            flash("اكتب الاسم ورقم موبايل صحيح")
            return render_template("goldencode/order.html", wa=WHATSAPP, page=PAGE_URL)
        cid = request.form.get("c", "")
        db().execute("INSERT INTO orders(name,phone,service,details,campaign_id,created) VALUES(?,?,?,?,?,?)",
                     (name, phone, request.form.get("service", "")[:100],
                      request.form.get("details", "")[:1000], int(cid) if cid.isdigit() else None, now()))
        db().commit()
        return render_template("goldencode/thanks.html", wa=wa_link(WHATSAPP, f"مرحبا، أنا {name} سجلت طلب من الإعلان"))
    return render_template("goldencode/order.html", wa=WHATSAPP, page=PAGE_URL)


# ---------- admin ----------

@bp.route("/")
@login_required
def dashboard():
    d = db()
    status = request.args.get("status", "")
    q = "SELECT o.*, c.name AS campaign FROM orders o LEFT JOIN campaigns c ON c.id=o.campaign_id"
    orders = d.execute(q + (" WHERE o.status=?" if status else "") + " ORDER BY o.id DESC",
                       (status,) if status else ()).fetchall()
    camps = d.execute("SELECT c.*, (SELECT COUNT(*) FROM orders o WHERE o.campaign_id=c.id) AS n_orders,"
                      " (SELECT COALESCE(SUM(price),0) FROM orders o WHERE o.campaign_id=c.id AND o.status='done') AS revenue"
                      " FROM campaigns c ORDER BY c.id DESC").fetchall()
    s = d.execute("SELECT COUNT(*) n, SUM(status='new') new, SUM(status='done') done,"
                  " COALESCE(SUM(CASE WHEN status='done' THEN price END),0) revenue FROM orders").fetchone()
    spent = d.execute("SELECT COALESCE(SUM(spent),0) FROM campaigns").fetchone()[0]
    return render_template("goldencode/dashboard.html", orders=orders, camps=camps, s=s, spent=spent,
                           statuses=STATUSES, cur=status, page=PAGE_URL, wa=WHATSAPP)


@bp.route("/orders/<int:oid>", methods=["POST"])
@login_required
def update_order(oid):
    check_csrf()
    st = request.form.get("status")
    if st not in dict(STATUSES):
        abort(400)
    try:
        price = float(request.form.get("price") or 0)
    except ValueError:
        price = 0
    db().execute("UPDATE orders SET status=?, price=? WHERE id=?", (st, price, oid))
    db().commit()
    return redirect(request.referrer or url_for(".dashboard"))


@bp.route("/campaigns/new", methods=["GET", "POST"])
@bp.route("/campaigns/<int:cid>", methods=["GET", "POST"])
@login_required
def campaign(cid=None):
    d = db()
    row = d.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone() if cid else None
    if cid and not row:
        abort(404)
    if request.method == "POST":
        check_csrf()
        f = request.form

        def num(k, t=float):
            try:
                return t(f.get(k) or 0)
            except ValueError:
                return 0
        vals = (f.get("name", "").strip() or "حملة", f.get("platform", ""), num("budget"), num("spent"),
                num("reach", int), num("clicks", int), f.get("start_date", ""), f.get("end_date", ""),
                f.get("status", "active"), f.get("notes", ""))
        if row:
            d.execute("UPDATE campaigns SET name=?,platform=?,budget=?,spent=?,reach=?,clicks=?,start_date=?,"
                      "end_date=?,status=?,notes=? WHERE id=?", vals + (cid,))
        else:
            d.execute("INSERT INTO campaigns(name,platform,budget,spent,reach,clicks,start_date,end_date,status,"
                      "notes,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)", vals + (now(),))
        d.commit()
        return redirect(url_for(".dashboard"))
    return render_template("goldencode/campaign.html", c=row)
