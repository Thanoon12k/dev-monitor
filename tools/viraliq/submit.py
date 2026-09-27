"""Hand drafts from a Claude session to the hub on PythonAnywhere.

    python tools/viraliq/submit.py history          # recent titles + next course day
    python tools/viraliq/submit.py send drafts.json  # render posters, upload, notify
    python tools/viraliq/submit.py connect           # store $viraliq_tele_bot_token on the hub + set webhook

drafts.json: [{"kind", "title", "text", "hashtags": [...], "suggested_at": "YYYY-MM-DD HH:MM" (Baghdad),
               "sources": [...], "poster": {"badge", "title", "hook", "points": [...]}}]
Needs $apps1monitor_PA_TOKEN.
"""
import json
import os
import secrets
import sys
import tempfile
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

USER = "apps1monitor"
SITE = f"https://{USER}.pythonanywhere.com"
API = f"https://www.pythonanywhere.com/api/v0/user/{USER}/files/path/home/{USER}/hub/data/viraliq/"
H = {"Authorization": "Token " + os.environ.get("apps1monitor_PA_TOKEN", "")}


def get_json(name, default):
    r = requests.get(API + name, headers=H, timeout=30)
    return r.json() if r.ok else default


def upload(name, data):
    r = requests.post(API + name, headers=H, files={"content": (os.path.basename(name), data)}, timeout=60)
    r.raise_for_status()


def history():
    posts = get_json("posts.json", [])
    course_days = sum(1 for p in posts if p.get("kind") == "course" and p.get("status") != "cancelled")
    print(f"posts: {len(posts)} · next course day: {course_days + 1}")
    for p in posts[-40:]:
        print(f"#{p['id']} [{p.get('kind')}] {p['status']:<9} {p['created'][:10]} {p['title']}")


def send(path):
    from poster import render
    with open(path, encoding="utf-8") as f:
        drafts = json.load(f)
    stamp = time.strftime("%Y%m%d%H%M%S")
    for i, d in enumerate(drafts):
        spec = dict(d.get("poster") or {}, kind=d.get("kind", "trend"))
        spec.setdefault("title", d["title"])
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            render(spec, tmp.name)
            name = f"inbox/{stamp}-{i}"
            upload(name + ".png", open(tmp.name, "rb").read())  # image first: the hub waits for it
        meta = {k: d.get(k) for k in ("kind", "title", "text", "hashtags", "suggested_at", "sources")}
        upload(name + ".json", json.dumps(meta, ensure_ascii=False).encode())
        print("uploaded", name, d["title"])
    print("tick:", requests.get(SITE + "/viraliq/tick", timeout=120).text)


def connect():
    token = os.environ["viraliq_tele_bot_token"].strip()
    cfg = get_json("config.json", {})
    cfg.update(token=token, chat_id=cfg.get("chat_id") or os.environ.get("viraliq_tele_bot_userid", "647908098"))
    cfg.setdefault("hook_key", secrets.token_urlsafe(24))
    tg = f"https://api.telegram.org/bot{token}/"
    cfg["bot"] = requests.get(tg + "getMe", timeout=30).json()["result"]["username"]
    upload("config.json", json.dumps(cfg, ensure_ascii=False, indent=1).encode())
    print(requests.post(tg + "setWebhook", timeout=30, data={
        "url": f"{SITE}/viraliq/webhook/{cfg['hook_key']}", "secret_token": cfg["hook_key"],
        "allowed_updates": json.dumps(["message", "callback_query"])}).json())
    print("tick:", requests.get(SITE + "/viraliq/tick", timeout=120).text)


if __name__ == "__main__":
    {"history": history, "send": lambda: send(sys.argv[2]), "connect": connect}[sys.argv[1]]()
