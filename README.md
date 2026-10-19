# apps1monitor hub

Flask site on PythonAnywhere (apps1monitor.pythonanywhere.com) holding several admin sub-pages.

| Path | Tool |
|---|---|
| `/` | Hub home (open, no password); each tool below is locked with its own 4-digit PIN (`/pin/<tool>`) |
| `/goldencode/` | Golden Code ad manager: campaigns, orders, WhatsApp |
| `/goldencode/order?c=<id>` | Public order form to link from ads |
| `/viraliq/` | رائج · Viraliq: daily trend posts approved from Telegram (see `tools/viraliq/ROUTINE.md`) |
| `/course/` | جلسات دورة تطبيق الموبايل: 8 sessions, checklist per session |
| `/money/` | أول 10 دولار: 10 ways to earn, plus an inputs box the owner fills and Claude checks (`tools/money/review.py`) |
| `/social/` | مدير المنصات: one post (text/photo/video/music) adapted and published to LinkedIn, Facebook, Instagram, TikTok, a Telegram channel and the blog at `/social/blog`, controlled from its own Telegram bot (same code as the Social-Platforms-Manager repo) |
| `/linkedin/` | Legacy LinkedIn Autopost app, mounted unchanged from `/home/apps1monitor/linkedin` |

Add a tool: create `tools/<name>/__init__.py` with a Blueprint, register it in `app.py`, add it to `TOOLS`;
its `@login_required` pages then ask for that tool's PIN (set on first visit, with the old site password if one exists).
While a tool is open, 🔑 in the header changes its PIN. Five wrong PINs lock the tool for 15 min, doubling up to a day.

Deploy: `deploy.sh` uploads files via the PythonAnywhere API (needs `apps1monitor_PA_TOKEN`).
