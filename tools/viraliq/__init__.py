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
        return {"ok": False, "description": str(e).replace(cfg["token"], "<token>")}


def keyboard(pid, p=None):
    rows = [
        [{"text": "✅ جدولة بالوقت المقترح", "callback_data": f"ok:{pid}"}, {"text": "🚀 انشر الآن", "callback_data": f"now:{pid}"}],
        [{"text": "🕒 وقت ثاني", "callback_data": f"time:{pid}"}, {"text": "✏️ تعديل النص", "callback_data": f"edit:{pid}"}],
        [{"text": "💬 تعليق أول", "callback_data": f"comment:{pid}"}, {"text": "📋 أنشره بنفسي", "callback_data": f"self:{pid}"}],
    ]
    if p and p.get("user_photo"):
        rows.append([{"text": "🖼 استخدم صورتي" if not p.get("use_user_photo") else "🎨 رجّع البوستر",
                      "callback_data": f"photo:{pid}"}])
    rows.append([{"text": "❌ إلغاء", "callback_data": f"no:{pid}"}])
    return {"inline_keyboard": rows}


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
        "manual": "📋 تنشره بنفسك",
    }[p["status"]]


def post_image(p):
    """The image that gets published: the owner's own photo when chosen, else the card."""
    if p.get("use_user_photo") and p.get("user_photo"):
        return os.path.join(IMG, p["user_photo"])
    return os.path.join(IMG, p["image"])


def preview_body(p):
    src = "\n".join(f"🔗 {u}" for u in p.get("sources", [])[:3])
    com = f"\n\n💬 التعليق الأول:\n{p['comment']}" if p.get("comment") else ""
    return (f"{full_text(p)}{com}\n\n━━━━━━━━\n{status_line(p)}" + (f"\n\nالمصادر:\n{src}" if src else ""))[:4096]


def send_preview(cfg, p):
    """Poster (with short caption) followed by the full post text + buttons."""
    chat = cfg.get("chat_id", DEFAULT_CHAT)
    with open(post_image(p), "rb") as f:
        r = tg(cfg, "sendPhoto", files={"photo": f}, chat_id=chat,
               caption=f"🆕 منشور #{p['id']} · {p.get('kind', '')}\n{p['title']}")
    if not r.get("ok"):
        p["tg_err"] = f"sendPhoto: {r.get('description')}"
        return False
    r2 = tg(cfg, "sendMessage", chat_id=chat, text=preview_body(p), reply_markup=keyboard(p["id"], p),
            disable_web_page_preview=True)
    p["tg_msg"] = r2.get("result", {}).get("message_id")
    if not r2.get("ok"):
        p["tg_err"] = f"sendMessage: {r2.get('description')}"
    return r2.get("ok", False)


def refresh(cfg, p, extra=""):
    """Rewrite the preview message's status line; keep buttons while it is still actionable."""
    if not p.get("tg_msg"):
        return
    body = preview_body(p) + (f"\n{extra}" if extra else "")
    kb = keyboard(p["id"], p) if p["status"] in ("pending", "approved") else {"inline_keyboard": []}
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
        with open(post_image(p), "rb") as f:
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


def fb_comment(token, obj_id, message):
    try:
        r = requests.post(GRAPH + obj_id + "/comments", timeout=30,
                          data={"message": message, "access_token": token}).json()
    except (requests.RequestException, ValueError) as e:
        r = {"error": {"message": str(e)}}
    return "✅" if r.get("id") else f"❌ {r.get('error', {}).get('message')}"


