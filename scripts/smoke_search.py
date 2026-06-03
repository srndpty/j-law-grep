"""POST a fixed query to /api/search and assert the response contains hits.

Used by the `api-smoke` / `frontend-smoke` Makefile targets. The request body
is built and JSON-encoded here (ASCII-escaped) instead of being passed through
the shell, so the Japanese query is not mangled by the OS locale encoding
(e.g. cp932 on Windows). A failed search prints a clear diagnostic instead of
an opaque traceback.

Usage: python scripts/smoke_search.py <label> <base_url>
"""

import json
import sys
import urllib.error
import urllib.request

# Make Japanese output legible regardless of the OS console codepage (cp932).
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

label = sys.argv[1] if len(sys.argv) > 1 else "smoke"
base_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"

# A plain full-text term keeps this a connectivity/wiring check: it returns
# hits on any non-empty corpus (sample 民法709/710条 and full corpus alike)
# and does not depend on importer-provided metadata such as article_no.
body = {
    "q": "損害",
    "mode": "literal",
    "size": 5,
    "page": 1,
}
# ensure_ascii=True keeps the payload pure ASCII so it survives any locale.
payload = json.dumps(body, ensure_ascii=True).encode("ascii")
request = urllib.request.Request(
    f"{base_url}/api/search",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read().decode("utf-8")
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", "replace")[:300]
    sys.exit(f"{label} FAILED: HTTP {exc.code} {detail}")
except urllib.error.URLError as exc:
    sys.exit(f"{label} FAILED: cannot reach {base_url} ({exc.reason})")

try:
    data = json.loads(raw)
except json.JSONDecodeError:
    sys.exit(f"{label} FAILED: non-JSON response: {raw[:300]}")

hits = data.get("hits", [])
if not hits:
    detail = data.get("detail") or data.get("error")
    suffix = f" detail={detail}" if detail else " (index empty? run `make reindex`)"
    sys.exit(f"{label} FAILED: no hits.{suffix}")

top = hits[0]
print(f"{label} OK: {top.get('law_name')} {top.get('article_no')} (total={data.get('total')})")
