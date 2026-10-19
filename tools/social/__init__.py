"""مدير المنصات · Social: one post, published to every platform.

Write once (text, photo, video or music) from this page or from its Telegram bot; it is adapted
per platform and published one platform after another to LinkedIn, a Facebook Page, Instagram,
TikTok, YouTube, a Telegram channel, the built-in blog (/social/blog) and optionally WordPress, with each
result reported on Telegram. The core lives in tools/social/spm (same code as the
Social-Platforms-Manager repo); its data sits in data/social/.
Scheduled posts go out from /social/tick (called by the viraliq-tick workflow); "publish now"
goes out right after the response.
"""
import os
import secrets
import time
from datetime import datetime
from email.utils import format_datetime
from functools import wraps

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SPM_DATA"] = os.environ.get("SPM_DATA") or os.path.join(BASE, "data", "social")

from .spm import adapt, bot, engine, platforms, store  # noqa: E402
from .spm.platforms import facebook, linkedin, tiktok, youtube  # noqa: E402
from .spm.platforms.telegram import tg  # noqa: E402

bp = Blueprint("social", __name__, template_folder="../../templates")


def _admin():
    from app import check_csrf, login_required
    return check_csrf, login_required


check_csrf, login_required = _admin()


def admin(f):
    """The hub's PIN check, then remember the public address of this tool."""
    @wraps(f)
    def w(*a, **k):
        remember_base_url()
        return f(*a, **k)
    return login_required(w)


def remember_base_url():
    """https://<site>/social: the root for media links, the webhook and OAuth redirects."""
    url = url_for("social.dashboard", _external=True).rstrip("/")
    if url.startswith("http://") and "localhost" not in url and "127.0.0.1" not in url:
        url = "https://" + url[7:]
    s = store.load(store.CFG, {}).get("settings", {})
    if not s.get("base_url_fixed") and s.get("base_url") != url:
        store.patch("settings", base_url=url)


@bp.context_processor
def inject():
    return {"label": platforms.label, "fmt": store.fmt, "STATUS": engine.STATUS, "KIND": engine.KIND,
            "ts": lambda t: datetime.fromtimestamp(t, store.tz()).strftime("%Y-%m-%d"),
            "rfc822": lambda iso: format_datetime(datetime.fromisoformat(iso))}


def publish_after(resp):
    """Publish right after the response is sent, so the browser does not wait for uploads."""
    resp.call_on_close(engine.run_due)
    return resp


# ---------- dashboard ----------

@bp.route("/")
@admin
def dashboard():
    cfg, posts = store.read()
    counts = {k: sum(1 for p in posts if p["status"] == k) for k in engine.STATUS}
    sent = sum(1 for p in posts for r in p["results"].values() if r.get("ok"))
    return render_template("social/dashboard.html", cfg=cfg, posts=list(reversed(posts))[:40], counts=counts,
                           sent=sent, connected=platforms.connected(cfg), order=platforms.ORDER,
                           ai=bool(adapt.provider(cfg)), log=list(reversed(store.load(store.LOG, [])))[:12],
                           now=store.now())


def tmp_upload(f):
    tmp = os.path.join(store.MEDIA, "tmp")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, secrets.token_hex(8))
    f.save(path)
    return path


@bp.route("/compose", methods=["POST"])
@admin
def compose():
    check_csrf()
    f = request.form
    up = request.files.get("file")
    path = tmp_upload(up) if up and up.filename else None
    try:
        p = engine.create(text=f.get("text", ""), title=f.get("title", ""), link=f.get("link", ""), file_path=path,
                          filename=secure_filename(up.filename) if path else "", mime=up.mimetype if path else "",
                          targets=f.getlist("targets"), use_ai=bool(f.get("ai")))
    except ValueError as e:
        if path and os.path.exists(path):
            os.remove(path)
        flash(str(e))
        return redirect(url_for("social.dashboard"))
    return post_action(p["id"], f.get("action", "draft"))


def post_action(pid, action):
    back = redirect(url_for("social.post_page", pid=pid))
    if action == "publish":
        flash("🚀 بدأ النشر. الصفحة تتحدث وحدها، والنتيجة توصلك على تيليجرام." if engine.schedule(pid)
              else "ما ينفع أنشره: اختار منصة وحدة على الأقل")
        return publish_after(back)
    if action == "schedule":
        when = store.parse_time(request.form.get("when", ""))
        if not when:
            flash("اكتب وقت النشر")
        elif engine.schedule(pid, when):
            flash(f"🕒 مجدول: {store.fmt(when.isoformat())}")
        else:
            flash("ما ينفع أجدوله")
        return publish_after(back)
    return back


