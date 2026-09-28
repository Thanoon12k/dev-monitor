"""Viraliq: daily trend posts, approved from Telegram, then published on time.

Drafts arrive as data/viraliq/inbox/<id>.json (+ <id>.png), uploaded by the
scheduled Claude routine through the PythonAnywhere files API (submit.py).
/viraliq/tick ingests them, sends each to the owner's Telegram with buttons
(approve / edit / time / cancel), and publishes approved posts that are due.
Publishing goes to the Golden Code Facebook page (using the page token the
Golden Code tool already stores) and/or a Telegram channel; with neither, the
bot hands the final post back to the owner to post by hand.
"""
import fcntl
import json
import os
import re
import secrets
import shutil
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for

bp = Blueprint("viraliq", __name__)

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(BASE, "data", "viraliq")
INBOX, IMG = os.path.join(DIR, "inbox"), os.path.join(DIR, "img")
for _d in (INBOX, IMG):
    os.makedirs(_d, exist_ok=True)
CFG, POSTS, LOCK = (os.path.join(DIR, n) for n in ("config.json", "posts.json", ".lock"))
TZ = timezone(timedelta(hours=3))  # Baghdad, no DST
TG = "https://api.telegram.org/bot{}/{}"
GRAPH = "https://graph.facebook.com/v21.0/"
DEFAULT_CHAT = "647908098"
GOLDEN_PAGE = "423528124186043"  # facebook.com/goldencode114


# ---------- storage ----------

def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