def publish(cfg, p):
    text, img, done = full_text(p), post_image(p), []
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
        if p.get("comment") and token:
            done.append("التعليق الأول: " + fb_comment(token, p["fb_sched"], p["comment"]))
    elif page:
        try:
            with open(img, "rb") as f:
                r = requests.post(GRAPH + page + "/photos", files={"source": f}, timeout=60,
                                  data={"caption": text, "access_token": token}).json()
        except (requests.RequestException, ValueError) as e:
            r = {"error": {"message": str(e)}}
        done.append("فيسبوك: " + ("✅" if r.get("id") else f"❌ {r.get('error', {}).get('message')}"))
        if r.get("id") and p.get("comment"):
            done.append("التعليق الأول: " + fb_comment(token, r["id"], p["comment"]))
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
                          "sources": d.get("sources", []), "comment": d.get("comment") or "",
                          "image": f"{pid}.png", "status": "pending",
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
    elif action == "now":
        fb_unschedule(cfg, p)
        p["status"], p["scheduled_at"] = "approved", now().isoformat()
        publish(cfg, p)
    elif action == "self":
        hand_over(cfg, p)
    elif action == "comment":
        cfg["await"] = {"kind": "comment", "id": pid}
        say(cfg, f"💬 اكتب التعليق الأول لمنشور #{pid} (ينزل تحت المنشور أول ما ينتشر).\nلحذفه اكتب: لا\nللتراجع: /skip",
            reply_markup={"force_reply": True})
    elif action == "photo":
        p["use_user_photo"] = not p.get("use_user_photo")
        fb_unschedule(cfg, p)
        if p.get("tg_msg"):
            tg(cfg, "editMessageReplyMarkup", chat_id=cfg.get("chat_id", DEFAULT_CHAT), message_id=p["tg_msg"],
               reply_markup={"inline_keyboard": []})
        p["tg_msg"] = None
        send_preview(cfg, p)
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


def hand_over(cfg, p):
    """Owner posts it by hand: send the image as a file plus the texts, ready to copy."""
    fb_unschedule(cfg, p)
    chat = cfg.get("chat_id", DEFAULT_CHAT)
    with open(post_image(p), "rb") as f:
        tg(cfg, "sendDocument", files={"document": (f"golden-code-{p['id']}.png", f)}, chat_id=chat,
           caption=f"📋 منشور #{p['id']} جاهز تنشره بنفسك: الصورة بجودة كاملة، والنص بالرسالة الجاية")
    say(cfg, full_text(p)[:4096])
    if p.get("comment"):
        say(cfg, "💬 التعليق الأول (انسخه وحطه تحت المنشور):\n\n" + p["comment"])
    p["status"] = "manual"
    refresh(cfg, p)


def set_time(cfg, p, t):
    fb_unschedule(cfg, p)
    p["scheduled_at"], p["status"] = t.isoformat(), "approved"
    refresh(cfg, p)
    say(cfg, f"✅ #{p['id']} راح ينتشر {fmt(p['scheduled_at'])}")


BULLET = re.compile(r"^\s*(?:[-•*▪◦●✅✔☑🔹🔸👉]|(?:\d+|[٠-٩]+)\s*[.)\-:،]|\((?:\d+|[٠-٩]+)\))\s*")
COMMENT = re.compile(r"^\s*(?:💬\s*)?(?:التعليق الأول|تعليق أول|تعليق|comment)\s*[:：]\s*", re.I)
LABEL = re.compile(r"^\s*(?:العنوان|عنوان|title)\s*[:：]\s*", re.I)


def parse_compose(text):
    """Owner's message -> card fields + a simple post text.

    Line 1 is the title ("|" splits it into two lines), the next plain line is the subtitle,
    bulleted or numbered lines are the 3-5 outlines, a "تعليق:" line starts the first comment,
    and any other plain lines are the post's own text.
    """
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    comment, body_lines = [], []
    for i, ln in enumerate(lines):
        if COMMENT.match(ln):
            comment = [COMMENT.sub("", ln)] + lines[i + 1:]
            lines = lines[:i]
            break
    plain = [ln for ln in lines if ln.strip()]
    title = LABEL.sub("", plain[0]).strip() if plain else ""
    sub, points = "", []
    for ln in plain[1:]:
        if BULLET.match(ln):
            points.append(BULLET.sub("", ln).strip())
        elif not sub and not points and len(ln) <= 110:
            sub = ln.strip()
        else:
            body_lines.append(ln.strip())
    if not points:  # no bullets: short body lines/sentences become the outlines
        pool = [x.strip().rstrip(".") for ln in body_lines for x in re.split(r"(?<=[.!؟?])\s+", ln) if x.strip()]
        points = [x for x in pool if len(x) <= 60][:5]
    points = [x[:70] for x in points[:5]]
    title_flat = re.sub(r"\s*\|\s*", " ", title).strip()
    if body_lines:  # the owner wrote their own post text: keep it as is
        post = "\n".join([title_flat] + ([sub] if sub else []) + [""] + body_lines)
        if points and not any(pt in post for pt in points):
            post += "\n\n" + "\n".join(f"• {pt}" for pt in points)
    else:  # build a short, plain post from the card
        post = title_flat + (f"\n{sub}" if sub else "") + "\n\n" + "\n".join(f"• {pt}" for pt in points)
        post += "\n\nشنو رأيك؟ اكتبلنا بالتعليقات 👇" if "؟" in title or "?" in title else "\n\nاحفظه حتى ترجعله 🔖"
    kind = "debate" if ("؟" in title or "?" in title) else "tip"
    return {"kind": kind, "title": title, "sub": sub, "points": points,
            "text": post.strip(), "comment": "\n".join(comment).strip()}