@bp.route("/post/<int:pid>", methods=["GET", "POST"])
@admin
def post_page(pid):
    p = store.get_post(pid)
    if not p:
        abort(404)
    if request.method == "POST":
        check_csrf()
        f, action = request.form, request.form.get("action", "save")
        if action in ("save", "publish", "schedule") and p["status"] not in ("publishing", "done"):
            variants = dict(p["variants"])
            for k in platforms.BY_KEY:
                if f"v_{k}" in f:
                    variants[k] = dict(variants.get(k) or {}, text=f[f"v_{k}"])
                if f"t_{k}" in f:
                    variants.setdefault(k, {})["title"] = f[f"t_{k}"]
            engine.update(pid, variants=variants, targets=engine.ordered(f.getlist("targets")))
            if action == "save":
                flash("انحفظ")
                return redirect(url_for("social.post_page", pid=pid))
            return post_action(pid, action)
        if action == "readapt":
            engine.update(pid, text=f.get("text", p["text"]), title=f.get("title", p.get("title", "")),
                          link=f.get("link", p.get("link", "")))
            engine.readapt(pid, use_ai=bool(f.get("ai")))
            flash("انعادت الصياغة لكل منصة")
        elif action == "retry":
            flash("🔁 دا أعيد النشر للفاشلة" if engine.retry(pid) else "ما كو شي أعيده")
            return publish_after(redirect(url_for("social.post_page", pid=pid)))
        elif action == "cancel":
            flash("🚫 انلغى" if engine.cancel(pid) else "ما ينفع ألغيه")
        elif action == "delete":
            if engine.delete(pid):
                flash(f"انحذف #{pid}")
                return redirect(url_for("social.dashboard"))
            flash("ما ينفع أحذفه أثناء النشر")
        return redirect(url_for("social.post_page", pid=pid))
    cfg = store.load(store.CFG, {})
    variants = {k: p["variants"].get(k) or adapt.rules(p)[k] for k in platforms.BY_KEY}
    f = (p.get("media") or {}).get("file")
    return render_template("social/post.html", p=p, cfg=cfg, variants=variants, order=platforms.ORDER,
                           connected=platforms.connected(cfg), ai=bool(adapt.provider(cfg)),
                           ordered=engine.ordered(p["targets"]), limits=adapt.LIMITS,
                           media_url=url_for("social.public_media", pid=pid, token=p["token"], name=f) if f else None)


@bp.route("/log")
@admin
def log_page():
    return render_template("social/log.html", log=list(reversed(store.load(store.LOG, []))))


# ---------- accounts ----------

def keep(sec, f, *names):
    """Copy the non-empty form fields into a config section (empty secret fields keep the old value)."""
    for n in names:
        v = f.get(n, "").strip()
        if v:
            sec[n] = v


@bp.route("/accounts", methods=["GET", "POST"])
@admin
def accounts():
    if request.method == "POST":
        check_csrf()
        save_account(request.form)
        return redirect(url_for("social.accounts") + "#" + request.form.get("section", ""))
    cfg = store.load(store.CFG, {})
    checks = platforms.check_all(cfg) if request.args.get("check") else {}
    t = cfg.get("telegram", {})
    claim_link = f"https://t.me/{t['bot']}?start={t['claim']}" if t.get("bot") and t.get("claim") else ""
    return render_template("social/accounts.html", cfg=cfg, checks=checks, base=cfg.get("settings", {}).get("base_url", ""),
                           order=platforms.ORDER, claim_link=claim_link, connected=platforms.connected(cfg))