@contextmanager
def state():
    """Exclusive access to (config, posts); saved on exit."""
    with open(LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        cfg, posts = _load(CFG, {}), _load(POSTS, [])
        yield cfg, posts
        _save(CFG, cfg)
        _save(POSTS, posts)


def now():
    return datetime.now(TZ)


def fmt(iso):
    return datetime.fromisoformat(iso).astimezone(TZ).strftime("%Y-%m-%d %H:%M") if iso else "—"


def parse_time(s, base=None):
    """'21:30', '2026-09-28 21:30', 'الآن'/'now' -> aware datetime (Baghdad)."""
    s = s.strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    base = base or now()
    if s in ("الآن", "الان", "هسه", "now"):
        return base + timedelta(minutes=1)
    m = re.fullmatch(r"(\d{4}-\d{1,2}-\d{1,2})[ T](\d{1,2}):(\d{2})", s)
    if m:
        return datetime.strptime(f"{m[1]} {m[2]}:{m[3]}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if m:
        t = base.replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
        return t if t > base else t + timedelta(days=1)
    return None


def find(posts, pid):
    return next((p for p in posts if p["id"] == pid), None)


def full_text(p):
    tags = " ".join(p.get("hashtags", []))
    return (p["text"].strip() + ("\n\n" + tags if tags else "")).strip()


# ---------- telegram ----------

def tg(cfg, method, files=None, **params):
    if not cfg.get("token"):
        return {}
    data = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in params.items()}
    try:
        return requests.post(TG.format(cfg["token"], method), data=data, files=files, timeout=30).json()
    except (requests.RequestException, ValueError) as e:
        return {"ok": False, "description": str(e)}


def keyboard(pid):
    return {"inline_keyboard": [
        [{"text": "✅ موافقة", "callback_data": f"ok:{pid}"}, {"text": "✏️ تعديل", "callback_data": f"edit:{pid}"}],
        [{"text": "🕒 تغيير الوقت", "callback_data": f"time:{pid}"}, {"text": "❌ إلغاء", "callback_data": f"no:{pid}"}],
    ]}


def time_keyboard(pid):
    n = now()
    opts = [("🚀 الآن", n + timedelta(minutes=1)), ("بعد ساعة", n + timedelta(hours=1))]
    for h in (12, 18, 21):
        t = n.replace(hour=h, minute=0, second=0, microsecond=0)
        opts.append((("اليوم " if t > n else "باجر ") + f"{h}:00", t if t > n else t + timedelta(days=1)))
    t = (n + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    opts.append(("باجر 10:00", t))
    rows = [[{"text": a, "callback_data": f"at:{pid}:{int(b.timestamp())}"} for a, b in opts[i:i + 3]] for i in (0, 3)]
    rows.append([{"text": "✍️ أكتب الوقت", "callback_data": f"typetime:{pid}"}])
    return {"inline_keyboard": rows}


def status_line(p):
    return {
        "pending": f"⏳ بانتظار موافقتك · الوقت المقترح: {fmt(p['suggested_at'])}",
        "approved": f"✅ مجدول للنشر: {fmt(p.get('scheduled_at'))}"
                    + (" · 📅 مجدول داخل فيسبوك" if p.get("fb_sched") else ""),
        "published": f"🚀 نُشر {fmt(p.get('published_at'))}",
        "cancelled": "❌ ملغي",
    }[p["status"]]


def send_preview(cfg, p):
    """Poster (with short caption) followed by the full post text + buttons."""
    chat = cfg.get("chat_id", DEFAULT_CHAT)
    with open(os.path.join(IMG, p["image"]), "rb") as f:
        r = tg(cfg, "sendPhoto", files={"photo": f}, chat_id=chat,
               caption=f"🆕 منشور #{p['id']} · {p.get('kind', '')}\n{p['title']}")
    if not r.get("ok"):
        return False
    src = "\n".join(f"🔗 {u}" for u in p.get("sources", [])[:3])
    body = f"{full_text(p)}\n\n━━━━━━━━\n{status_line(p)}" + (f"\n\nالمصادر:\n{src}" if src else "")
    r2 = tg(cfg, "sendMessage", chat_id=chat, text=body[:4096], reply_markup=keyboard(p["id"]),
            disable_web_page_preview=True)
    p["tg_msg"] = r2.get("result", {}).get("message_id")
    return r2.get("ok", False)


def refresh(cfg, p, extra=""):
    """Rewrite the preview message's status line; keep buttons while it is still actionable."""
    if not p.get("tg_msg"):
        return
    body = f"{full_text(p)}\n\n━━━━━━━━\n{status_line(p)}" + (f"\n{extra}" if extra else "")
    kb = keyboard(p["id"]) if p["status"] in ("pending", "approved") else {"inline_keyboard": []}
    tg(cfg, "editMessageText", chat_id=cfg.get("chat_id", DEFAULT_CHAT), message_id=p["tg_msg"],
       text=body[:4096], reply_markup=kb, disable_web_page_preview=True)


def say(cfg, text, **kw):
    return tg(cfg, "sendMessage", chat_id=cfg.get("chat_id", DEFAULT_CHAT), text=text, **kw)


# ---------- publishing ----------

def fb_target(cfg):
    """(page id, token): explicit Viraliq settings, else the linked Golden Code page."""
    if cfg.get("fb_page") and cfg.get("fb_token"):
        return cfg["fb_page"], cfg["fb_token"]
    from app import load_cfg
    tok = load_cfg().get("fb_page_token")
    return (GOLDEN_PAGE, tok) if tok and not cfg.get("fb_off") else (None, None)


def fb_schedule(cfg, p):
    """Create the post inside Facebook as a scheduled (unpublished) photo post.

    Facebook accepts scheduled times from 10 minutes to 30 days ahead; outside that
    window, or on failure, the hub publishes it itself when the time comes.
    """
    page, token = fb_target(cfg)
    t = datetime.fromisoformat(p["scheduled_at"])
    if not page or p.get("fb_sched") or p.get("fb_err") or not now() + timedelta(minutes=11) <= t <= now() + timedelta(days=29):
        return
    try:
        with open(os.path.join(IMG, p["image"]), "rb") as f:
            r = requests.post(GRAPH + page + "/photos", files={"source": f}, timeout=60, data={
                "caption": full_text(p), "published": "false", "scheduled_publish_time": int(t.timestamp()),
                "access_token": token}).json()
    except (requests.RequestException, ValueError) as e:
        r = {"error": {"message": str(e)}}
    if r.get("id"):
        p["fb_sched"] = r.get("post_id") or r["id"]
    else:
        p["fb_err"] = r.get("error", {}).get("message", "خطأ غير معروف")
        say(cfg, f"⚠️ ما كدرت أجدول #{p['id']} داخل فيسبوك ({p['fb_err']}). راح ينتشر من التطبيق بوقته.")
    refresh(cfg, p)


def fb_unschedule(cfg, p):
    """Drop the Facebook-side scheduled post (before a time change, an edit or a cancel)."""
    pid = p.pop("fb_sched", None)
    p.pop("fb_err", None)
    page, token = fb_target(cfg)
    if pid and token:
        try:
            requests.delete(GRAPH + pid, params={"access_token": token}, timeout=30)
        except requests.RequestException:
            pass


def publish(cfg, p):
    text, img, done = full_text(p), os.path.join(IMG, p["image"]), []
    if cfg.get("channel"):
        with open(img, "rb") as f:
            if len(text) <= 1024:
                r = tg(cfg, "sendPhoto", files={"photo": f}, chat_id=cfg["channel"], caption=text)
            else:
                r = tg(cfg, "sendPhoto", files={"photo": f}, chat_id=cfg["channel"])
                r = r if not r.get("ok") else tg(cfg, "sendMessage", chat_id=cfg["channel"], text=text[:4096])
        done.append(f"تيليجرام {cfg['channel']}: " + ("✅" if r.get("ok") else f"❌ {r.get('description')}"))
    page, token = fb_target(cfg)
    if p.get("fb_sched"):
        done.append("فيسبوك: ✅ (انتشر من جدولة فيسبوك)")
    elif page:
        try:
            with open(img, "rb") as f:
                r = requests.post(GRAPH + page + "/photos", files={"source": f}, timeout=60,
                                  data={"caption": text, "access_token": token}).json()
        except (requests.RequestException, ValueError) as e:
            r = {"error": {"message": str(e)}}
        done.append("فيسبوك: " + ("✅" if r.get("id") else f"❌ {r.get('error', {}).get('message')}"))
    p["status"], p["published_at"] = "published", now().isoformat()
    p["result"] = done
    if done:
        say(cfg, f"🚀 منشور #{p['id']} انتشر:\n" + "\n".join(done))
    else:  # no target configured: hand it back ready to copy
        with open(img, "rb") as f:
            tg(cfg, "sendPhoto", files={"photo": f}, chat_id=cfg.get("chat_id", DEFAULT_CHAT),
               caption=f"⏰ حان وقت نشر #{p['id']} — احفظ الصورة وانسخ النص الجاي وانشره")
        say(cfg, text[:4096])
    refresh(cfg, p)


def tick():
    """Ingest new drafts, (re)send unsent previews, publish what is due. Idempotent."""
    report = {"ingested": 0, "sent": 0, "published": 0}
    with state() as (cfg, posts):
        for name in sorted(os.listdir(INBOX)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(INBOX, name)
            d = _load(path, None)
            png = path[:-5] + ".png"
            if not d or not os.path.exists(png):
                continue  # image still uploading
            pid = max([p["id"] for p in posts] + [0]) + 1
            shutil.move(png, os.path.join(IMG, f"{pid}.png"))
            os.remove(path)
            sug = parse_time(d.get("suggested_at", "")) or now() + timedelta(hours=2)
            posts.append({"id": pid, "kind": d.get("kind", "trend"), "title": d.get("title", ""),
                          "text": d.get("text", ""), "hashtags": d.get("hashtags", []),
                          "sources": d.get("sources", []), "image": f"{pid}.png", "status": "pending",
                          "suggested_at": sug.isoformat(), "created": now().isoformat(), "tg_msg": None})
            if d.get("request") and d["request"] in cfg.get("auto_reqs", []):
                cfg["auto_reqs"].remove(d["request"])
                posts[-1].update(status="approved", scheduled_at=now().isoformat(), auto=True)
            report["ingested"] += 1
        for p in posts:
            if p["status"] in ("pending", "approved") and p.get("auto") and not p.get("tg_msg") and cfg.get("token"):
                report["sent"] += send_preview(cfg, p)
            elif p["status"] == "pending" and not p.get("tg_msg") and cfg.get("token"):
                report["sent"] += send_preview(cfg, p)
            if cfg.get("token") and p["status"] == "approved" and p.get("scheduled_at"):
                if datetime.fromisoformat(p["scheduled_at"]) <= now():
                    publish(cfg, p)
                    report["published"] += 1
                else:
                    fb_schedule(cfg, p)
        watchdog(cfg, posts)
    return report


RUNS = ((8, "الصبح"), (20, "المسا"))  # routine hours (Baghdad); drafts expected within 45 min


def watchdog(cfg, posts):
    """Tell the owner once if a scheduled content run brought no drafts."""
    n = now()
    for hour, name in RUNS:
        start = n.replace(hour=hour, minute=0, second=0, microsecond=0)
        key = f"{start:%Y-%m-%d}-{hour}"
        if not cfg.get("token") or n < start + timedelta(minutes=45) or n > start + timedelta(hours=3) \
                or key in cfg.get("alerted", []):
            continue
        if not any(datetime.fromisoformat(p["created"]) >= start for p in posts):
            say(cfg, f"⚠️ مسودات {name} ({hour}:00) ما وصلت لحد هسه. الوكيل المجدول ما اشتغل أو فشل؛ "
                     "افتح Claude وكله يشغّل دفعة اليوم.")
        cfg["alerted"] = (cfg.get("alerted", []) + [key])[-10:]


# ---------- telegram webhook ----------

def on_callback(cfg, posts, cq):
    action, _, rest = cq.get("data", "").partition(":")
    pid = int(rest.split(":")[0]) if rest.split(":")[0].isdigit() else 0
    p = find(posts, pid)
    tg(cfg, "answerCallbackQuery", callback_query_id=cq["id"])
    if not p or p["status"] in ("published", "cancelled"):
        return
    if action == "ok":
        t = datetime.fromisoformat(p.get("scheduled_at") or p["suggested_at"])
        p["status"], p["scheduled_at"] = "approved", max(t, now() + timedelta(minutes=1)).isoformat()
        refresh(cfg, p)  # the tick after this webhook schedules it inside Facebook
    elif action == "no":
        fb_unschedule(cfg, p)
        p["status"] = "cancelled"
        refresh(cfg, p)
    elif action == "edit":
        cfg["await"] = {"kind": "edit", "id": pid}
        say(cfg, f"✏️ ارسل النص الجديد لمنشور #{pid} كاملاً (أو ارسل صورة جديدة للبوستر).\nللتراجع: /skip",
            reply_markup={"force_reply": True})
    elif action == "time":
        tg(cfg, "sendMessage", chat_id=cfg.get("chat_id", DEFAULT_CHAT),
           text=f"🕒 اختر وقت نشر #{pid}:", reply_markup=time_keyboard(pid))
    elif action == "typetime":
        cfg["await"] = {"kind": "time", "id": pid}
        say(cfg, "✍️ اكتب الوقت بصيغة 21:30 أو 2026-09-28 21:30 أو «الآن»", reply_markup={"force_reply": True})
    elif action == "at":
        t = datetime.fromtimestamp(int(rest.split(":")[1]), TZ)
        set_time(cfg, p, t)
        if cq.get("message"):
            tg(cfg, "deleteMessage", chat_id=cfg.get("chat_id", DEFAULT_CHAT), message_id=cq["message"]["message_id"])


def set_time(cfg, p, t):
    fb_unschedule(cfg, p)
    p["scheduled_at"], p["status"] = t.isoformat(), "approved"
    refresh(cfg, p)
    say(cfg, f"✅ #{p['id']} راح ينتشر {fmt(p['scheduled_at'])}")


def on_message(cfg, posts, msg):
    text = (msg.get("text") or msg.get("caption") or "").strip()
    wait = cfg.get("await") or {}
    if text.startswith("/"):
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0]
        if cmd == "/skip":
            cfg.pop("await", None)
            say(cfg, "تمام، ما تغيّر شي.")
        elif cmd == "/channel":
            cfg["channel"] = arg.strip()
            say(cfg, f"📢 قناة النشر: {cfg['channel'] or 'بدون (تستلم المنشور بيدك)'}\n"
                     "لازم تضيف البوت أدمن بالقناة حتى يكدر ينشر.")
        elif cmd == "/post":
            request_post(cfg, arg)
        elif cmd == "/postnow":
            request_post(cfg, arg, auto=True)
        elif cmd == "/queue":
            q = [p for p in posts if p["status"] in ("pending", "approved")]
            say(cfg, "\n".join(f"#{p['id']} {p['title'][:50]}\n   {status_line(p)}" for p in q) or "ماكو منشورات بالانتظار.")
        else:
            say(cfg, "أهلاً 👋 أني بوت رائج (Viraliq).\nكل يوم الساعة 8 الصبح و8 بالليل أبحث عن الترند وأرسلك مسودات "
                     "منشورات مع بوستر، وانت توافق أو تعدّل أو تغيّر الوقت أو تلغي.\n\n"
                     "✍️ تريد منشور عن موضوع معين؟ اكتبه برسالة (أو /post الموضوع) وأبحث وأكمله مع بوستر.\n"
                     "🚀 /postnow الموضوع: نفسه بس ينتشر مباشرة من يجهز بدون موافقة.\n\n"
                     "/queue المنشورات المنتظرة\n/channel @اسم_القناة لتحديد قناة النشر التلقائي\n"
                     f"معرّف المحادثة: {msg['chat']['id']}")
        return
    p = find(posts, wait.get("id", 0))
    if not p:  # free text outside an edit = a request for a new post on that topic
        request_post(cfg, text)
        return
    if wait["kind"] == "time":
        t = parse_time(text)
        if not t:
            say(cfg, "ما فهمت الوقت 🙏 جرّب مثل 21:30 أو 2026-09-28 21:30")
            return
        cfg.pop("await", None)
        set_time(cfg, p, t)
    elif wait["kind"] == "edit":
        cfg.pop("await", None)
        if msg.get("photo"):
            f = tg(cfg, "getFile", file_id=msg["photo"][-1]["file_id"]).get("result", {})
            if f.get("file_path"):
                data = requests.get(f"https://api.telegram.org/file/bot{cfg['token']}/{f['file_path']}", timeout=60).content
                with open(os.path.join(IMG, p["image"]), "wb") as out:
                    out.write(data)
        if text:  # the new text is the whole post, hashtags included
            p["text"], p["hashtags"] = text, []
        fb_unschedule(cfg, p)  # rescheduled with the new content on the next tick
        if p.get("tg_msg"):
            tg(cfg, "editMessageReplyMarkup", chat_id=cfg.get("chat_id", DEFAULT_CHAT), message_id=p["tg_msg"],
               reply_markup={"inline_keyboard": []})
        p["tg_msg"] = None
        send_preview(cfg, p)


FIRE_BETA = "experimental-cc-routine-2026-04-01"
MAX_REQUESTS_PER_DAY = 6


def request_post(cfg, topic, auto=False):
    """Start the on-demand Claude routine that researches `topic` and sends back a draft.

    With auto=True the finished post skips approval and is published as soon as it arrives.
    Returns the message shown to the owner (also sent on Telegram).
    """
    topic = (topic or "").strip()
    if len(topic) < 3:
        return say_back(cfg, "اكتب الموضوع اللي تريد عنه منشور، مثلاً:\n/post أفضل 5 أدوات ذكاء اصطناعي مجانية للطلاب")
    if not (cfg.get("fire_url") and cfg.get("fire_token")):
        return say_back(cfg, "⚙️ ميزة الطلب تحتاج رابط وتوكن الـ API للروتين «Viraliq · طلب منشور». حطهم بلوحة /viraliq/ مرة وحدة.")
    day = f"{now():%Y-%m-%d}"
    used = cfg.get("requests", {}).get(day, 0)
    if used >= MAX_REQUESTS_PER_DAY:
        return say_back(cfg, f"وصلت حد اليوم ({MAX_REQUESTS_PER_DAY} طلبات). باجر نكمل 🙏")
    rid = secrets.token_hex(3)
    try:
        r = requests.post(cfg["fire_url"], timeout=30, json={"text": f"[req:{rid}] {topic[:1500]}"}, headers={
            "Authorization": "Bearer " + cfg["fire_token"], "anthropic-beta": FIRE_BETA,
            "anthropic-version": "2023-06-01"})
        ok, err = r.ok, r.text[:300]
    except requests.RequestException as e:
        ok, err = False, str(e)
    if not ok:
        return say_back(cfg, f"⚠️ ما كدرت أشغّل الوكيل: {err}")
    cfg["requests"] = {day: used + 1}
    if auto:
        cfg["auto_reqs"] = (cfg.get("auto_reqs", []) + [rid])[-20:]
        return say_back(cfg, f"🔎 دا أبحث عن: «{topic[:200]}»\n🚀 من يجهز خلال 5 إلى 15 دقيقة ينتشر مباشرة بدون موافقة، ويوصلك هنا.")
    return say_back(cfg, f"🔎 تمام، دا أبحث عن: «{topic[:200]}»\nالمسودة مع البوستر توصلك هنا خلال 5 إلى 15 دقيقة.")


def say_back(cfg, text):
    say(cfg, text)
    return text


@bp.route("/webhook/<key>", methods=["POST"])
def webhook(key):
    cfg0 = _load(CFG, {})
    if not cfg0.get("hook_key") or not secrets.compare_digest(key, cfg0["hook_key"]) \
            or request.headers.get("X-Telegram-Bot-Api-Secret-Token") != cfg0["hook_key"]:
        abort(403)
    upd = request.get_json(silent=True) or {}
    with state() as (cfg, posts):
        owner = str(cfg.get("chat_id", DEFAULT_CHAT))
        if "callback_query" in upd and str(upd["callback_query"]["from"]["id"]) == owner:
            on_callback(cfg, posts, upd["callback_query"])
        elif "message" in upd and str(upd["message"]["chat"]["id"]) == owner:
            on_message(cfg, posts, upd["message"])
    tick()  # every interaction also moves the queue along
    return "ok"


LOG = os.path.join(DIR, "log.json")


@bp.route("/ping", methods=["POST"])
def ping():
    """Unauthenticated progress log for the content routine (no secrets needed to report).

    Keeps the last 100 lines; a stage of "error" is also forwarded to Telegram, at most 8 a day.
    """
    f = request.form
    line = {"at": now().isoformat(timespec="seconds"), "run": f.get("run", "")[:40],
            "stage": f.get("stage", "")[:40], "msg": f.get("msg", "")[:500]}
    with state() as (cfg, _):
        log = _load(LOG, [])[-99:] + [line]
        _save(LOG, log)
        day = f"{now():%Y-%m-%d}"
        sent = cfg.get("err_alerts", {}).get(day, 0)
        if line["stage"] == "error" and sent < 8:
            cfg["err_alerts"] = {day: sent + 1}
            say(cfg, f"⚠️ الوكيل ({line['run']}) فشل: {line['msg']}")
    return "ok"


@bp.route("/tick")
def tick_route():
    return tick()


# ---------- admin page ----------

def _admin():
    from app import check_csrf, login_required
    return check_csrf, login_required


check_csrf, login_required = _admin()


def connect(token, chat_id=None):
    """Store the bot token and point Telegram's webhook at this site."""
    with state() as (cfg, _):
        cfg["token"] = token.strip()
        if chat_id:
            cfg["chat_id"] = str(chat_id)
        cfg.setdefault("hook_key", secrets.token_urlsafe(24))
        me = tg(cfg, "getMe")
        if not me.get("ok"):
            cfg.pop("token")
            return me
        cfg["bot"] = me["result"].get("username")
        url = request.host_url.replace("http://", "https://") + "viraliq/webhook/" + cfg["hook_key"]
        return tg(cfg, "setWebhook", url=url, secret_token=cfg["hook_key"],
                  allowed_updates=["message", "callback_query"])


@bp.route("/", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        check_csrf()
        f = request.form
        if f.get("token"):
            r = connect(f["token"], f.get("chat_id"))
            flash("✅ البوت مربوط" if r.get("ok") else f"فشل الربط: {r.get('description')}")
        else:
            with state() as (cfg, _):
                cfg["chat_id"] = f.get("chat_id", "").strip() or DEFAULT_CHAT
                cfg["channel"] = f.get("channel", "").strip()
                cfg["fb_page"] = f.get("fb_page", "").strip()
                cfg["fb_off"] = bool(f.get("fb_off"))
                if f.get("fb_token"):
                    cfg["fb_token"] = f["fb_token"].strip()
                cfg["fire_url"] = f.get("fire_url", "").strip()
                if f.get("fire_token"):
                    cfg["fire_token"] = f["fire_token"].strip()
            flash("انحفظت الإعدادات")
        return redirect(url_for("viraliq.dashboard"))
    rep = tick()
    cfg, posts = _load(CFG, {}), _load(POSTS, [])
    return render_template("viraliq/dashboard.html", cfg=cfg, posts=list(reversed(posts))[:60],
                           log=list(reversed(_load(LOG, [])))[:20],
                           rep=rep, fmt=fmt, status_line=status_line, default_chat=DEFAULT_CHAT,
                           fb=fb_target(cfg)[0])


@bp.route("/request", methods=["POST"])
@login_required
def request_from_site():
    check_csrf()
    with state() as (cfg, _):
        msg = request_post(cfg, request.form.get("topic", ""), auto=bool(request.form.get("auto")))
    flash(msg)
    return redirect(url_for("viraliq.dashboard"))


@bp.route("/img/<int:pid>.png")
@login_required
def image(pid):
    return send_file(os.path.join(IMG, f"{pid}.png"), mimetype="image/png")
