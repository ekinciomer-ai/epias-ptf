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
import os, json, datetime, base64, urllib.request, urllib.error, time

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
    """GitHub'a dosya yaz. 409 Conflict'te SHA'yi yenileyip 3 kez dener.
    Sorun: ayni anda 3 dosyaya art arda yazinca GitHub bir oncekinin commit'i
    sebebiyle repo durumu degisir ve eski SHA reddedilir."""
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{dosya}"
    icerik = json.dumps(veri, ensure_ascii=False, separators=(',', ':'))

    for deneme in range(3):
        body = {
            "message": f"arsiv {dosya} {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "content": base64.b64encode(icerik.encode("utf-8")).decode("ascii"),
        }
        if sha:
            body["sha"] = sha

        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            "Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json",
            "Content-Type": "application/json"}, method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status in (200, 201)
        except urllib.error.HTTPError as e:
            if e.code == 409 and deneme < 2:
                # SHA cakismasi - dosyayi yeniden oku, guncel SHA al
                log(f"  409 Conflict ({dosya}), SHA yenileniyor (deneme {deneme+1}/3)")
                time.sleep(1)  # GitHub indeks gecikmesine pay
                _, yeni_sha = gh_oku(dosya)
                if yeni_sha:
                    sha = yeni_sha
                    continue
            log(f"  gh_yaz hatasi ({dosya}): {e.code} {e.reason}")
            raise
    return False

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

    # 2) Cihaz bazli (F2Pool)
    cihaz_dosya = f"arsiv_cihaz_{ay}.json"
    cveri, csha = gh_oku(cihaz_dosya)
    if cveri is None: cveri = {}
    cveri[ts] = cihazlar
    gh_yaz(cihaz_dosya, cveri, csha)
    log(f"  {cihaz_dosya}: {len(cveri)} kayit")

    # 3) Antminer saha verisi (Pi'nin topladigi - gercek guc dahil)
    arsivle_antminer(ts, ay)

    log("Arsivleme tamamlandi.")

def arsivle_antminer(ts, ay):
    """antminer_panel.json'u oku, her cihazin o anki verilerini arsivle.
    NOT: Antminer device'inda gercek guc (Watt) YOK - sadece hashrate var.
    Guc, hashrate x model verimliligi (J/TH) ile TAHMIN edilir."""
    # Model -> J/TH verimlilik tablosu (nominal)
    VERIM = {
        'S19': 34.5, 'S19 Pro': 29.5, 'S19j': 34.5, 'S19j Pro': 30.5, 'S19j Pro+': 27.5,
        'S19 XP': 21.5, 'S19 XP Hyd': 20.8, 'S19 Hydro': 28.0, 'S19k Pro': 23.0, 'T19': 37.5,
        'S21': 17.5, 'S21 Pro': 15.0, 'S21+': 16.5, 'S21 XP': 13.5, 'S21 Hyd': 16.0, 'T21': 19.0,
        'S17': 45.0, 'T17': 55.0
    }
    def jth(model):
        if not model: return 25.0
        m = str(model)
        if m in VERIM: return VERIM[m]
        best, bl = 25.0, 0
        for k, v in VERIM.items():
            if k.upper() in m.upper() and len(k) > bl:
                best, bl = v, len(k)
        return best

    panel, _ = gh_oku("antminer_panel.json")
    if not panel:
        log("  antminer_panel.json yok/bos, antminer arsivi atlandi")
        return
    devices = panel.get("devices", [])
    if not devices:
        log("  antminer device yok, atlandi")
        return

    snap = {}
    toplam_guc = 0.0
    toplam_hash = 0.0
    for d in devices:
        ad = d.get("havuz_worker") or d.get("actual_worker") or d.get("saha_worker") or "?"
        hr = d.get("hashrate_TH", 0) or 0
        model = d.get("model", "")
        guc = (hr * jth(model)) / 1000.0  # kW (TAHMINI - hashrate x J/TH)
        toplam_guc += guc
        toplam_hash += hr
        snap[ad] = {
            "hash": round(hr, 1),
            "guc_tahmini": round(guc, 3),               # kW (tahmini)
            "verim": d.get("efficiency_pct", 0),
            "temp": d.get("temp_max", 0),
            "su": d.get("temp_water", 0),
            "model": model,
            "online": 1 if d.get("online") else 0,
            "uptime": round(d.get("elapsed_hours", 0), 1),
        }

    arsiv_dosya = f"arsiv_antminer_{ay}.json"
    av, ash = gh_oku(arsiv_dosya)
    if av is None: av = {}
    av[ts] = {
        "toplam_hash_TH": round(toplam_hash, 1),
        "toplam_guc_kW_tahmini": round(toplam_guc, 2),
        "cihaz_sayisi": len(devices),
        "cihazlar": snap,
    }
    gh_yaz(arsiv_dosya, av, ash)
    log(f"  {arsiv_dosya}: {len(av)} kayit ({round(toplam_hash,0)} TH/s, ~{round(toplam_guc,1)} kW)")

if __name__ == "__main__":
    try:
        arsivle()
    except Exception as e:
        log("KRITIK HATA:", str(e))
        import traceback; traceback.print_exc()