def telegram_connect(cfg, f):
    t = store.section(cfg, "telegram")
    keep(t, f, "token")
    t["channel"] = f.get("channel", "").strip()
    if not t.get("token"):
        return "حط توكن البوت من @BotFather"
    me = tg(t["token"], "getMe")
    if not me.get("ok"):
        return f"التوكن غلط: {me.get('description')}"
    t["bot"] = me["result"].get("username")
    t.setdefault("hook_key", secrets.token_urlsafe(24))
    if not t.get("owner"):
        t["claim"] = t.get("claim") or secrets.token_urlsafe(9)
    url = cfg["settings"].get("base_url", "") + "/tg/" + t["hook_key"]
    r = tg(t["token"], "setWebhook", url=url, secret_token=t["hook_key"],
           allowed_updates=["message", "callback_query"], drop_pending_updates=True)
    if not r.get("ok"):
        return f"البوت انربط بس الـ webhook فشل: {r.get('description')}"
    return "✅ البوت مربوط @" + t["bot"]


def save_account(f):
    s = f.get("section")
    with store.state() as (cfg, _):
        store.settings(cfg)
        if s == "telegram":
            if f.get("unlink_owner"):
                store.section(cfg, "telegram").update(owner=None, claim=secrets.token_urlsafe(9))
                flash("انفك ربط صاحب البوت. افتح رابط الربط الجديد من تيليجرامك.")
            else:
                flash(telegram_connect(cfg, f))
        elif s == "facebook":
            fb = store.section(cfg, "facebook")
            keep(fb, f, "app_id", "app_secret")
            if f.get("disconnect"):
                for k in ("page_id", "page_token", "ig_id", "ig_username", "page_name"):
                    fb.pop(k, None)
                flash("انفك ربط فيسبوك وإنستغرام")
            elif f.get("user_token"):
                fields, err = facebook.connect(f["user_token"], fb.get("app_id", ""), fb.get("app_secret", ""),
                                               f.get("page_id", ""))
                if err:
                    flash(f"فشل ربط فيسبوك: {err}")
                else:
                    fb.update(fields)
                    ig = f" وإنستغرام @{fields['ig_username']}" if fields.get("ig_id") else \
                        " (ما لكيت حساب إنستغرام احترافي مربوط بالصفحة)"
                    flash(f"✅ انربطت صفحة {fields['page_name']}{ig}")
        elif s == "linkedin":
            li = store.section(cfg, "linkedin")
            keep(li, f, "client_id", "client_secret")
            li["author"] = f.get("author", "").strip() or li.get("member", "")
            li["version"] = f.get("version", "").strip()
            if f.get("token"):
                li["token"] = f["token"].strip()
                li.pop("expires", None)
            if f.get("disconnect"):
                for k in ("token", "expires", "member", "name"):
                    li.pop(k, None)
            flash("انحفظ لينكدإن")
        elif s == "tiktok":
            tk = store.section(cfg, "tiktok")
            keep(tk, f, "client_key", "client_secret")
            tk["mode"] = f.get("mode", "direct")
            tk["privacy"] = f.get("privacy", "PUBLIC_TO_EVERYONE")
            if f.get("disconnect"):
                for k in ("token", "refresh", "expires", "refresh_expires", "open_id", "name", "username"):
                    tk.pop(k, None)
            flash("انحفظ تيك توك")
        elif s == "youtube":
            yt = store.section(cfg, "youtube")
            keep(yt, f, "client_id", "client_secret")
            yt["privacy"] = f.get("privacy", "public")
            if f.get("disconnect"):
                for k in ("token", "refresh", "expires", "channel_id", "name"):
                    yt.pop(k, None)
            flash("انحفظ يوتيوب")
        elif s == "wordpress":
            w = store.section(cfg, "wordpress")
            w["url"], w["user"] = f.get("url", "").strip(), f.get("user", "").strip()
            keep(w, f, "app_password")
            if f.get("disconnect"):
                cfg["wordpress"] = {}
            flash("انحفظ ووردبريس")
        elif s == "blog":
            b = store.section(cfg, "blog")
            b.update(title=f.get("title", "").strip() or "المدونة", about=f.get("about", "").strip(),
                     off=bool(f.get("off")))
            flash("انحفظت المدونة")
        elif s == "ai":
            a = store.section(cfg, "ai")
            keep(a, f, "groq_key", "gemini_key")
            a["model"] = f.get("model", "").strip()
            a["default"] = bool(f.get("default"))
            if f.get("clear"):
                cfg["ai"] = {}
            flash("انحفظ الذكاء الاصطناعي")
        elif s == "settings":
            st = cfg["settings"]
            st["brand"] = f.get("brand", "").strip()
            try:
                st["tz_hours"] = float(f.get("tz_hours", "3"))
            except ValueError:
                pass
            if f.get("base_url", "").strip():
                st["base_url"], st["base_url_fixed"] = f["base_url"].strip().rstrip("/"), True
            else:
                st["base_url_fixed"] = False
            flash("انحفظت الإعدادات")


