#!/usr/bin/env bash
# Upload the hub to /home/apps1monitor/hub, point the WSGI file at it, reload.
# The PythonAnywhere API throttles bursts (HTTP 429), so every call retries with a pause.
set -euo pipefail
T="${apps1monitor_PA_TOKEN:?}"; U=apps1monitor; A="https://www.pythonanywhere.com/api/v0/user/$U"
cd "$(dirname "$0")"

pa() {  # pa <curl args...>: retry up to 6 times, waiting out throttling
  for i in 1 2 3 4 5 6; do
    curl -sf -H "Authorization: Token $T" "$@" >/dev/null && return 0
    sleep $((i * 10))
  done
  echo "FAILED: $*" >&2; return 1
}

for f in $(git ls-files | grep -v -E '^(deploy.sh|\.gitignore|\.github/.*)$'); do
  pa -F "content=@$f" "$A/files/path/home/$U/hub/$f" && echo "up $f"
done
printf 'import sys\nsys.path.insert(0, "/home/%s/hub")\nfrom wsgi import application  # noqa\n' "$U" > /tmp/pa_wsgi.py
pa -F "content=@/tmp/pa_wsgi.py" "$A/files/path/var/www/${U}_pythonanywhere_com_wsgi.py"
pa -X POST "$A/webapps/$U.pythonanywhere.com/reload/" && echo reloaded
