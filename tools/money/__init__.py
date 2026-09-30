"""First $10: ten parallel ways to earn it, plus an inputs box between the owner and Claude.

The owner fills inputs (city, ad text, payment number, tokens...). The server checks what it
can itself (phone/card format, Facebook and Telegram tokens), and Claude reviews the rest
through the key-protected API and marks each one ✔ or ✗ with a note. The owner can also
mark an input as correct himself. Secret values (tokens) live in a separate file and never
leave the server: the page and the API only show a masked hint and the check result.
"""
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

bp = Blueprint("money", __name__, template_folder="../../templates")

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
STATE = os.path.join(DATA, "money.json")
SECRETS = os.path.join(DATA, "money_secrets.json")
IRAQ = timezone(timedelta(hours=3))

KINDS = {"text": "نص قصير", "long": "نص طويل", "pay": "رقم استلام فلوس", "phone": "رقم هاتف",
         "fb_token": "توكن صفحة فيسبوك", "tg_token": "توكن بوت تيليجرام", "secret": "سر آخر (يبقى مخفي)",
         "url": "رابط"}
SECRET_KINDS = {"fb_token", "tg_token", "secret"}

# Inputs the plan needs from the owner: (id, label, kind, hint)
DEFAULT_INPUTS = [
    ("net", "أوقات النت عندك", "text", "بأي ساعات النت يكون زين؟ حتى نرتب الشغل عليها"),
    ("name", "اسمك مثل ما يظهر للزبائن", "text", "يطلع بالرسائل والعروض"),
    ("ads", "نص الإعلانين", "long", "انسخ نص الإعلان الأول والثاني هنا"),
    ("prices", "أسعار الدورات الأونلاين", "long", "مثلاً: موبايل أونلاين 100 ألف، مواقع ..."),
    ("deposit", "مبلغ العربون", "text", "مثلاً 25 ألف يثبّت مكان الطالب"),
    ("pay", "رقم استلام الفلوس (كي كارد أو زين كاش)", "pay",
     "رقم البطاقة (16 رقم) أو رقم زين كاش. لا تكتب PIN ولا CVV ولا رمز OTP أبداً"),
    ("whatsapp", "رقم الواتساب للزبائن", "phone", "بصيغة 07XXXXXXXXX"),
    ("groups", "الجروبات والقنوات اللي إنت بيها", "long", "روابط جروبات فيسبوك وتيليجرام (برمجة، طلاب، عمل حر، أصحاب مولدات)"),
    ("projects", "روابط مشاريعك الجاهزة", "long", "moalidaty، العيادة، الموظفين، البصمة: رابط أو APK أو صور"),
    ("fb_token", "توكن صفحة Golden Code", "fb_token", "اختياري. السيرفر يتحقق منه ويخفيه، ما ينعرض لأحد"),
]