def next_slot():
    n = now()
    for h, m in ((12, 30), (16, 0), (21, 30)):
        t = n.replace(hour=h, minute=m, second=0, microsecond=0)
        if t > n + timedelta(minutes=30):
            return t
    return (n + timedelta(days=1)).replace(hour=12, minute=30, second=0, microsecond=0)


def download_photo(cfg, msg):
    f = tg(cfg, "getFile", file_id=msg["photo"][-1]["file_id"]).get("result", {})
    if not f.get("file_path"):
        return None
    try:
        return requests.get(f"https://api.telegram.org/file/bot{cfg['token']}/{f['file_path']}", timeout=60).content
    except requests.RequestException:
        return None


def compose(cfg, posts, msg, text):
    """Build a card + post from the owner's message and send it back with the action buttons."""
    from .poster import render
    if not text:
        say(cfg, "📷 وصلت الصورة. ارسلها مرة ثانية ويا نص (عنوان ونقاط) حتى أسوي منها منشور.")
        return
    d = parse_compose(text)
    if len(d["points"]) < 3:
        say(cfg, "✍️ أحتاج على الأقل 3 نقاط حتى أسوي البوستر. مثال:\n\n"
                 "5 أسئلة | قبل التسليم\nاسألهن لأي مبرمج قبل ما تنطيه مشروعك\n"
                 "- وريني شغل سابق يشبه مشروعي\n- الكود راح يكون مالي؟\n- شنو اللي ما راح يشمله السعر؟\n"
                 "تعليق: انت شنو تسأل قبل ما تدفع؟")
        return
    pid = max([p["id"] for p in posts] + [0]) + 1
    render({"kind": d["kind"], "title": d["title"], "sub": d["sub"], "points": d["points"]},
           os.path.join(IMG, f"{pid}.png"))
    p = {"id": pid, "kind": d["kind"], "title": re.sub(r"\s*\|\s*", " ", d["title"]), "text": d["text"], "hashtags": [],
         "comment": d["comment"], "sources": [], "image": f"{pid}.png", "status": "pending",
         "suggested_at": next_slot().isoformat(), "created": now().isoformat(), "tg_msg": None, "own": True}
    if msg.get("photo"):
        data = download_photo(cfg, msg)
        if data:
            p["user_photo"] = f"{pid}-own.jpg"
            with open(os.path.join(IMG, p["user_photo"]), "wb") as out:
                out.write(data)
    posts.append(p)
    send_preview(cfg, p)


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
                     "✍️ تريد تسوي منشور بنفسك؟ ارسلي رسالة (ويا صورة إذا تحب) بهالشكل:\n"
                     "السطر الأول = العنوان (تكدر تقسمه لسطرين بـ |)\n"
                     "السطر الثاني = جملة قصيرة تحت العنوان\n"
                     "بعدها 3 إلى 5 نقاط، كل نقطة تبدي بـ - أو رقم\n"
                     "وإذا تريد تعليق أول: سطر يبدي بـ «تعليق:»\n"
                     "وأني أسوي البوستر والنص، وانت تختار: تنشره هسه، تجدوله، أو تنشره بنفسك.\n\n"
                     "🤖 /post الموضوع: ينضاف للطابور ويوصلك منشور كامل عنه ويا أقرب دفعة كتابة.\n"
                     "🚀 /postnow الموضوع: نفسه بس ينتشر مباشرة من يجهز.\n\n"
                     "/queue المنشورات المنتظرة\n/channel @اسم_القناة لتحديد قناة النشر التلقائي\n"
                     f"معرّف المحادثة: {msg['chat']['id']}")
        return
    p = find(posts, wait.get("id", 0))
    if not p:  # free text (or a photo with a caption) outside an edit = compose a new post from it
        compose(cfg, posts, msg, text)
        return
    if wait["kind"] == "comment":
        cfg.pop("await", None)
        p["comment"] = "" if text in ("لا", "حذف", "-") else text
        fb_unschedule(cfg, p)  # a scheduled Facebook post is recreated on the next tick
        refresh(cfg, p)
        say(cfg, "💬 انحفظ التعليق الأول." if p["comment"] else "انحذف التعليق الأول.")
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
            data = download_photo(cfg, msg)
            if data:
                with open(os.path.join(IMG, p["image"]), "wb") as out:
                    out.write(data)
                p["use_user_photo"] = False
        if text:  # the new text is the whole post, hashtags included
            p["text"], p["hashtags"] = text, []
        fb_unschedule(cfg, p)  # rescheduled with the new content on the next tick
        if p.get("tg_msg"):
            tg(cfg, "editMessageReplyMarkup", chat_id=cfg.get("chat_id", DEFAULT_CHAT), message_id=p["tg_msg"],
               reply_markup={"inline_keyboard": []})
        p["tg_msg"] = None
        send_preview(cfg, p)


