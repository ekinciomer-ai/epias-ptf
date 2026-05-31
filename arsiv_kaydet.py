#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARSIV KAYDEDICI - Otocoin Veri Kutuphanesi (v2 - 31.05.2026)

YENI MANTIK: "Geri donuk cek + arsive ekle"
  - F2Pool hashrate_history endpoint'i her cihaz icin son ~48 saatin
    10 dakikalik tum verisini doner.
  - Her cron calistiginda bu 48 saati cekip arsivdeki eksik saatleri doldururuz.
  - Cron 24 saatte 1 calissa bile, tum saatler yakalanir.
  - Mevcut saatlerin uzerine YAZMAZ (idempotent ekleme).

YAZILAN DOSYALAR:
  arsiv_f2pool_YYYY-MM.json   -> saatlik havuz ozeti
  arsiv_cihaz_YYYY-MM.json    -> saatlik cihaz bazli (kod -> {h, d})
  arsiv_antminer_YYYY-MM.json -> anlik Pi saha verisi (sadece bu saatlik)

DUZELTILEN HATALAR:
  - 409 Conflict: gh_yaz retry'li + SHA yenileme
  - Eski "anlik snapshot" yerine "48 saat geri doldurma"
"""
import os, json, datetime, base64, urllib.request, urllib.error, time

F2POOL_TOKEN = os.environ.get("F2POOL_TOKEN", "")
F2POOL_USER  = os.environ.get("F2POOL_KULLANICI", "mehmetas")
GH_TOKEN     = os.environ.get("GH_TOKEN", "")
GH_REPO      = os.environ.get("GH_REPO", "ekinciomer-ai/epias-ptf")

def log(*a):
    print(datetime.datetime.now().strftime("%H:%M:%S"), *a, flush=True)

# ============================================================
# F2POOL API
# ============================================================
def f2pool_post(endpoint, body):
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(f"https://api.f2pool.com/v2/{endpoint}",
            data=data, headers={"Content-Type":"application/json", "F2P-API-SECRET":F2POOL_TOKEN}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        log(f"  f2pool_post hata ({endpoint}):", str(e)[:80])
        return None

def f2pool_legacy(path):
    try:
        req = urllib.request.Request(f"https://api.f2pool.com/{path}",
            headers={"F2P-API-SECRET":F2POOL_TOKEN})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        log(f"  f2pool_legacy hata ({path}):", str(e)[:80])
        return None

def f2pool_workers():
    result = f2pool_post("hash_rate/worker/list", {
        "currency": "bitcoin", "mining_user_name": F2POOL_USER})
    return result.get("workers", []) if result else []

def f2pool_hashrate():
    result = f2pool_post("hash_rate/info", {
        "currency": "bitcoin", "mining_user_name": F2POOL_USER})
    if result:
        info = result.get("info", {})
        return {"anlik": info.get("hash_rate", 0)/1e12,
                "h1": info.get("h1_hash_rate", 0)/1e12,
                "h24": info.get("h24_hash_rate", 0)/1e12}
    return {"anlik": 0, "h1": 0, "h24": 0}

def f2pool_bugun_tahmini():
    result = f2pool_post("assets/balance", {
        "currency": "bitcoin", "mining_user_name": F2POOL_USER,
        "calculate_estimated_income": True})
    return result.get("balance_info", {}).get("estimated_today_income", 0) if result else 0

def cihaz_durum_kod(anlik, h1, h24):
    """c=calisiyor, y=yavasliyor, u=uyuyor, k=kapali"""
    if anlik > 0: return "c"
    if h1 > 0:    return "y"
    if h24 > 0:   return "u"
    return "k"

# ============================================================
# GITHUB
# ============================================================
def gh_oku(dosya):
    """Dosyayi oku. Donus: (icerik_dict, sha) veya (None, None)."""
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
    """GitHub'a yaz. 409 Conflict'te SHA'yi yenileyip 3 kez dener.
    Geriye True/False doner, exception ustte yakalansa bile diger islemler devam etsin."""
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
                log(f"  409 Conflict ({dosya}), SHA yenileniyor (deneme {deneme+1}/3)")
                time.sleep(1)
                _, yeni_sha = gh_oku(dosya)
                if yeni_sha:
                    sha = yeni_sha
                    continue
            log(f"  gh_yaz hatasi ({dosya}): {e.code} {e.reason}")
            return False
    return False

# ============================================================
# CIHAZ GECMISI: 48 saatlik hashrate_history -> saatlik ortalama
# ============================================================
def cihaz_saatlik_gecmis(worker_name):
    """Bir cihazin son ~48 saatlik 10dk verisini saatlik ortalamaya cevir.
    F2Pool hashrate_history formati: { "2026-05-31 14:00:00": hash_raw, ... }
    Donus: { "2026-05-31 14:00": {"h": ortalama_TH, "d": durum_kodu} }"""
    legacy = f2pool_legacy(f"bitcoin/{F2POOL_USER}/{worker_name}")
    if not legacy:
        return {}
    hist = legacy.get("hashrate_history", {})
    if not hist:
        return {}

    # 10dk kayitlari saate gore grupla
    saat_grup = {}  # {"YYYY-MM-DD HH:00": [hash_th, ...]}
    for ts, hr in hist.items():
        if len(ts) < 16:
            continue
        saat_anahtar = ts[:13] + ":00"
        saat_grup.setdefault(saat_anahtar, []).append(hr / 1e12)

    # Her saatin ortalamasini al + durum belirle
    sonuc = {}
    for sa, arr in saat_grup.items():
        if not arr:
            continue
        ort = sum(arr) / len(arr)
        dolu_sayisi = sum(1 for x in arr if x > 0)
        if dolu_sayisi == len(arr):
            durum = "c"
        elif dolu_sayisi > len(arr) / 2:
            durum = "y"
        elif dolu_sayisi > 0:
            durum = "u"
        else:
            durum = "k"
        sonuc[sa] = {"h": round(ort, 1), "d": durum}
    return sonuc

# ============================================================
# ANTMINER (Pi saha verisi - anlik snapshot)
# ============================================================
def arsivle_antminer(ts, ay):
    """antminer_panel.json'dan anlik snapshot."""
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
        log("  antminer_panel.json yok, atlandi")
        return
    devices = panel.get("devices", [])
    if not devices:
        log("  antminer device yok, atlandi")
        return

    snap = {}
    toplam_guc = toplam_hash = 0.0
    for d in devices:
        ad = d.get("havuz_worker") or d.get("actual_worker") or d.get("saha_worker") or "?"
        hr = d.get("hashrate_TH", 0) or 0
        model = d.get("model", "")
        guc = (hr * jth(model)) / 1000.0
        toplam_guc += guc
        toplam_hash += hr
        snap[ad] = {
            "hash": round(hr, 1),
            "guc_tahmini": round(guc, 3),
            "verim": d.get("efficiency_pct", 0),
            "temp": d.get("temp_max", 0),
            "su": d.get("temp_water", 0),
            "model": model,
            "online": 1 if d.get("online") else 0,
            "uptime": round(d.get("elapsed_hours", 0), 1),
        }

    dosya = f"arsiv_antminer_{ay}.json"
    av, ash = gh_oku(dosya)
    if av is None: av = {}
    av[ts] = {
        "toplam_hash_TH": round(toplam_hash, 1),
        "toplam_guc_kW_tahmini": round(toplam_guc, 2),
        "cihaz_sayisi": len(devices),
        "cihazlar": snap,
    }
    if gh_yaz(dosya, av, ash):
        log(f"  {dosya}: {len(av)} kayit (anlik snapshot)")

