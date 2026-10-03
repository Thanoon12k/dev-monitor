"""Viraliq content agent, run by GitHub Actions (.github/workflows/viraliq-content.yml).

    python tools/viraliq/agent.py morning    # course of the day + top tech news
    python tools/viraliq/agent.py evening    # a practical tip or a debate
    python tools/viraliq/agent.py requests   # topics the owner asked for on Telegram

Writes with GitHub Models (the workflow's GITHUB_TOKEN, permission models: read) and talks to
the hub with the workflow's OIDC token (permission id-token: write), so no secrets are needed.
News comes from public RSS feeds; courses from the checked list in courses.json. The model may
only use facts from what it is given; every draft keeps its source links.
"""
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

HUB = "https://apps1monitor.pythonanywhere.com/viraliq"
MODELS = "https://models.github.ai/inference/chat/completions"
MODEL = os.environ.get("VIRALIQ_MODEL", "openai/gpt-4.1")
TZ = timezone(timedelta(hours=3))
HERE = os.path.dirname(os.path.abspath(__file__))
FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://www.engadget.com/rss.xml",
]
UA = {"User-Agent": "viraliq-agent/1.0 (+https://apps1monitor.pythonanywhere.com)"}

RULES = """You write Facebook posts for «الكود الذهبي» (Golden Code), a small tech and programming page
from Mosul, Iraq. Readers: Iraqi students, beginners and small business owners.

Write like a real person talking to a friend, not like a news agency:
- Plain Arabic with a light Iraqi touch (شلون، هسه، انت، شنو), short sentences, no hype, no long intro.
- "text": 250-600 characters. One hook line, 2-4 short lines or "•" bullets, one simple question or call
  to action at the end. At most 2 emojis. No hashtags inside the text.
- Use ONLY facts given to you in the input. Never invent numbers, names, dates or features.
- Stay away from politics, religion, sectarian topics and personal attacks.
Return JSON only, with this shape:
{"title": "short headline for the owner, <= 60 chars",
 "text": "the post",
 "hashtags": ["#الكود_الذهبي", "... 1-3 more"],
 "comment": "a short first comment for under the post (usually the link with one line), or empty",
 "poster": {"tag": "1-2 words like نصيحة / خبر / سؤال / دورة مجانية",
            "label": "short pill text, <= 18 chars",
            "title": "poster headline <= 30 chars, split into two lines with |",
            "sub": "one short line <= 60 chars",
            "points": ["3 to 5 short points, each <= 35 chars"],
            "warn": null or the number of one point to highlight,
            "cta": "one of احفظه / شاركه / علّق / تابعنا"}}"""


def log(*a):
    print(*a, flush=True)


def oidc_token():
    url, tok = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"], os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
    r = requests.get(url + "&audience=viraliq", headers={"Authorization": "Bearer " + tok}, timeout=30)
    r.raise_for_status()
    return r.json()["value"]


class Hub:
    def __init__(self):
        self.h = {"Authorization": "Bearer " + oidc_token()}

    def get(self, path):
        r = requests.get(HUB + path, headers=self.h, timeout=60)
        r.raise_for_status()
        return r.json()

    def post(self, path, data):
        r = requests.post(HUB + path, headers=self.h, json=data, timeout=240)
        r.raise_for_status()
        return r.json()


def ping(run, stage, msg):
    try:
        requests.post(HUB + "/ping", data={"run": run, "stage": stage, "msg": msg[:400]}, timeout=20)
    except requests.RequestException:
        pass