# Plan sections: (title, emoji, colour, [(who, text)]); who: "you" = the owner, "me" = Claude.
# Everything is online: the owner lives in a remote village with no local market.
PLAN = [
    ("تجهيزاتك الليلة", "🌙", "c-violet", [
        ("you", "تعبّي خانات «المعطيات» فوگ، وأنا أتحقق منها وأعلّم ✔ أو ✗"),
        ("you", "لا تنطي PIN ولا CVV ولا OTP لأي أحد، ولا حتى إلي"),
        ("you", "تنضم لـ 10 جروبات فيسبوك وتيليجرام: برمجة، طلاب جامعات، عمل حر، أصحاب مولدات"),
    ]),
    ("خطة باچر (كلها أونلاين)", "📅", "c-ocean", [
        ("me", "الصبح: قائمة زبائن محتملين من النت، وكل الرسائل والمنشورات جاهزة"),
        ("you", "نشر الإعلانين بالصفحة و5 جروبات (الطريقة 1)"),
        ("you", "رسائل شخصية على ماسنجر وإنستغرام لـ 10 أهداف أنا أختارهم (الطرق 3 و4)"),
        ("me", "دفعة إيميلات للشركات بعد موافقتك (الطريقة 7)"),
        ("you", "العصر: تدزلي كل محادثة وأنا أكتبلك الرد"),
        ("me", "بالليل: تقرير اليوم: منو رد، منو مهتم، منو دفع، وخطة اليوم الثاني"),
    ]),
    ("1. عربون دورة أونلاين (الأسرع)", "🎓", "c-sun", [
        ("me", "نص الرد على المهتمين، ونموذج التسجيل، ورسالة الدفع"),
        ("you", "نشر الإعلانين بصفحة Golden Code وجروبات البرمجة والطلاب بكل العراق"),
        ("you", "الرد على كل مهتم خلال ساعة"),
        ("you", "🎯 أول عربون (15-25 ألف) من مسجّل جديد"),
    ]),
    ("2. جلسات أونلاين لطلاب الجامعات", "🧑‍💻", "c-ocean", [
        ("me", "إعلان جلسة ساعة (10-15 ألف) على Google Meet لتصليح الأخطاء والشرح، تدريس مو حل واجبات"),
        ("you", "نشره بجروبات الكليات وقنوات تيليجرام الطلاب"),
        ("me", "تحضير مادة كل جلسة قبلها"),
        ("you", "🎯 أول جلسة مدفوعة"),
    ]),
    ("3. خدمات عن بعد لمحلات تعلن أونلاين", "🏪", "c-teal", [
        ("me", "أدور صفحات محلات ومطاعم عراقية نشطة وناقصها شي: منيو QR، موقع على خرائط Google، ردود واتساب"),
        ("me", "ديمو جاهز باسم كل محل (منيو أو صفحة) ورسالة شخصية إله"),
        ("you", "ترسل الرسالة من صفحتك أو ماسنجر (5-10 باليوم، مو رسائل جماعية)"),
        ("you", "🎯 أول محل يدفع (15-25 ألف)"),
    ]),
    ("4. نظام المولدات لأصحاب المولدات بكل العراق", "⚡", "c-ember", [
        ("me", "صفحة عرض وفيديو قصير يشرح النظام"),
        ("me", "أدور جروبات وصفحات أصحاب المولدات وأكتب منشور عرض"),
        ("you", "تنشر العرض: أسبوع تجربة مجاني ويا شرح بمكالمة فيديو"),
        ("you", "🎯 أول اشتراك شهري (15-25 ألف)"),
    ]),
    ("5. باقات بوسترات للصفحات", "🖼️", "c-violet", [
        ("me", "3 نماذج بوسترات من مولّد البوسترات، ومنشور عرض"),
        ("you", "تعرض باقة 10 بوسترات بـ 15 ألف على صفحات ومحلات بالنت"),
        ("you", "🎯 أول باقة تنباع"),
    ]),
    ("6. صيد طلبات «مطلوب مبرمج»", "🎣", "c-teal", [
        ("me", "بحث يومي بالويب عن طلبات برمجة بالجروبات العراقية والعربية"),
        ("me", "عرض مخصص لكل طلب"),
        ("you", "ترسل العرض وتتابع"),
        ("you", "🎯 أول مهمة صغيرة مدفوعة"),
    ]),
    ("7. إيميلات لشركات ووكالات", "✉️", "c-ember", [
        ("me", "قائمة 20 وكالة وشركة برمجيات بالعراق والخليج ويا إيميلاتها العامة"),
        ("me", "إيميل مخصص لكل وحدة كمسودة بـ Gmail"),
        ("you", "توافق وأنا أرسل (بدون رسائل جماعية عشوائية)"),
        ("me", "متابعة الردود بعد يومين"),
        ("you", "🎯 أول مهمة (10-50$)"),
    ]),
    ("8. تصليح مشاكل Flutter وPython للمطورين", "🛠️", "c-sun", [
        ("me", "منشور خدمة: «مشكلتك بـ Flutter أو Python، أحلها خلال ساعة» بـ 10-15 ألف"),
        ("you", "تنشره بجروبات المطورين العرب والعراقيين"),
        ("me", "أساعدك بحل كل مشكلة توصل"),
        ("you", "🎯 أول مشكلة مدفوعة"),
    ]),
    ("9. محتوى الصفحة يبيع", "📣", "c-ocean", [
        ("me", "منشور يومي بصفحة Golden Code ينتهي بعرض خدمة واضح وزر واتساب"),
        ("you", "توافق عليه من تيليجرام"),
        ("you", "🎯 أول زبون يجي من الصفحة"),
    ]),
    ("10. منتج رقمي يتباع", "📦", "c-violet", [
        ("me", "قالب بوت تيليجرام أو قالب Flutter جاهز للبيع"),
        ("me", "صفحة هبوط ودفع بتحويل على رقمك وإنت تأكد"),
        ("you", "نشره بالصفحة والجروبات"),
        ("you", "🎯 أول نسخة تنباع"),
    ]),
]
STEP_KEYS = {f"{n}-{i}" for n, (_, _, _, st) in enumerate(PLAN) for i in range(len(st))}