# ---------- OAuth (LinkedIn, TikTok) ----------

OAUTH = {"linkedin": (linkedin, "client_id"), "tiktok": (tiktok, "client_key"), "youtube": (youtube, "client_id")}


def redirect_uri(name):
    return store.load(store.CFG, {})["settings"]["base_url"] + f"/oauth/{name}/callback"


@bp.route("/oauth/<name>/start")
@admin
def oauth_start(name):
    if name not in OAUTH:
        abort(404)
    mod, id_field = OAUTH[name]
    cfg = store.load(store.CFG, {})
    if not cfg.get(name, {}).get(id_field) or not cfg[name].get("client_secret"):
        flash("حط بيانات التطبيق (ID و Secret) واحفظها أول")
        return redirect(url_for("social.accounts") + "#" + name)
    session["oauth_state"] = secrets.token_urlsafe(18)
    return redirect(mod.auth_url(cfg, redirect_uri(name), session["oauth_state"]))


@bp.route("/oauth/<name>/callback")
@admin
def oauth_callback(name):
    if name not in OAUTH:
        abort(404)
    if not request.args.get("state") or request.args.get("state") != session.pop("oauth_state", None):
        abort(400)
    back = redirect(url_for("social.accounts") + "#" + name)
    if request.args.get("error"):
        flash(f"الربط انلغى: {request.args.get('error_description') or request.args['error']}")
        return back
    mod = OAUTH[name][0]
    try:
        fields = mod.finish_auth(store.load(store.CFG, {}), request.args.get("code", ""), redirect_uri(name))
    except Exception as e:  # noqa: BLE001
        flash(f"فشل الربط: {e}")
        return back
    store.patch(name, **fields)
    flash(f"✅ انربط {mod.NAME}: {fields.get('name', '')}")
    return back


# ---------- machine endpoints ----------

@bp.route("/tg/<key>", methods=["POST"])
def telegram_webhook(key):
    t = store.load(store.CFG, {}).get("telegram", {})
    if not t.get("hook_key") or not secrets.compare_digest(key, t["hook_key"]) \
            or request.headers.get("X-Telegram-Bot-Api-Secret-Token") != t["hook_key"]:
        abort(403)
    bot.handle(request.get_json(silent=True) or {})
    return publish_after(Response("ok"))


@bp.route("/tick")
def tick():
    """Publishes scheduled posts (idempotent, like /viraliq/tick); called by the viraliq-tick workflow."""
    tmp = os.path.join(store.MEDIA, "tmp")
    for n in os.listdir(tmp) if os.path.isdir(tmp) else []:
        if time.time() - os.path.getmtime(os.path.join(tmp, n)) > 86400:
            os.remove(os.path.join(tmp, n))
    return engine.run_due()


@bp.route("/m/<int:pid>/<token>/<name>")
def public_media(pid, token, name):
    """Media for Instagram/TikTok to download and for the blog; the per-post token keeps drafts private."""
    p = store.get_post(pid)
    if not p or not secrets.compare_digest(token, p["token"]) or name != secure_filename(name):
        abort(404)
    path = os.path.join(store.MEDIA, str(pid), name)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, conditional=True)


# ---------- public blog ----------

def blog_cfg():
    return store.load(store.CFG, {}).get("blog", {})


@bp.route("/blog")
def blog_index():
    return render_template("social/blog_index.html", entries=list(reversed(store.load(store.BLOG, []))), blog=blog_cfg())


@bp.route("/blog/<slug>")
def blog_post(slug):
    e = next((e for e in store.load(store.BLOG, []) if e["slug"] == slug), None)
    if not e:
        abort(404)
    return render_template("social/blog_post.html", e=e, blog=blog_cfg())


@bp.route("/blog/feed.xml")
def blog_feed():
    base = store.load(store.CFG, {}).get("settings", {}).get("base_url", "")
    xml = render_template("social/feed.xml", entries=list(reversed(store.load(store.BLOG, [])))[:30], blog=blog_cfg(),
                          base=base)
    return Response(xml, mimetype="application/rss+xml")
