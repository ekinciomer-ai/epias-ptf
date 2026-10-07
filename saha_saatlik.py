#!/usr/bin/env python3
"""Saha saatlik özeti — GitHub Actions ile 10 dakikada bir.
Pi her 1-2 dakikada antminer_panel.json'u günceller; her güncelleme bir commit'tir. Bu betik son 2 günün
commit geçmişinden saat saat ortalama toplam hash (TH/s), filo gücü (kW) ve çalışan/ısınan/uyuyan sayısını
hesaplar ve n8n/saha_saatlik.json'a yazar. Panel bunu enerji maliyeti ve hashprice ile çarpar.
Toplayıcının cihazlara ulaşamadığı saatler yazılmaz (veri yok, sıfır değil)."""
import json, subprocess
from datetime import datetime, timedelta, timezone

TR = timezone(timedelta(hours=3))
JTH = {"S21e Hyd": 17.5, "S19 XP+ Hyd": 21.5, "S19e XP Hyd": 34.5}   # J/TH (antminer arşivindeki güç tahmini / hash)
ISINMA_KW = 1.0
DOSYA = "n8n/saha_saatlik.json"


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True).stdout


def main():
    try:
        kim = json.load(open("n8n/cihaz_kimlik.json"))
    except Exception:
        kim = {}
    since = (datetime.now(TR) - timedelta(days=2)).replace(hour=0, minute=0, second=0).isoformat()
    S, gor = {}, set()
    for c in git("log", "--since=" + since, "--format=%H", "--", "antminer_panel.json").split():
        try:
            d = json.loads(git("show", c + ":antminer_panel.json"))
        except Exception:
            continue
        t = d.get("timestamp")
        if not t or t in gor:
            continue
        gor.add(t)
        ts = datetime.fromisoformat(t)
        ts = ts.replace(tzinfo=TR) if ts.tzinfo is None else ts.astimezone(TR)
        th = kw = 0.0
        cal = isi = uy = ul = 0
        for v in d.get("devices") or []:
            if not (v.get("online") or v.get("sleeping")):
                continue
            ul += 1
            h = v.get("hashrate_TH") or 0
            w = str(v.get("actual_worker") or "").split(".")[-1]
            if v.get("sleeping"):
                uy += 1
            elif h > 0:
                cal += 1
                th += h
                kw += h * JTH.get((kim.get(w) or {}).get("model") or v.get("model"), 17.5) / 1000
            else:
                isi += 1
                kw += ISINMA_KW
        k = ts.strftime("%Y-%m-%d %H")
        r = S.setdefault(k, {"n": 0, "th": 0.0, "kw": 0.0, "cal": 0, "isi": 0, "uy": 0, "ul": 0, "ilk": ts, "son": ts})
        r["n"] += 1; r["th"] += th; r["kw"] += kw; r["cal"] += cal; r["isi"] += isi; r["uy"] += uy; r["ul"] += ul
        r["ilk"] = min(r["ilk"], ts); r["son"] = max(r["son"], ts)
    saat = {}
    for k, r in sorted(S.items()):
        n = r["n"]
        if r["ul"] / n < 1:
            continue
        saat[k] = {"n": n, "th": round(r["th"] / n, 1), "kw": round(r["kw"] / n, 2), "calisan": round(r["cal"] / n, 1),
                   "isinan": round(r["isi"] / n, 1), "uyuyan": round(r["uy"] / n, 1), "ulasilan": round(r["ul"] / n, 1),
                   "ilk": r["ilk"].strftime("%H:%M"), "son": r["son"].strftime("%H:%M")}
    json.dump({"guncellendi": datetime.now(TR).isoformat(timespec="seconds"), "jth": JTH, "isinma_kw": ISINMA_KW,
               "kaynak": "antminer_panel.json commit geçmişi (GitHub Actions)", "saat": saat},
              open(DOSYA, "w"), ensure_ascii=False, indent=1)
    print(len(saat), "saat yazıldı")


if __name__ == "__main__":
    main()
