#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARSIV KAYDEDICI - Otocoin Veri Kutuphanesi
Her saat F2Pool snapshot'ini GitHub'daki aylik arsiv dosyalarina ekler.
F2Pool fonksiyonlari ofis_panel.py'deki CALISAN kodlardan birebir alindi.

Cikti:
  arsiv_f2pool_YYYY-MM.json  -> saatlik havuz ozeti
  arsiv_cihaz_YYYY-MM.json   -> saatlik cihaz bazli durum
"""
import os, json, datetime, base64, urllib.request, urllib.error

F2POOL_TOKEN = os.environ.get("F2POOL_TOKEN", "")
F2POOL_USER  = os.environ.get("F2POOL_KULLANICI", "mehmetas")
GH_TOKEN     = os.environ.get("GH_TOKEN", "")
GH_REPO      = os.environ.get("GH_REPO", "ekinciomer-ai/epias-ptf")

def log(*a):
    print(datetime.datetime.now().strftime("%H:%M:%S"), *a, flush=True)

# === F2POOL API (ofis_panel.py'den birebir) ===
def f2pool_post(endpoint, body):
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(f"https://api.f2pool.com/v2/{endpoint}",
            data=data, headers={"Content-Type":"application/json", "F2P-API-SECRET":F2POOL_TOKEN}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        log("f2pool_post hata:", endpoint, str(e)[:80])
        return None

def f2pool_hashrate():
    result = f2pool_post("hash_rate/info", {
        "currency": "bitcoin", "mining_user_name": F2POOL_USER})
    if result:
        info = result.get("info", {})
        return {"anlik": info.get("hash_rate", 0)/1e12,
                "h1": info.get("h1_hash_rate", 0)/1e12,
                "h24": info.get("h24_hash_rate", 0)/1e12}
    return {"anlik": 0, "h1": 0, "h24": 0}

def f2pool_workers():
    result = f2pool_post("hash_rate/worker/list", {
        "currency": "bitcoin", "mining_user_name": F2POOL_USER})
    return result.get("workers", []) if result else []

def f2pool_bugun_tahmini():
    result = f2pool_post("assets/balance", {
        "currency": "bitcoin", "mining_user_name": F2POOL_USER,
        "calculate_estimated_income": True})
    return result.get("balance_info", {}).get("estimated_today_income", 0) if result else 0

def cihaz_durum(info):
    anlik = info.get("hash_rate", 0)
    h1 = info.get("h1_hash_rate", 0)
    h24 = info.get("h24_hash_rate", 0)
    if anlik > 0: return "calisiyor"
    elif h1 > 0: return "yavasliyor"
    elif h24 > 0: return "uyuyor"
    return "kapali"

# === GITHUB OKUMA/YAZMA ===
def gh_oku(dosya):
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{dosya}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
            return json.loads(base64.b64decode(d["content"]).decode("utf-8")), d["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise

def gh_yaz(dosya, veri, sha=None):
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{dosya}"
    icerik = json.dumps(veri, ensure_ascii=False, separators=(',', ':'))
    body = {"message": f"arsiv {dosya} {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "content": base64.b64encode(icerik.encode("utf-8")).decode("ascii")}
    if sha: body["sha"] = sha
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status in (200, 201)

# === ARSIVLE ===
def arsivle():
    if not F2POOL_TOKEN:
        log("HATA: F2POOL_TOKEN yok"); return
    if not GH_TOKEN:
        log("HATA: GH_TOKEN yok"); return

    simdi = datetime.datetime.now()
    ts = simdi.strftime("%Y-%m-%d %H:%M")
    gun = simdi.strftime("%Y-%m-%d")
    ay = gun[:7]

    # Havuz hashrate
    hr = f2pool_hashrate()
    # Cihazlar
    workers = f2pool_workers()
    calisan = 0
    cihazlar = {}
    for w in workers:
        info = w.get("hash_rate_info", {})
        name = info.get("name", "?")
        durum = cihaz_durum(info)
        cihazlar[name] = {"h": round(info.get("hash_rate", 0)/1e12, 1), "d": durum[0]}
        if durum == "calisiyor":
            calisan += 1
    # Bugunku tahmini BTC
    bugun_btc = f2pool_bugun_tahmini()

    log(f"Snapshot: {hr['anlik']:.0f} TH/s, {calisan}/{len(workers)} cihaz, {bugun_btc} BTC")

    if hr['anlik'] == 0 and len(workers) == 0:
        log("UYARI: F2Pool'dan veri gelmedi (token/baglanti?), kayit atlandi")
        return

    # 1) Havuz ozeti
    ozet_dosya = f"arsiv_f2pool_{ay}.json"
    ozet, sha = gh_oku(ozet_dosya)
    if ozet is None: ozet = {}
    ozet[ts] = {
        "hash": round(hr['anlik'], 1),
        "hash_h1": round(hr['h1'], 1),
        "hash_h24": round(hr['h24'], 1),
        "calisan": calisan,
        "toplam": len(workers),
        "btc": round(bugun_btc, 8) if bugun_btc else 0,
    }
    gh_yaz(ozet_dosya, ozet, sha)
    log(f"  {ozet_dosya}: {len(ozet)} kayit")

    # 2) Cihaz bazli
    cihaz_dosya = f"arsiv_cihaz_{ay}.json"
    cveri, csha = gh_oku(cihaz_dosya)
    if cveri is None: cveri = {}
    cveri[ts] = cihazlar
    gh_yaz(cihaz_dosya, cveri, csha)
    log(f"  {cihaz_dosya}: {len(cveri)} kayit")

    log("Arsivleme tamamlandi.")

if __name__ == "__main__":
    try:
        arsivle()
    except Exception as e:
        log("KRITIK HATA:", str(e))
        import traceback; traceback.print_exc()