MAX_REQUESTS_PER_DAY = 6


def request_post(cfg, topic, auto=False):
    """Queue `topic` for the content agent (GitHub Actions + GitHub Models, polls every 15 min).

    With auto=True the finished post skips approval and is published as soon as it arrives.
    Returns the message shown to the owner (also sent on Telegram).
    """
    topic = (topic or "").strip()
    if len(topic) < 3:
        return say_back(cfg, "اكتب الموضوع اللي تريد عنه منشور، مثلاً:\n/post أفضل 5 أدوات ذكاء اصطناعي مجانية للطلاب")
    day = f"{now():%Y-%m-%d}"
    used = cfg.get("requests", {}).get(day, 0)
    if used >= MAX_REQUESTS_PER_DAY:
        return say_back(cfg, f"وصلت حد اليوم ({MAX_REQUESTS_PER_DAY} طلبات). باجر نكمل 🙏")
    rid = secrets.token_hex(3)
    cfg["requests"] = {day: used + 1}
    cfg["queue"] = (cfg.get("queue", []) + [{"id": rid, "topic": topic[:1500], "at": now().isoformat()}])[-20:]
    if auto:
        cfg["auto_reqs"] = (cfg.get("auto_reqs", []) + [rid])[-20:]
        return say_back(cfg, f"📝 انضاف للطابور: «{topic[:200]}»\n🚀 من يجهز ينتشر مباشرة بدون موافقة، ويوصلك هنا.")
    return say_back(cfg, f"📝 انضاف للطابور: «{topic[:200]}»\nالمسودة مع البوستر توصلك هنا ويا أقرب دفعة كتابة.")


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


OIDC_ISS = "https://token.actions.githubusercontent.com"
OIDC_AUD = "viraliq"
OIDC_REPO = "Thanoon12k/dev-monitor"
_jwks = {"at": 0, "keys": {}}


