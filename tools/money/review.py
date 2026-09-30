"""Claude's side of the /money/ inputs box.

    python tools/money/review.py state                       # plan + inputs (secrets stay masked)
    python tools/money/review.py ok <id> "note"              # mark an input correct
    python tools/money/review.py wrong <id> "what to fix"    # mark an input wrong
    python tools/money/review.py ask "label" [kind] ["hint"] # ask the owner for something new
    python tools/money/review.py tick <key>... [--undo]      # tick plan steps (keys like 2-0)

The API key is read from the hub's data/money.json through the PythonAnywhere files API.
Needs $apps1monitor_PA_TOKEN.
"""
import json
import os
import sys

import requests

USER = "apps1monitor"
SITE = f"https://{USER}.pythonanywhere.com/money"
FILE = f"https://www.pythonanywhere.com/api/v0/user/{USER}/files/path/home/{USER}/hub/data/money.json"


def key():
    r = requests.get(FILE, headers={"Authorization": "Token " + os.environ["apps1monitor_PA_TOKEN"]}, timeout=30)
    r.raise_for_status()
    return r.json()["api_key"]


def call(path, data=None):
    h = {"X-Key": key()}
    r = (requests.post(SITE + path, json=data, headers=h, timeout=60) if data is not None
         else requests.get(SITE + path, headers=h, timeout=60))
    r.raise_for_status()
    return r.json()


def main(a):
    if not a or a[0] == "state":
        print(json.dumps(call("/api/state"), ensure_ascii=False, indent=1))
    elif a[0] in ("ok", "wrong") and len(a) >= 2:
        print(call("/api/review", {"id": a[1], "status": a[0], "note": a[2] if len(a) > 2 else ""}))
    elif a[0] == "ask" and len(a) >= 2:
        print(call("/api/ask", {"label": a[1], "kind": a[2] if len(a) > 2 else "text", "hint": a[3] if len(a) > 3 else ""}))
    elif a[0] == "tick" and len(a) >= 2:
        keys = [k for k in a[1:] if k != "--undo"]
        print(call("/api/steps", {"keys": keys, "done": "--undo" not in a}))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
