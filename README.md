# apps1monitor hub

Flask site on PythonAnywhere (apps1monitor.pythonanywhere.com) holding several admin sub-pages.

| Path | Tool |
|---|---|
| `/` | Hub home (admin login; first visit sets the password) |
| `/goldencode/` | Golden Code ad manager: campaigns, orders, WhatsApp |
| `/goldencode/order?c=<id>` | Public order form to link from ads |
| `/linkedin/` | Legacy LinkedIn Autopost app, mounted unchanged from `/home/apps1monitor/linkedin` |

Add a tool: create `tools/<name>/__init__.py` with a Blueprint, register it in `app.py`, add it to `TOOLS`.

Deploy: `deploy.sh` uploads files via the PythonAnywhere API (needs `apps1monitor_PA_TOKEN`).