def now():
    return datetime.now(IRAQ).strftime("%Y-%m-%d %H:%M")


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(path, d):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load():
    s = _read(STATE)
    s.setdefault("done", [])
    s.setdefault("inputs", {})
    s.setdefault("order", [])
    s.setdefault("earned", 0)
    if not s.get("api_key"):
        s["api_key"] = secrets.token_urlsafe(24)
        _write(STATE, s)
    wanted = {d[0] for d in DEFAULT_INPUTS}
    for iid in [i for i, it in s["inputs"].items() if it.get("by") == "plan" and i not in wanted]:
        if not s["inputs"][iid].get("value"):
            s["inputs"].pop(iid)
            s["order"].remove(iid)
    for iid, label, kind, hint in DEFAULT_INPUTS:
        if iid not in s["inputs"]:
            s["inputs"][iid] = {"label": label, "kind": kind, "hint": hint, "by": "plan"}
            s["order"].append(iid)
        else:
            s["inputs"][iid].update(label=label, hint=hint)
    s["order"] = [i for i, _, _, _ in DEFAULT_INPUTS] + [i for i in s["order"] if i not in wanted]
    for it in s["inputs"].values():
        it.setdefault("status", "empty")
        it.setdefault("value", "")
        it.setdefault("note", "")
    return s


def save(s):
    _write(STATE, s)


def mask(v):
    v = v.strip()
    return "•" * 6 + v[-4:] if len(v) > 8 else "•" * len(v)


def luhn(n):
    total = 0
    for i, d in enumerate(reversed(n)):
        d = int(d)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


IQ_PHONE = re.compile(r"^(?:\+?964|0)?(7[3-9]\d{8})$")


def check(kind, v):
    """Server-side check: (status, note). status: ok, wrong, sent (needs Claude/owner review)."""
    v = v.strip()
    digits = re.sub(r"[\s\-]", "", v)
    if kind == "phone":
        m = IQ_PHONE.match(digits)
        return ("ok", "رقم عراقي صحيح: 0" + m.group(1)) if m else ("wrong", "مو رقم موبايل عراقي (07XXXXXXXXX)")
    if kind == "pay":
        if IQ_PHONE.match(digits):
            return "ok", "رقم زين كاش بصيغة صحيحة"
        if digits.isdigit() and len(digits) == 16:
            return ("ok", "رقم بطاقة صحيح (فحص Luhn)") if luhn(digits) else ("wrong", "رقم البطاقة بي غلط بأحد الأرقام")
        if digits.isdigit() and len(digits) in (3, 4, 6):
            return "wrong", "هذا يشبه PIN أو CVV أو OTP. لا تكتبه هنا"
        return "wrong", "لازم يكون 16 رقم (بطاقة) أو رقم زين كاش 07XXXXXXXXX"
    if kind == "fb_token":
        try:
            r = requests.get("https://graph.facebook.com/v19.0/me", params={"access_token": v, "fields": "id,name"},
                             timeout=20).json()
        except (requests.RequestException, ValueError) as e:
            return "sent", f"ما گدرت أوصل لفيسبوك هسه: {type(e).__name__}"
        if "error" in r:
            return "wrong", "فيسبوك رفض التوكن: " + r["error"].get("message", "")[:160]
        return "ok", f"التوكن شغال: {r.get('name')} ({r.get('id')})"
    if kind == "tg_token":
        try:
            r = requests.get(f"https://api.telegram.org/bot{v}/getMe", timeout=20).json()
        except (requests.RequestException, ValueError) as e:
            return "sent", f"ما گدرت أوصل لتيليجرام هسه: {type(e).__name__}"
        return ("ok", "البوت شغال: @" + r["result"].get("username", "")) if r.get("ok") else ("wrong", "تيليجرام رفض التوكن")
    if kind == "url":
        if not re.match(r"^https?://", v):
            return "wrong", "الرابط لازم يبدي بـ https://"
        try:
            code = requests.get(v, timeout=20, allow_redirects=True).status_code
        except requests.RequestException as e:
            return "sent", f"ما گدرت أفتح الرابط: {type(e).__name__}"
        return ("ok", "الرابط يفتح") if code < 400 else ("wrong", f"الرابط يرجع خطأ {code}")
    return "sent", "بانتظار مراجعة Claude"