def llm(user, system=RULES, tries=3):
    body = {"model": MODEL, "temperature": 0.7, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    headers = {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Content-Type": "application/json",
               "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    for i in range(tries):
        r = requests.post(MODELS, headers=headers, json=body, timeout=120)
        if r.status_code == 429 and i < tries - 1:
            time.sleep(30 * (i + 1))
            continue
        try:
            content = r.json()["choices"][0]["message"]["content"]
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
            return json.loads(content)
        except (ValueError, KeyError, IndexError) as e:
            raise RuntimeError(f"model reply HTTP {r.status_code}: {r.text[:300]}") from e
    raise RuntimeError("model rate limit")
    raise RuntimeError("model rate limit")


def clean(d, kind, sources, when):
    """Clamp the model's draft to what the hub and the poster expect."""
    p = d.get("poster") or {}
    pts = [str(x).strip() for x in p.get("points", []) if str(x).strip()][:5]
    if len(pts) < 3:
        raise ValueError("poster needs at least 3 points")
    tags = [t if t.startswith("#") else "#" + t for t in d.get("hashtags", []) if t]
    if "#الكود_الذهبي" not in tags:
        tags.insert(0, "#الكود_الذهبي")
    warn = p.get("warn")
    return {"kind": kind, "title": str(d.get("title", ""))[:80], "text": str(d.get("text", "")).strip(),
            "hashtags": tags[:4], "comment": str(d.get("comment") or "").strip(), "sources": sources,
            "suggested_at": when,
            "poster": {"tag": p.get("tag"), "label": p.get("label"), "title": str(p.get("title", ""))[:40],
                       "sub": str(p.get("sub", ""))[:70], "points": [x[:45] for x in pts],
                       "warn": warn if isinstance(warn, int) and 1 <= warn <= len(pts) else None,
                       "cta": p.get("cta") or "احفظه"}}


def slot(h, m):
    n = datetime.now(TZ)
    t = n.replace(hour=h, minute=m, second=0, microsecond=0)
    if t < n + timedelta(minutes=30):
        t += timedelta(days=1)
    return t.strftime("%Y-%m-%d %H:%M")


def news(limit=25):
    items = []
    for url in FEEDS:
        try:
            root = ET.fromstring(requests.get(url, headers=UA, timeout=30).content)
        except (requests.RequestException, ET.ParseError) as e:
            log("feed failed", url, e)
            continue
        for it in root.iter():
            tag = it.tag.split("}")[-1]
            if tag not in ("item", "entry"):
                continue
            def get(*names):  # first child with one of these tag names (elements are falsy, so no `or`)
                return next((c for n in names for c in it if c.tag.split("}")[-1] == n), None)
            title = (get("title").text or "").strip() if get("title") is not None else ""
            link_el = get("link")
            link = (link_el.get("href") or link_el.text or "").strip() if link_el is not None else ""
            desc_el = get("description", "summary", "content")
            desc = re.sub(r"<[^>]+>", " ", (desc_el.text or "") if desc_el is not None else "")
            date_el = get("pubDate", "published", "updated")
            try:
                ds = (date_el.text or "").strip()
                when = parsedate_to_datetime(ds) if "," in ds else datetime.fromisoformat(ds.replace("Z", "+00:00"))
            except Exception:  # noqa: BLE001
                when = None
            if title and link and (when is None or when > datetime.now(timezone.utc) - timedelta(hours=36)):
                items.append({"title": title, "link": link, "summary": " ".join(desc.split())[:500]})
    seen, out = set(), []
    for it in items:
        if it["link"] not in seen:
            seen.add(it["link"])
            out.append(it)
    return out[:limit]


def course_draft(hist):
    courses = json.load(open(os.path.join(HERE, "courses.json"), encoding="utf-8"))
    used = set(hist.get("used_sources", []))
    c = next((c for c in courses if c["url"] not in used), None)
    if not c:
        return None
    day = hist["next_course_day"]
    d = llm(f"""Write post number {day} of the series «100 يوم دورات مجانية» about this free course.
Course: {json.dumps(c, ensure_ascii=False)}
Only say what is in "about"/"level"/"provider"; tell people the link is in the first comment.
poster.tag = "دورة مجانية", poster.label = "اليوم {day} من 100", and comment = "الرابط: {c['url']}".""")
    return clean(d, "course", [c["url"]], slot(12, 30))


def news_draft(hist, items):
    d = llm(f"""Pick the ONE story below that is most useful or interesting for our readers (prefer AI,
everyday apps, security, phones, programming) and that is not already in our recent posts.
Explain what happened and why it matters to an ordinary person. Put the story link in "comment".
Also return "link": the exact link of the story you picked.
Recent posts: {json.dumps(hist.get("recent", [])[-15:], ensure_ascii=False)}
Stories: {json.dumps(items, ensure_ascii=False)}""")
    link = d.get("link") or ""
    if link not in [i["link"] for i in items]:
        raise ValueError("model picked a link that is not in the feed")
    return clean(d, "news", [link], slot(16, 0))


def evening_draft(hist, items):
    d = llm(f"""Write tonight's post. Either:
(a) a debate about one of the stories below that people would argue about (present both sides
    fairly, end with a question; poster.tag = "سؤال", poster.cta = "علّق"), using only its facts,
    and put its link in "comment" and "link"; or
(b) if none fits, a practical, well-known tip for students or small businesses (keyboard shortcuts,
    phone settings, free tools, online safety). Only give tips you are sure are correct and current;
    set "link" to "".
Do not repeat recent posts: {json.dumps(hist.get("recent", [])[-15:], ensure_ascii=False)}
Stories: {json.dumps(items[:15], ensure_ascii=False)}""")
    link = d.get("link") or ""
    kind = "debate" if link else "tip"
    if link and link not in [i["link"] for i in items]:
        raise ValueError("model picked a link that is not in the feed")
    return clean(d, kind, [link] if link else [], slot(21, 30))


def request_draft(q, items):
    d = llm(f"""The page owner asked for a post about: «{q['topic']}»
Write it. If the topic needs current facts and the stories below cover it, use only their facts and
put the link in "comment" and "link"; otherwise write a practical, evergreen post with only facts you
are sure about and set "link" to "".
Stories: {json.dumps(items[:15], ensure_ascii=False)}""")
    link = d.get("link") or ""
    if link and link not in [i["link"] for i in items]:
        link = ""
    out = clean(d, "tip", [link] if link else [], slot(21, 30) if datetime.now(TZ).hour >= 16 else slot(16, 0))
    out["request"] = q["id"]
    return out


def main(run):
    hub = Hub()
    if run == "requests":
        queue = hub.get("/api/requests")["queue"]
        if not queue:
            log("no requests")
            return
        items = news()
        for q in queue:
            try:
                r = hub.post("/api/drafts", [request_draft(q, items)])
                log("request", q["id"], r.get("tick"))
                ping("request", "done", q["topic"][:80])
            except Exception as e:  # noqa: BLE001
                log("request failed:", e)
                ping("request", "error", f"{q['topic'][:60]}: {e}")
            hub.post("/api/requests", {"id": q["id"]})
        return
    ping(run, "boot", "github actions")
    hist = hub.get("/api/history")
    items = news()
    log(len(items), "news items")
    drafts = []
    jobs = ([("course", lambda: None if hist.get("pending_courses", 0) >= 2 else course_draft(hist)),
             ("news", lambda: news_draft(hist, items))] if run == "morning"
            else [("evening", lambda: evening_draft(hist, items))])
    for name, job in jobs:
        for attempt in range(2):
            try:
                d = job()
                if d:
                    drafts.append(d)
                break
            except Exception as e:  # noqa: BLE001
                log(name, "failed:", e)
                if attempt:
                    ping(run, "error", f"{name}: {e}")
    if not drafts:
        ping(run, "error", "no drafts produced")
        sys.exit(1)
    r = hub.post("/api/drafts", drafts)
    log(json.dumps(r, ensure_ascii=False))
    ping(run, "done", " | ".join(d["title"] for d in drafts))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "morning")
