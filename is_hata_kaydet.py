"""is_calistir.sh yardımcısı: iş sonucunu n8n/is_hatalari.json'a yazar (gizli değerler maskelenir)."""
import json, re, sys
from datetime import datetime, timedelta, timezone

ad, kod, yol = sys.argv[1], int(sys.argv[2]), sys.argv[3]
TR = timezone(timedelta(hours=3))
GIZLI = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AC[0-9a-f]{32}|SK[0-9a-f]{32}|Bearer\s+\S+|token\s+[A-Za-z0-9_]{20,})")
try:
    satir = open(yol, errors="ignore").read().splitlines()
except Exception:
    satir = []
ozet = [GIZLI.sub("***", s)[:300] for s in satir if s.strip()][-40:]
try:
    d = json.load(open("n8n/is_hatalari.json"))
except Exception:
    d = {"isler": {}, "hatalar": []}
z = datetime.now(TR).isoformat(timespec="seconds")
i = d["isler"].setdefault(ad, {})
i["son"] = z; i["son_kod"] = kod
if kod == 0:
    i["son_basari"] = z
else:
    i["son_hata"] = z
    d["hatalar"] = (d["hatalar"] + [{"is": ad, "zaman": z, "kod": kod, "cikti": ozet}])[-30:]
json.dump(d, open("n8n/is_hatalari.json", "w"), ensure_ascii=False, indent=1)
print(f"[iş durumu] {ad}: kod {kod}")