def set_value(s, iid, value):
    it = s["inputs"][iid]
    value = value.strip()[:8000]
    if it["kind"] == "pay" and re.fullmatch(r"\d{3,4}|\d{6}", re.sub(r"[\s\-]", "", value)):
        # looks like a PIN, CVV or OTP: never keep it
        it.update(value="", status="wrong", note="هذا يشبه PIN أو CVV أو OTP، ما انحفظ. اكتب رقم البطاقة أو زين كاش بس",
                  note_by="server", at=now())
        return
    if it["kind"] in SECRET_KINDS:
        sec = _read(SECRETS)
        if value:
            sec[iid] = value
        else:
            sec.pop(iid, None)
        _write(SECRETS, sec)
        it["value"] = mask(value) if value else ""
    else:
        it["value"] = value
    if value:
        it["status"], it["note"] = check(it["kind"], value)
        it["note_by"] = "server" if it["status"] != "sent" else ""
    else:
        it["status"], it["note"] = "empty", ""
    it["at"] = now()


def public(s):
    """State without the API key; secret values are already masked."""
    return {"inputs": [dict(s["inputs"][i], id=i) for i in s["order"] if i in s["inputs"]],
            "done": s["done"], "earned": s["earned"],
            "plan": [{"title": t, "steps": [{"key": f"{n}-{i}", "who": w, "text": x} for i, (w, x) in enumerate(st)]}
                     for n, (t, _, _, st) in enumerate(PLAN)]}


def _admin():
    from app import check_csrf, login_required
    return check_csrf, login_required


check_csrf, login_required = _admin()


@bp.route("/")
@login_required
def dashboard():
    s = load()
    save(s)
    done = set(s["done"])
    sections = []
    for n, (title, emoji, colour, steps) in enumerate(PLAN):
        items = [{"key": f"{n}-{i}", "who": w, "text": t, "done": f"{n}-{i}" in done} for i, (w, t) in enumerate(steps)]
        c = sum(x["done"] for x in items)
        sections.append({"title": title, "emoji": emoji, "colour": colour, "steps": items, "count": c,
                         "total": len(items), "pct": round(100 * c / len(items))})
    total = sum(x["total"] for x in sections)
    count = sum(x["count"] for x in sections)
    inputs = [dict(s["inputs"][i], id=i) for i in s["order"] if i in s["inputs"]]
    stats = {k: sum(1 for x in inputs if x["status"] == k) for k in ("empty", "sent", "ok", "wrong")}
    return render_template("money/dashboard.html", sections=sections, total=total, count=count,
                           pct=round(100 * count / total), inputs=inputs, stats=stats, kinds=KINDS,
                           secret_kinds=SECRET_KINDS, earned=s["earned"])


@bp.route("/toggle", methods=["POST"])
@login_required
def toggle():
    check_csrf()
    key = request.form.get("key", "")
    if key not in STEP_KEYS:
        return jsonify(ok=False), 400
    s = load()
    done = set(s["done"]) ^ {key}
    s["done"] = sorted(done)
    save(s)
    return jsonify(ok=True, done=key in done)


