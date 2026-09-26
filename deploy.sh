#!/usr/bin/env bash
# Upload the hub to /home/apps1monitor/hub, point the WSGI file at it, reload.
set -euo pipefail
T="${apps1monitor_PA_TOKEN:?}"; U=apps1monitor; A="https://www.pythonanywhere.com/api/v0/user/$U"
cd "$(dirname "$0")"
for f in $(git ls-files | grep -v -E '^(deploy.sh|\.gitignore)$'); do
  curl -sf -H "Authorization: Token $T" -F "content=@$f" "$A/files/path/home/$U/hub/$f" >/dev/null && echo "up $f"
done
printf 'import sys\nsys.path.insert(0, "/home/%s/hub")\nfrom wsgi import application  # noqa\n' "$U" > /tmp/pa_wsgi.py
curl -sf -H "Authorization: Token $T" -F "content=@/tmp/pa_wsgi.py" "$A/files/path/var/www/${U}_pythonanywhere_com_wsgi.py" >/dev/null
curl -sf -X POST -H "Authorization: Token $T" "$A/webapps/$U.pythonanywhere.com/reload/" && echo reloaded