def _b64(s):
    import base64
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def github_oidc_ok(token):
    """True when `token` is a GitHub Actions OIDC token from this repo's main branch."""
    import time
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    try:
        h64, p64, s64 = token.split(".")
        header, claims = json.loads(_b64(h64)), json.loads(_b64(p64))
        if header.get("alg") != "RS256":
            return False
        if header.get("kid") not in _jwks["keys"] or time.time() - _jwks["at"] > 3600:
            keys = requests.get(OIDC_ISS + "/.well-known/jwks", timeout=20).json()["keys"]
            _jwks.update(at=time.time(), keys={k["kid"]: k for k in keys})
        k = _jwks["keys"][header["kid"]]
        pub = rsa.RSAPublicNumbers(int.from_bytes(_b64(k["e"]), "big"), int.from_bytes(_b64(k["n"]), "big")).public_key()
        pub.verify(_b64(s64), f"{h64}.{p64}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except Exception:  # noqa: BLE001 - any parse/verify problem means "not authorised"
        return False
    aud = claims.get("aud")
    return (claims.get("iss") == OIDC_ISS and (aud == OIDC_AUD or (isinstance(aud, list) and OIDC_AUD in aud))
            and claims.get("repository") == OIDC_REPO and claims.get("ref") == "refs/heads/main"
            and claims.get("exp", 0) > time.time())


def api_ok():
    key = _load(CFG, {}).get("api_key")
    if key and secrets.compare_digest(request.headers.get("X-Key", ""), key):
        return True
    auth = request.headers.get("Authorization", "")
    return auth.startswith("Bearer ") and github_oidc_ok(auth[7:])


@bp.route("/api/drafts", methods=["POST"])
def api_drafts():
    """Drafts straight from the routine as JSON (same shape as submit.py's drafts.json).

    The hub renders each poster itself, so the routine needs no code, only one HTTP call.
    """
    if not api_ok():
        abort(403)
    from .poster import render
    drafts = request.get_json(silent=True)
    if isinstance(drafts, dict):
        drafts = [drafts]
    if not isinstance(drafts, list) or not drafts:
        return {"ok": False, "error": "body must be a JSON list of drafts"}, 400
    stamp, names = now().strftime("%Y%m%d%H%M%S"), []
    for i, d in enumerate(drafts[:5]):
        if not d.get("title") or not d.get("text"):
            return {"ok": False, "error": f"draft {i}: title and text are required"}, 400
        spec = dict(d.get("poster") or {}, kind=d.get("kind", "trend"))
        spec.setdefault("title", d["title"])
        base = os.path.join(INBOX, f"{stamp}-api{i}")
        render(spec, base + ".png")
        meta = {k: d.get(k) for k in ("kind", "title", "text", "hashtags", "suggested_at", "sources", "request",
                                      "comment")}
        _save(base + ".json", meta)
        names.append(d["title"])
    return {"ok": True, "queued": names, "tick": tick()}


@bp.route("/api/history")
def api_history():
    if not api_ok():
        abort(403)
    posts = _load(POSTS, [])
    course = sum(1 for p in posts if p.get("kind") == "course" and p.get("status") != "cancelled")
    return {"next_course_day": course + 1, "now": now().strftime("%Y-%m-%d %H:%M"),
            "recent": [f"[{p.get('kind')}] {p['created'][:10]} {p['title']}" for p in posts[-40:]],
            "used_sources": sorted({u for p in posts if p.get("status") != "cancelled" for u in p.get("sources", [])}),
            "pending_courses": sum(1 for p in posts if p.get("kind") == "course" and p.get("status") == "pending")}


@bp.route("/api/requests", methods=["GET", "POST"])
def api_requests():
    """GET: topics the owner asked for. POST {"id": ...}: mark one as handled."""
    if not api_ok():
        abort(403)
    with state() as (cfg, _):
        if request.method == "POST":
            rid = (request.get_json(silent=True) or {}).get("id")
            cfg["queue"] = [q for q in cfg.get("queue", []) if q["id"] != rid]
        return {"queue": cfg.get("queue", [])}


@bp.route("/routine.md")
def routine_md():
    here = os.path.dirname(os.path.abspath(__file__))
    return send_file(os.path.join(here, "ROUTINE.md"), mimetype="text/plain; charset=utf-8")


@bp.route("/kit.tgz")
def kit():
    """The routine's tools (poster, submit, fonts, instructions) for sessions without a repo checkout."""
    import io
    import tarfile
    here = os.path.dirname(os.path.abspath(__file__))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        t.add(here, arcname="tools/viraliq", filter=lambda i: None if "__pycache__" in i.name else i)
    buf.seek(0)
    return send_file(buf, mimetype="application/gzip", download_name="kit.tgz")


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