@bp.route("/input/<iid>", methods=["POST"])
@login_required
def save_input(iid):
    check_csrf()
    s = load()
    if iid not in s["inputs"]:
        abort(404)
    act = request.form.get("act", "save")
    it = s["inputs"][iid]
    if act == "save":
        set_value(s, iid, request.form.get("value", ""))
    elif act == "mine_ok" and it["status"] != "empty":
        it["status"], it["note"], it["note_by"] = "ok", "إنت أكدت إنها صح", "you"
    elif act == "delete" and it.get("by") != "plan":
        s["inputs"].pop(iid)
        s["order"].remove(iid)
        sec = _read(SECRETS)
        if sec.pop(iid, None) is not None:
            _write(SECRETS, sec)
    save(s)
    return redirect(url_for("money.dashboard") + "#inputs")


@bp.route("/input/new", methods=["POST"])
@login_required
def new_input():
    check_csrf()
    label = request.form.get("label", "").strip()[:120]
    kind = request.form.get("kind", "text")
    if not label or kind not in KINDS:
        return redirect(url_for("money.dashboard") + "#inputs")
    s = load()
    iid = "u" + secrets.token_hex(3)
    s["inputs"][iid] = {"label": label, "kind": kind, "hint": "", "by": "you", "status": "empty", "value": "", "note": ""}
    s["order"].append(iid)
    set_value(s, iid, request.form.get("value", ""))
    save(s)
    return redirect(url_for("money.dashboard") + "#inputs")


@bp.route("/earned", methods=["POST"])
@login_required
def earned():
    check_csrf()
    s = load()
    try:
        s["earned"] = max(0, int(request.form.get("earned", "0").replace(",", "")))
    except ValueError:
        pass
    save(s)
    return redirect(url_for("money.dashboard"))


# ---- API for Claude (header X-Key) ----

def _api():
    s = load()
    if not secrets.compare_digest(request.headers.get("X-Key", ""), s["api_key"]):
        abort(403)
    return s


@bp.route("/api/state")
def api_state():
    return jsonify(public(_api()))


@bp.route("/api/review", methods=["POST"])
def api_review():
    """Claude marks an input: {"id", "status": "ok"|"wrong", "note"}."""
    s = _api()
    d = request.get_json(force=True, silent=True) or {}
    it = s["inputs"].get(d.get("id"))
    if not it or d.get("status") not in ("ok", "wrong"):
        return jsonify(ok=False, error="need id and status ok|wrong"), 400
    it["status"], it["note"], it["note_by"], it["reviewed_at"] = d["status"], str(d.get("note", ""))[:1000], "claude", now()
    save(s)
    return jsonify(ok=True)


@bp.route("/api/ask", methods=["POST"])
def api_ask():
    """Claude asks the owner for a new input: {"label", "kind", "hint"}."""
    s = _api()
    d = request.get_json(force=True, silent=True) or {}
    label, kind = str(d.get("label", "")).strip()[:120], d.get("kind", "text")
    if not label or kind not in KINDS:
        return jsonify(ok=False, error="need label and a valid kind"), 400
    iid = "c" + secrets.token_hex(3)
    s["inputs"][iid] = {"label": label, "kind": kind, "hint": str(d.get("hint", ""))[:300], "by": "claude",
                        "status": "empty", "value": "", "note": "", "at": now()}
    s["order"].append(iid)
    save(s)
    return jsonify(ok=True, id=iid)


@bp.route("/api/steps", methods=["POST"])
def api_steps():
    """Claude ticks plan steps: {"keys": [...], "done": true|false}."""
    s = _api()
    d = request.get_json(force=True, silent=True) or {}
    keys = {k for k in d.get("keys", []) if k in STEP_KEYS}
    done = set(s["done"])
    s["done"] = sorted(done | keys if d.get("done", True) else done - keys)
    save(s)
    return jsonify(ok=True, done=s["done"])
