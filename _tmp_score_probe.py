from pathlib import Path
from urllib.request import Request, urlopen
import re

ROOT = Path(__file__).resolve().parent
html = urlopen(
    Request(
        "https://bibletoppt.com/hymn/sheet-music/030",
        headers={"User-Agent": "Mozilla/5.0"},
    ),
    timeout=20,
).read().decode("utf-8", "replace")

# Persist a slice for searching download handlers
(ROOT / "_tmp_sheet.html").write_text(html, encoding="utf-8")
print("html len", len(html))
print("has __NEXT_DATA__", "__NEXT_DATA__" in html)
print("onclick", "onclick" in html)
for key in ("sheet-music", "downloadFile", "signedUrl", "presign", ".jpg", "files/", "cdn"):
    print(key, html.lower().count(key.lower()))

# Try likely asset URLs
candidates = [
    "https://bibletoppt.com/thumbnails/hymn/sheet-music/030장-전능하고 놀라우신(jpg).webp",
    "https://bibletoppt.com/thumbnails/hymn/sheet-music/030%EC%9E%A5-%EC%A0%84%EB%8A%A5%ED%95%98%EA%B3%A0%20%EB%86%80%EB%9D%BC%EC%9A%B0%EC%8B%A0(jpg).webp",
    "https://bibletoppt.com/hymn/sheet-music/030.jpg",
    "https://bibletoppt.com/files/hymn/sheet-music/030.jpg",
    "https://bibletoppt.com/downloads/hymn/030.jpg",
    "https://bibletoppt.com/api/hymn/sheet-music/030",
    "https://bibletoppt.com/api/download/hymn/sheet-music/030?format=jpg",
]
for url in candidates:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=12) as resp:
            data = resp.read(64)
            print("OK", resp.status, resp.getheader("Content-Type"), len(data), url[:90])
    except Exception as e:
        print("NO", type(e).__name__, url[:90], str(e)[:80])