# ============================================================
# ANA ARSIVLE FONKSIYONU
# ============================================================
def arsivle():
    if not F2POOL_TOKEN:
        log("HATA: F2POOL_TOKEN yok"); return
    if not GH_TOKEN:
        log("HATA: GH_TOKEN yok"); return

    simdi = datetime.datetime.now()
    ts_simdi = simdi.strftime("%Y-%m-%d %H:%M")

    log("F2Pool veri cekiliyor...")
    workers = f2pool_workers()
    hr_info = f2pool_hashrate()
    bugun_btc = f2pool_bugun_tahmini()
    log(f"  {len(workers)} cihaz, havuz hash {hr_info['anlik']:.0f} TH/s, bugun ~{bugun_btc:.6f} BTC")

    if not workers:
        log("UYARI: F2Pool'dan cihaz gelmedi, kayit atlandi")
        return

    # ============================================================
    # ARSIV_CIHAZ: HER CIHAZ icin 48 SAATLIK GERI DOLDURMA
    # ============================================================
    log("Cihaz hashrate gecmisleri cekiliyor (48 saat geri)...")
    tum_cihaz_saatler = {}  # {"YYYY-MM-DD HH:00": {kod: {h, d}}}

    for w in workers:
        info = w.get("hash_rate_info", {})
        name = info.get("name", "")
        if not name or "." not in name:
            continue
        kod = name.split(".")[-1]
        saatlik = cihaz_saatlik_gecmis(name)
        for sa, deg in saatlik.items():
            tum_cihaz_saatler.setdefault(sa, {})[kod] = deg

    log(f"  Toplam {len(tum_cihaz_saatler)} farkli saat icin veri toplandi")

    # Ay bazinda dosyalara dagit (bazi saatler bir onceki aya dusebilir)
    aylar = set(sa[:7] for sa in tum_cihaz_saatler.keys())
    for ay in aylar:
        dosya = f"arsiv_cihaz_{ay}.json"
        mevcut, sha = gh_oku(dosya)
        if mevcut is None:
            mevcut = {}
        eklenen = 0
        guncellenen = 0
        for sa, cihaz_kayit in tum_cihaz_saatler.items():
            if not sa.startswith(ay):
                continue
            if sa in mevcut:
                # Mevcut saat: sadece eksik cihazlari ekle (mevcut kayda dokunma)
                degisti = False
                for kod, deg in cihaz_kayit.items():
                    if kod not in mevcut[sa]:
                        mevcut[sa][kod] = deg
                        degisti = True
                if degisti:
                    guncellenen += 1
            else:
                mevcut[sa] = cihaz_kayit
                eklenen += 1
        if eklenen > 0 or guncellenen > 0:
            if gh_yaz(dosya, mevcut, sha):
                log(f"  {dosya}: +{eklenen} yeni saat, {guncellenen} saat tamamlandi (toplam {len(mevcut)})")
            else:
                log(f"  {dosya}: YAZMA BASARISIZ!")
        else:
            log(f"  {dosya}: degisiklik yok (toplam {len(mevcut)})")

    # ============================================================
    # ARSIV_F2POOL: HAVUZ OZETI - bu saat icin tek snapshot
    # ============================================================
    ay_simdi = ts_simdi[:7]
    dosya = f"arsiv_f2pool_{ay_simdi}.json"
    ozet, sha = gh_oku(dosya)
    if ozet is None:
        ozet = {}
    saat_anahtar = ts_simdi[:13] + ":00"
    calisan = 0
    for w in workers:
        info = w.get("hash_rate_info", {})
        if cihaz_durum_kod(info.get("hash_rate",0),
                           info.get("h1_hash_rate",0),
                           info.get("h24_hash_rate",0)) == "c":
            calisan += 1
    ozet[saat_anahtar] = {
        "hash": round(hr_info['anlik'], 1),
        "hash_h1": round(hr_info['h1'], 1),
        "hash_h24": round(hr_info['h24'], 1),
        "calisan": calisan,
        "toplam": len(workers),
        "btc": round(bugun_btc, 8) if bugun_btc else 0,
    }
    if gh_yaz(dosya, ozet, sha):
        log(f"  {dosya}: {len(ozet)} kayit (anlik havuz)")

    # ============================================================
    # ARSIV_ANTMINER: Pi anlik snapshot
    # ============================================================
    arsivle_antminer(ts_simdi, ay_simdi)

    log("Arsivleme tamamlandi.")

if __name__ == "__main__":
    try:
        arsivle()
    except Exception as e:
        log("KRITIK HATA:", str(e))
        import traceback; traceback.print_exc()
        import sys; sys.exit(1)
