from flask import Flask, jsonify, session, redirect, render_template_string, request, Response
import hashlib, json, os, urllib.request, urllib.parse, urllib.error
import datetime

app = Flask(__name__)
app.secret_key = "otocoin-ofis-2026"

# === VERSIYON TAKIBI ===
# Format: ver.AA.BB.CC
#   AA = menu degisikligi (sekme ekleme/cikarma, yapisal)
#   BB = sekil/gorsel degisikligi (tema, renk, layout)
#   CC = veri degisikligi (EPIAS, OSOS, manuel girisler)
_PANEL_VERSIYON_ANA = "ver.02.01.1"
# Build numarasi: HER YENI DOSYA TESLIMATINDA +1 yapilir.
# Calisma aninda DEGISMEZ - dosyaya gomulu sabit sayi.
# Sen damgaya bakinca b15 -> b16 olursa yeni surum yuklenmis demektir.
PANEL_VERSIYON_BUILD = 54

def _panel_tarih():
    try:
        import os as _os, datetime as _dt
        ts = _os.path.getmtime(__file__)
        tr = _dt.datetime.utcfromtimestamp(ts) + _dt.timedelta(hours=3)
        return tr.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "?"

PANEL_VERSIYON = f"{_PANEL_VERSIYON_ANA}·b{PANEL_VERSIYON_BUILD}"
PANEL_VERSIYON_TARIH = _panel_tarih()

# Sistem bilesenleri - her biri kendi son guncellemesini tutar
# Damgada gosterilir, boylece tum sistemin durumu tek bakista gorulur
SISTEM_DURUM_VARSAYILAN = {
    "panel":  "v1.9.7",
    "arsiv":  "?",
    "ptf":    "?",
    "osos":   "?",
}
AY_KISA = ['Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara']

def _tarih_kisa(iso):
    """'2026-06-02' -> '2Haz'"""
    try:
        if not iso or len(iso) < 10:
            return "?"
        y, m, g = iso[:4], iso[5:7], iso[8:10]
        return f"{int(g)}{AY_KISA[int(m)-1]}"
    except:
        return "?"

def sistem_durum_hesapla():
    """Her panel acilisinda JSON dosyalarinin son tarihlerini cikarir. Cache: 60sn."""
    import datetime as _dt
    simdi = _dt.datetime.now().timestamp()
    if hasattr(sistem_durum_hesapla, '_cache'):
        ts, veri = sistem_durum_hesapla._cache
        if simdi - ts < 60:
            return veri

    durum = dict(SISTEM_DURUM_VARSAYILAN)
    try:
        osos = github_oku("2026_osos_endeks.json")
        if osos:
            tum_gunler = set()
            for ab in osos.values():
                tum_gunler.update((ab.get("veri") or {}).keys())
            if tum_gunler:
                durum["osos"] = _tarih_kisa(max(tum_gunler))
    except:
        pass

    try:
        ptf = github_oku("aylik_ptf.json")
        if ptf:
            tum_aygun = []
            for ay, gunler in ptf.items():
                for g in gunler.keys():
                    tum_aygun.append(f"{ay}-{g}")
            if tum_aygun:
                durum["ptf"] = _tarih_kisa(max(tum_aygun))
    except:
        pass

    try:
        bugun = _dt.date.today()
        for fark in range(2):
            tarih = bugun - _dt.timedelta(days=fark*30)
            ay_str = tarih.strftime("%Y-%m")
            arsiv = github_oku(f"arsiv_cihaz_{ay_str}.json")
            if arsiv:
                son = max(arsiv.keys())
                durum["arsiv"] = "v2 · " + _tarih_kisa(son[:10])
                break
    except:
        pass

    sistem_durum_hesapla._cache = (simdi, durum)
    return durum


KULLANICILAR = {
    "admin1":    {"sifre": hashlib.sha256("admin1".encode()).hexdigest(),    "rol": "yonetici"},
    "admin2":    {"sifre": hashlib.sha256("admin2".encode()).hexdigest(),    "rol": "yonetici"},
    "kullanici1":{"sifre": hashlib.sha256("kullanici1".encode()).hexdigest(),"rol": "izleyici"},
    "kullanici2":{"sifre": hashlib.sha256("kullanici2".encode()).hexdigest(),"rol": "izleyici"},
}

GITHUB_RAW   = "https://raw.githubusercontent.com/ekinciomer-ai/epias-ptf/main"
GITHUB_REPO  = "ekinciomer-ai/epias-ptf"
GH_TOKEN     = os.environ.get("GH_TOKEN", "")
F2POOL_TOKEN = os.environ.get("F2POOL_TOKEN", "")
F2POOL_USER  = "mehmetas"

# BTC fiyati: canli cekilir (CoinGecko), basarisizsa sinyal.json'daki son deger kullanilir.
import time as _btc_time
_btc_cache = {"ts": 0.0, "usd": 0.0, "try": 0.0}

def _btc_canli_cek():
    """Canli BTC fiyati (TL, USD). 2 dk cache. CoinGecko -> Binance -> (0,0)."""
    global _btc_cache
    if (_btc_time.time() - _btc_cache["ts"]) < 120 and _btc_cache["usd"]:
        return _btc_cache["try"], _btc_cache["usd"]
    # 1) CoinGecko (hem USD hem TRY tek cagri)
    try:
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,try",
            headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        usd = float(d["bitcoin"]["usd"]); tl = float(d["bitcoin"]["try"])
        if usd > 0 and tl > 0:
            _btc_cache = {"ts": _btc_time.time(), "usd": usd, "try": tl}
            return tl, usd
    except Exception as e:
        print("BTC CoinGecko hatasi:", e)
    # 2) Binance yedek (BTCUSDT × USDTTRY)
    try:
        h = {"User-Agent": "Mozilla/5.0"}
        u = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", headers=h), timeout=8).read())
        usd = float(u["price"])
        k = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://api.binance.com/api/v3/ticker/price?symbol=USDTTRY", headers=h), timeout=8).read())
        usdtry = float(k["price"])
        if usd > 0 and usdtry > 0:
            tl = usd * usdtry
            _btc_cache = {"ts": _btc_time.time(), "usd": usd, "try": tl}
            return tl, usd
    except Exception as e:
        print("BTC Binance hatasi:", e)
    return 0.0, 0.0

def _btc_kur_uygula(sinyal):
    """Once canli BTC fiyatini dener; basarisizsa sinyal.json'daki son degeri kullanir."""
    bt, bu = _btc_canli_cek()
    if bu and bt:
        return bt, bu
    btc_try = sinyal.get("btc_try", 0) if sinyal else 0
    btc_usd = sinyal.get("btc_usd", 0) if sinyal else 0
    return btc_try, btc_usd
ZARARLI_ESIK = 2200
DOGRULAMA_TOLERANS = 50  # kWh tolerans

MANIFEST = json.dumps({
    "name": "Otocoin", "short_name": "Otocoin",
    "start_url": "/", "display": "standalone",
    "background_color": "#050917", "theme_color": "#16a34a",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]
})

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="100" fill="#050917"/>
<polygon points="290,110 220,270 262,270 222,400 320,210 272,210 310,110" fill="#22c55e"/>
</svg>"""

def github_oku(dosya):
    """Public repo - ONCE CDN dene (token gerekmez), basarisizsa token ile API dene."""
    # 1. Once CDN (public repo, token gerekmiyor)
    try:
        with urllib.request.urlopen(f"{GITHUB_RAW}/{dosya}", timeout=15) as r:
            return json.loads(r.read())
    except:
        pass
    # 2. CDN basarisizsa ve token varsa, API ile dene
    if GH_TOKEN:
        try:
            import base64
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{dosya}"
            req = urllib.request.Request(api_url, headers={
                "Authorization": f"Bearer {GH_TOKEN}",
                "Accept": "application/vnd.github+json",
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
                icerik_b64 = data.get("content", "")
                if icerik_b64:
                    icerik = base64.b64decode(icerik_b64).decode("utf-8")
                    return json.loads(icerik)
        except:
            pass
    return None


def github_yaz(dosya, payload):
    """GitHub'a dosya yaz/guncelle."""
    if not GH_TOKEN:
        return False
    try:
        import base64
        content_json = json.dumps(payload, ensure_ascii=False, indent=2)
        content_b64 = base64.b64encode(content_json.encode("utf-8")).decode()
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{dosya}"
        # Mevcut SHA al
        sha = None
        try:
            req = urllib.request.Request(api_url, headers={
                "Authorization": f"Bearer {GH_TOKEN}",
                "Accept": "application/vnd.github+json",
            })
            with urllib.request.urlopen(req, timeout=3) as r:
                sha = json.loads(r.read()).get("sha")
        except:
            pass

        body = {
            "message": f"komut {datetime.datetime.now().strftime('%H:%M:%S')}",
            "content": content_b64,
        }
        if sha:
            body["sha"] = sha

        req = urllib.request.Request(
            api_url,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {GH_TOKEN}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
            method="PUT"
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status in (200, 201)
    except Exception as e:
        print(f"github_yaz hatasi ({dosya}): {e}")
        return False

def f2pool_post(endpoint, body):
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(f"https://api.f2pool.com/v2/{endpoint}",
            data=data, headers={"Content-Type":"application/json", "F2P-API-SECRET":F2POOL_TOKEN}, method="POST")
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())
    except:
        return None

def f2pool_legacy(path):
    try:
        req = urllib.request.Request(f"https://api.f2pool.com/{path}",
            headers={"F2P-API-SECRET":F2POOL_TOKEN})
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())
    except:
        return None

def f2pool_son_gunler(gun=30):
    now = datetime.datetime.now(datetime.timezone.utc)
    bas = int((now - datetime.timedelta(days=gun)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    bit = int(now.timestamp())
    result = f2pool_post("assets/transactions/list", {
        "currency": "bitcoin", "mining_user_name": F2POOL_USER,
        "type": "revenue", "start_time": bas, "end_time": bit
    })
    return result.get("transactions", []) if result else []

def f2pool_bugun_tahmini():
    result = f2pool_post("assets/balance", {
        "currency": "bitcoin", "mining_user_name": F2POOL_USER,
        "calculate_estimated_income": True
    })
    return result.get("balance_info", {}).get("estimated_today_income", 0) if result else 0

def f2pool_hashrate():
    result = f2pool_post("hash_rate/info", {
        "currency": "bitcoin", "mining_user_name": F2POOL_USER
    })
    if result:
        info = result.get("info", {})
        return {"anlik": info.get("hash_rate", 0)/1e12, "h1": info.get("h1_hash_rate", 0)/1e12, "h24": info.get("h24_hash_rate", 0)/1e12}
    return {"anlik": 0, "h1": 0, "h24": 0}

def f2pool_workers():
    result = f2pool_post("hash_rate/worker/list", {"currency": "bitcoin", "mining_user_name": F2POOL_USER})
    return result.get("workers", []) if result else []

def cihaz_durum(info):
    anlik = info.get("hash_rate", 0)
    h1 = info.get("h1_hash_rate", 0)
    h24 = info.get("h24_hash_rate", 0)
    if anlik > 0: return "calisiyor"
    elif h1 > 0: return "yavasliyor"
    elif h24 > 0: return "uyuyor"
    return "kapali"

LOGIN_HTML = """<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#16a34a"><link rel="manifest" href="/manifest.json"><title>Otocoin</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Inter',-apple-system,sans-serif;background:#050917;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;}
.card{background:linear-gradient(180deg,#0a0e1a 0%,#050917 100%);border:1px solid #1e293b;border-radius:28px;padding:40px 32px;width:100%;max-width:380px;}
.logo-wrap{text-align:center;margin-bottom:28px;}
.logo{width:80px;height:80px;background:linear-gradient(135deg,#16a34a,#22c55e,#4ade80);border-radius:22px;display:inline-flex;align-items:center;justify-content:center;font-size:42px;margin-bottom:14px;box-shadow:0 8px 30px rgba(34,197,94,0.5);}
h1{font-size:28px;font-weight:900;color:white;}
.alt{font-size:13px;color:#64748b;margin-top:6px;}
label{font-size:12px;color:#94a3b8;display:block;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;}
input{width:100%;padding:14px 16px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:14px;color:white;font-size:15px;margin-bottom:18px;outline:none;font-family:inherit;}
input:focus{border-color:#22c55e;}
button{width:100%;padding:15px;background:linear-gradient(135deg,#16a34a,#22c55e);color:white;border:none;border-radius:14px;font-size:15px;font-weight:800;cursor:pointer;font-family:inherit;}
.error{background:rgba(220,38,38,0.15);border:1px solid rgba(220,38,38,0.3);color:#fca5a5;padding:12px 16px;border-radius:12px;font-size:13px;margin-bottom:18px;text-align:center;}
</style></head><body>
<div class="card">
<div class="logo-wrap"><div class="logo">⚡</div><h1>Otocoin</h1><div class="alt">Aksaray Enerji Yönetim Sistemi</div></div>
{% if hata %}<div class="error">{{ hata }}</div>{% endif %}
<form method="POST" action="/giris">
<label>Kullanıcı Adı</label><input type="text" name="kullanici" autocomplete="username">
<label>Şifre</label><input type="password" name="sifre" autocomplete="current-password">
<button type="submit">Giriş Yap</button>
</form>
</div>
</body></html>"""
print("Bölüm 1 yazıldı")

PANEL_HTML = """<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#050917"><meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.json"><title>Otocoin</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
*{box-sizing:border-box;margin:0;padding:0;}
body{background:linear-gradient(180deg,#0a0e1a 0%,#050917 100%);font-family:'Inter',-apple-system,sans-serif;color:white;min-height:100vh;padding-bottom:20px;}
.header{padding:18px 20px 16px;padding-top:calc(18px + env(safe-area-inset-top));display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,0.06);background:rgba(10,14,26,0.9);backdrop-filter:blur(20px);position:sticky;top:0;z-index:100;}
.brand{display:flex;align-items:center;gap:10px;}
.brand-logo{width:38px;height:38px;background:linear-gradient(135deg,#16a34a,#22c55e,#4ade80);border-radius:11px;display:flex;align-items:center;justify-content:center;font-size:20px;box-shadow:0 4px 16px rgba(34,197,94,0.4);}
.brand-text{font-size:18px;font-weight:900;}
.user-pill{display:flex;align-items:center;gap:6px;background:rgba(255,255,255,0.05);padding:6px 10px;border-radius:20px;border:1px solid rgba(255,255,255,0.08);}
.user-avatar{width:22px;height:22px;background:linear-gradient(135deg,#3b82f6,#6366f1);border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-size:10px;font-weight:700;}
.user-name{color:#cbd5e1;font-size:11px;font-weight:600;}
.cikis-link{background:none;border:1px solid rgba(255,255,255,0.1);color:#f87171;padding:6px 12px;border-radius:10px;font-size:11px;cursor:pointer;margin-left:8px;text-decoration:none;}
.tabs{display:flex;padding:12px 20px 0;gap:6px;overflow-x:auto;border-bottom:1px solid rgba(255,255,255,0.04);background:rgba(10,14,26,0.7);backdrop-filter:blur(20px);position:sticky;top:73px;z-index:90;}
.tabs::-webkit-scrollbar{display:none;}
.tab{display:flex;align-items:center;gap:6px;padding:10px 14px;font-size:12px;font-weight:600;color:#64748b;border-bottom:2px solid transparent;white-space:nowrap;cursor:pointer;margin-bottom:-1px;}
.tab.active{color:#22c55e;border-bottom-color:#22c55e;}
.content{padding:16px 16px 24px;}
.status-card{background:linear-gradient(135deg,rgba(22,163,74,0.2) 0%,rgba(22,163,74,0.05) 100%);border:1px solid rgba(22,163,74,0.3);border-radius:20px;padding:18px;margin-bottom:14px;}
.status-card.zarar{background:linear-gradient(135deg,rgba(220,38,38,0.2) 0%,rgba(220,38,38,0.05) 100%);border-color:rgba(220,38,38,0.3);}
.status-card.gri{background:rgba(255,255,255,0.03);border-color:rgba(255,255,255,0.06);}
.status-row{display:flex;align-items:center;gap:14px;}
.status-icon{width:52px;height:52px;background:linear-gradient(135deg,#16a34a,#22c55e);border-radius:16px;display:flex;align-items:center;justify-content:center;font-size:26px;}
.status-card.zarar .status-icon{background:linear-gradient(135deg,#dc2626,#ef4444);}
.status-card.gri .status-icon{background:rgba(255,255,255,0.1);}
.status-title{font-size:18px;font-weight:900;}
.status-sub{color:rgba(255,255,255,0.6);font-size:11px;margin-top:2px;}
.kpi-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:14px;}
.kpi-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:14px;}
.kpi-card.highlight{background:linear-gradient(135deg,rgba(59,130,246,0.15) 0%,rgba(59,130,246,0.05) 100%);border-color:rgba(59,130,246,0.25);}
.kpi-label{font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;}
.kpi-value{font-size:22px;font-weight:900;}
.kpi-sub{font-size:11px;color:#94a3b8;margin-top:4px;}
.section-header{display:flex;align-items:center;justify-content:space-between;margin:14px 0 10px;}
.section-title{font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;}
.aylik-wrap{overflow-x:auto;margin-top:8px;border-radius:12px;border:1px solid rgba(255,255,255,0.06);background:#050917;}

/* YEKDEM AYLIK KARTLARI */
.yekdem-kart{background:rgba(255,255,255,0.02); border-radius:10px; padding:11px 12px; position:relative; transition:transform .15s ease;}
.yekdem-kart:hover{transform:translateY(-1px);}
.yekdem-kart .yk-ay{font-size:10px; color:#94a3b8; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px;}
.yekdem-kart .yk-deger{font-size:18px; font-weight:900; line-height:1; margin-bottom:3px; font-family:'Inter',monospace;}
.yekdem-kart .yk-birim{font-size:9px; color:#64748b; font-weight:600;}
.yekdem-kart .yk-not{font-size:9px; margin-top:6px; padding-top:6px; border-top:1px solid rgba(255,255,255,0.05); color:#64748b;}
.yekdem-kart.kesin{background:rgba(34,197,94,0.12); border:1px solid rgba(34,197,94,0.35);}
.yekdem-kart.kesin .yk-deger{color:#86efac;}
.yekdem-kart.ongoru{background:rgba(251,146,60,0.12); border:1px solid rgba(251,146,60,0.4);}
.yekdem-kart.ongoru .yk-deger{color:#fdba74;}
.yekdem-kart.tahmin{background:rgba(251,191,36,0.12); border:1px solid rgba(251,191,36,0.4);}
.yekdem-kart.tahmin .yk-deger{color:#fcd34d;}
.aylik-table{width:100%;border-collapse:collapse;font-size:10px;}
.aylik-table th{background:linear-gradient(180deg,#1e293b,#0f172a);color:#94a3b8;font-weight:700;font-size:9px;padding:8px 4px;text-align:center;position:sticky;top:0;z-index:2;}
.aylik-table th.saat-head{background:linear-gradient(180deg,#16a34a,#15803d);color:white;min-width:38px;position:sticky;left:0;z-index:3;}
.aylik-table td{padding:5px 3px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.06);font-weight:700;min-width:38px;background:#050917;}
.aylik-table td.saat-cell{background:#0a0e1a;font-weight:800;color:#4ade80;position:sticky;left:0;z-index:1;border-right:2px solid rgba(34,197,94,0.3);}
.aylik-table tr:nth-child(odd) td{background:rgba(255,255,255,0.015);}
.aylik-table tr:nth-child(odd) td.saat-cell{background:#0a0e1a;}
.l0{color:#4ade80;}
.l1{color:#86efac;}
.l2{color:#fbbf24;}
.l3{color:#fb923c;}
.l4{color:#f87171;}
.l5{color:#dc2626;font-weight:900;}
.aylik-table td.kapali-cell{color:#c4b5fd!important;background:linear-gradient(135deg,rgba(124,58,237,0.3),rgba(124,58,237,0.15))!important;border:1px solid rgba(168,85,247,0.6);font-weight:900;}
.fat-subtabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;}
.fat-subtab{flex:1;min-width:95px;padding:12px 14px;border-radius:12px;border:1.5px solid #e2e8f0;background:#fff;cursor:pointer;font-weight:800;font-size:13px;color:#64748b;text-align:center;transition:all .15s;display:flex;align-items:center;justify-content:center;gap:7px;}
.fat-subtab:hover{border-color:#cbd5e1;}
.fat-subtab.aktif.t1{border-color:#d97706;background:linear-gradient(135deg,rgba(217,119,6,0.1),rgba(245,158,11,0.05));color:#b45309;}
.fat-subtab.aktif.t2{border-color:#2563eb;background:linear-gradient(135deg,rgba(37,99,235,0.1),rgba(96,165,250,0.05));color:#1d4ed8;}
.fat-subtab.aktif.a3{border-color:#dc2626;background:linear-gradient(135deg,rgba(220,38,38,0.1),rgba(248,113,113,0.05));color:#b91c1c;}
.fat-abone-kart{background:#ffffff;border:1px solid #e2e8f0;border-radius:18px;padding:16px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.04);}
.fat-abone-kart.ty1{border-left:4px solid #d97706;}
.fat-abone-kart.ty2{border-left:4px solid #2563eb;}
.fat-abone-kart.aks3{border-left:4px solid #dc2626;}
.fat-abone-head{display:flex;align-items:center;gap:12px;padding-bottom:14px;border-bottom:1px solid #f1f5f9;margin-bottom:14px;}
.fat-abone-icon{width:44px;height:44px;border-radius:13px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;}
.fat-abone-kart.ty1 .fat-abone-icon{background:linear-gradient(135deg,#f59e0b,#fbbf24);}
.fat-abone-kart.ty2 .fat-abone-icon{background:linear-gradient(135deg,#3b82f6,#60a5fa);}
.fat-abone-kart.aks3 .fat-abone-icon{background:linear-gradient(135deg,#dc2626,#f87171);}
.fat-abone-name{font-size:16px;font-weight:900;line-height:1.2;color:#1e293b;}
.fat-abone-sub{font-size:11px;color:#64748b;margin-top:2px;font-weight:600;}
.fat-bolum-baslik{font-size:10px;font-weight:800;color:#64748b;text-transform:uppercase;letter-spacing:1.2px;margin:14px 0 8px;}
.fat-bilgi-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;}
.fat-bilgi-row{background:#f8fafc;border-radius:10px;padding:9px 11px;border:1px solid #f1f5f9;}
.fat-bilgi-lbl{font-size:9px;color:#94a3b8;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;}
.fat-bilgi-val{font-size:13px;font-weight:800;margin-top:2px;color:#1e293b;}
.fat-ozet-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;}
.fat-ozet-card{border-radius:12px;padding:11px 8px;text-align:center;border:1px solid;}
.fat-ozet-card.ham{background:linear-gradient(135deg,rgba(220,38,38,0.08),rgba(220,38,38,0.02));border-color:rgba(220,38,38,0.25);}
.fat-ozet-card.mhs{background:linear-gradient(135deg,rgba(124,58,237,0.08),rgba(124,58,237,0.02));border-color:rgba(124,58,237,0.25);}
.fat-ozet-card.snr{background:linear-gradient(135deg,rgba(217,119,6,0.1),rgba(217,119,6,0.03));border-color:rgba(217,119,6,0.3);}
.fat-ozet-lbl{font-size:9px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;}
.fat-ozet-val{font-size:16px;font-weight:900;letter-spacing:-0.3px;}
.fat-ozet-card.ham .fat-ozet-val{color:#dc2626;}
.fat-ozet-card.mhs .fat-ozet-val{color:#7c3aed;}
.fat-ozet-card.snr .fat-ozet-val{color:#d97706;}
.fat-ozet-unit{font-size:9px;color:#94a3b8;font-weight:700;margin-top:2px;}
.fat-mal-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;}
.fat-mal-card{background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:11px 12px;}
.fat-mal-lbl{font-size:9px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;}
.fat-mal-val{font-size:17px;font-weight:900;margin-top:4px;color:#16a34a;}
.fat-mal-sub{font-size:10px;color:#94a3b8;margin-top:3px;font-weight:600;}
.fat-tablo-wrap{overflow-x:auto;overflow-y:visible;margin-top:8px;border-radius:12px;border:1px solid #e2e8f0;background:#ffffff;}
.fat-table{width:100%;border-collapse:collapse;font-size:11px;}
.fat-table th{background:#f1f5f9;color:#64748b;font-weight:800;font-size:9px;padding:10px 6px;text-align:center;text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;}
.fat-table th:first-child{text-align:left;padding-left:14px;}
.fat-table td{padding:9px 6px;text-align:right;border-bottom:1px solid #f1f5f9;font-weight:700;white-space:nowrap;}
.fat-table td:first-child{text-align:left;padding-left:14px;color:#475569;font-weight:800;}
.fat-table tr.fat-gun-satir{cursor:pointer;transition:background 0.15s;}
.fat-table tr.fat-gun-satir:hover td{background:#f8fafc;}
.fat-table tr.fat-gun-satir.acik td{background:rgba(22,163,74,0.06);}
.fat-table tr.fat-gun-satir.acik td:first-child{color:#16a34a;}
.fat-table tr.fat-toplam td{background:linear-gradient(180deg,rgba(217,119,6,0.1),rgba(217,119,6,0.03));font-weight:900;border-top:2px solid rgba(217,119,6,0.3);color:#d97706;font-size:12px;}
.fat-table tr.fat-toplam td.fat-hover-cell{color:#b45309;}
.fat-table tr.fat-toplam td.fat-col-mal{color:#16a34a;}
.fat-table tr.fat-toplam td.fat-col-tutar{color:#d97706;}
.fat-table td.fat-col-ham{color:#dc2626;}
.fat-table td.fat-col-mhs{color:#7c3aed;}
.fat-table td.fat-col-snr{color:#d97706;font-weight:800;}
.fat-table td.fat-col-mal{color:#16a34a;}
.fat-table td.fat-col-ptf{color:#2563eb;}
.fat-expand-ico{display:inline-block;margin-right:5px;font-size:9px;color:#94a3b8;transition:transform 0.2s;}
tr.acik .fat-expand-ico{transform:rotate(90deg);color:#16a34a;}
.fat-saatlik-row{display:none;}
.fat-saatlik-row.acik{display:table-row;}
.fat-saatlik-row td{padding:0;background:#f8fafc;overflow:visible;}
.fat-saatlik-icerik{padding:10px 12px;background:linear-gradient(180deg,rgba(22,163,74,0.04),transparent);border-top:1px dashed rgba(22,163,74,0.2);border-bottom:1px dashed rgba(22,163,74,0.2);overflow:visible;}
.fat-saatlik-icerik table{width:100%;border-collapse:collapse;font-size:10px;overflow:visible;}
.fat-saatlik-icerik th{font-size:8px;color:#94a3b8;padding:6px 5px;text-align:right;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid #e2e8f0;}
.fat-saatlik-icerik th:first-child{text-align:left;}
.fat-saatlik-icerik td{padding:5px;text-align:right;border-bottom:1px solid #f1f5f9;font-weight:700;color:#475569;background:transparent;}
.fat-saatlik-icerik td:first-child{text-align:left;color:#16a34a;font-weight:800;}
.fat-saatlik-icerik tr.gun-tpl td{background:rgba(217,119,6,0.07);color:#d97706;font-weight:900;border-top:1px solid rgba(217,119,6,0.25);}
.fat-tutar-card{background:linear-gradient(135deg,rgba(217,119,6,0.1),rgba(245,158,11,0.03));border:1px solid rgba(217,119,6,0.3);border-radius:14px;padding:14px 16px;text-align:center;}
.fat-tutar-lbl{font-size:10px;color:#d97706;font-weight:800;text-transform:uppercase;letter-spacing:1px;}
.fat-tutar-val{font-size:24px;font-weight:900;color:#b45309;margin-top:6px;letter-spacing:-0.5px;}
.fat-tutar-sub{font-size:10px;color:#94a3b8;margin-top:4px;font-weight:600;}
.fat-table td.fat-col-tutar{color:#d97706;font-weight:800;}
.fat-table td.fat-col-mhsmal{color:#7c3aed;}
.fat-table td.fat-col-tukbed{color:#16a34a;}
.fat-table td.fat-col-mhsbed{color:#dc2626;}
.fat-table td.fat-col-toplam{color:#d97706;font-weight:800;}
.fat-fatura-card{background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;padding:14px;}
.fat-kalem{padding:10px 12px;background:#f8fafc;border-radius:10px;margin-bottom:10px;border:1px solid #f1f5f9;}
.fat-kalem:last-child{margin-bottom:0;}
.fat-kalem-baslik{font-size:12px;font-weight:800;color:#1e293b;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #e2e8f0;}
.fat-kalem-formul{display:flex;justify-content:space-between;align-items:center;font-size:11px;color:#64748b;padding:4px 0;font-weight:600;}
.fat-kalem-formul span:last-child{color:#475569;font-weight:700;font-family:'Inter',monospace;}
.fat-kalem-toplam{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:#16a34a;padding:6px 0 4px;margin-top:4px;border-top:1px dashed rgba(22,163,74,0.25);font-weight:800;}
.fat-kalem-toplam span:last-child{font-weight:900;font-family:'Inter',monospace;letter-spacing:-0.2px;}
.fat-odenecek{background:linear-gradient(135deg,rgba(22,163,74,0.1),rgba(22,163,74,0.03));border:1.5px solid rgba(22,163,74,0.35);border-radius:12px;padding:14px 16px;margin-top:12px;text-align:center;}
.fat-odenecek-lbl{font-size:10px;color:#16a34a;font-weight:800;text-transform:uppercase;letter-spacing:1.2px;}
.fat-odenecek-val{font-size:26px;font-weight:900;color:#15803d;margin-top:6px;letter-spacing:-0.5px;font-family:'Inter',monospace;}
.fat-saat-tr{cursor:pointer;transition:background 0.15s;}
.fat-saat-tr:hover td{background:rgba(22,163,74,0.05)!important;}
.fat-saat-tr.acik td{background:rgba(22,163,74,0.1)!important;color:#16a34a;}
.fat-saat-ico{display:inline-block;margin-right:5px;font-size:8px;color:#94a3b8;transition:transform 0.2s;}
.fat-saat-tr.acik .fat-saat-ico{transform:rotate(90deg);color:#16a34a;}
.fat-saat-detay-row{display:none;}
.fat-saat-detay-row.acik{display:table-row;}
.fat-saat-detay-row td{padding:0;background:#f8fafc;}
.fat-saat-detay-yatay{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:10px;background:linear-gradient(180deg,rgba(22,163,74,0.04),transparent);border-top:1px dashed rgba(22,163,74,0.2);border-bottom:1px dashed rgba(22,163,74,0.2);}
.fat-detay-kutu{background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;}
.fat-detay-kutu.mal{border-left:3px solid #16a34a;}
.fat-detay-kutu.mhsind{border-left:3px solid #7c3aed;}
.fat-detay-kutu.tutar{border-left:3px solid #d97706;}
.fat-detay-baslik{font-size:9px;font-weight:800;color:#64748b;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;padding-bottom:4px;border-bottom:1px solid #f1f5f9;}
.fat-detay-row{display:flex;justify-content:space-between;align-items:center;font-size:10px;padding:2px 0;gap:6px;}
.fat-detay-row span:first-child{color:#64748b;font-weight:600;}
.fat-detay-row span:last-child{color:#1e293b;font-weight:800;font-family:'Inter',monospace;}
.fat-detay-sonuc{display:flex;justify-content:space-between;align-items:center;padding:5px 0 2px;margin-top:5px;border-top:1px solid #e2e8f0;font-size:11px;font-weight:900;}
.fat-detay-kutu.mal .fat-detay-sonuc{color:#16a34a;}
.fat-detay-kutu.mhsind .fat-detay-sonuc{color:#dc2626;}
.fat-detay-kutu.tutar .fat-detay-sonuc{color:#d97706;}
.fat-detay-sonuc span:last-child{font-family:'Inter',monospace;}
.fat-saat-tbl td.fat-col-mhsind{color:#7c3aed;font-weight:700;}
/* Fatura Ozet Karti */
.fat-fatura-ozet{background:linear-gradient(135deg,rgba(22,163,74,0.05),rgba(22,163,74,0.01));border:1px solid rgba(22,163,74,0.18);border-radius:14px;padding:14px 16px;margin:14px 0 18px;}
.fat-fo-title{font-size:11px;font-weight:800;color:#16a34a;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid rgba(22,163,74,0.18);}
.fat-fo-row{display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid #f1f5f9;gap:12px;}
.fat-fo-row:last-of-type{border-bottom:none;}
.fat-fo-row.toplam{background:rgba(217,119,6,0.07);border:1px solid rgba(217,119,6,0.25);border-radius:8px;padding:9px 12px;margin:6px 0;color:#d97706;}
.fat-fo-lbl{font-size:12px;color:#475569;font-weight:700;flex:1;}
.fat-fo-no{color:#94a3b8;font-weight:800;margin-right:4px;}
.fat-fo-aciklama{color:#94a3b8;font-size:10px;font-weight:600;margin-left:6px;}
.fat-fo-val{font-size:13px;font-weight:800;color:#1e293b;font-family:'Inter',monospace;white-space:nowrap;}
.fat-fo-val.negatif{color:#dc2626;}
.fat-fo-tl{font-size:10px;color:#94a3b8;font-weight:700;margin-left:2px;}
.fat-fo-odenecek{background:linear-gradient(135deg,rgba(22,163,74,0.1),rgba(22,163,74,0.03));border:1.5px solid rgba(22,163,74,0.4);border-radius:12px;padding:14px 16px;margin-top:12px;display:flex;justify-content:space-between;align-items:center;gap:12px;}
.fat-fo-od-lbl{font-size:11px;font-weight:800;color:#16a34a;text-transform:uppercase;letter-spacing:1.1px;}
.fat-fo-od-val{font-size:24px;font-weight:900;color:#15803d;letter-spacing:-0.5px;font-family:'Inter',monospace;}
.fat-detay-lbl{font-size:11px;font-weight:800;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin:18px 0 8px;}
/* Tuketim Detayi karti */
.fat-tuketim-detay{background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:14px 16px;margin:14px 0;}
.fat-td-title{font-size:11px;font-weight:800;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid #e2e8f0;}
.fat-td-grid{display:flex;flex-direction:column;gap:6px;}
.fat-td-row{display:flex;justify-content:space-between;align-items:center;padding:6px 10px;border-radius:8px;background:#ffffff;font-size:12px;font-weight:700;border:1px solid #f1f5f9;}
.fat-td-row.sonra{background:linear-gradient(135deg,rgba(217,119,6,0.1),rgba(217,119,6,0.03));border:1px solid rgba(217,119,6,0.3);margin-top:4px;padding:9px 12px;}
.fat-td-lbl{color:#475569;}
.fat-td-val{font-weight:900;font-family:'Inter',monospace;font-size:13px;}
.fat-td-val.ham{color:#dc2626;}
.fat-td-val.mhs{color:#7c3aed;}
.fat-td-val.snr{color:#d97706;font-size:15px;}
/* Uretim detayi (GES T1/T2) - yesil tema, asil is vurgusu */
.fat-uretim-detay{background:linear-gradient(135deg,rgba(22,163,74,0.06),rgba(22,163,74,0.01));border:1px solid rgba(22,163,74,0.25);border-radius:14px;padding:14px 16px;margin:14px 0;}
.fat-ud-title{font-size:11px;font-weight:800;color:#16a34a;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid rgba(22,163,74,0.2);}
.fat-ud-grid{display:flex;flex-direction:column;gap:6px;}
.fat-ud-row{display:flex;justify-content:space-between;align-items:center;padding:6px 10px;border-radius:8px;background:#ffffff;font-size:12px;font-weight:700;border:1px solid rgba(22,163,74,0.1);}
.fat-ud-row.sebeke{background:linear-gradient(135deg,rgba(22,163,74,0.12),rgba(22,163,74,0.03));border:1px solid rgba(22,163,74,0.35);margin-top:4px;padding:9px 12px;}
.fat-ud-lbl{color:#475569;}
.fat-ud-val{font-weight:900;font-family:'Inter',monospace;font-size:13px;}
.fat-ud-val.uret{color:#16a34a;}
.fat-ud-val.mhsk{color:#7c3aed;}
.fat-ud-val.sat{color:#16a34a;font-size:15px;}
/* Uretim faturasi (GES) - yesil tema */
.fat-uretim-fatura{background:linear-gradient(135deg,rgba(22,163,74,0.07),rgba(22,163,74,0.02));border:1.5px solid rgba(22,163,74,0.3);border-radius:16px;padding:16px;margin:16px 0;}
.fat-uf-baslik{font-size:13px;font-weight:900;color:#16a34a;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;text-align:center;padding-bottom:8px;border-bottom:1px solid rgba(22,163,74,0.2);}
.fat-uf-net{display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding:12px 14px;background:#fff;border-radius:12px;border:1.5px solid rgba(22,163,74,0.3);}
.fat-uf-net-lbl{font-size:12px;font-weight:800;color:#475569;}
.fat-uf-net-val{font-size:20px;font-weight:900;font-family:'Inter',monospace;}
/* Fatura alt satiri - kalem detay (Ham × Birim Fiyat) */
.fat-fo-altrow{display:flex;justify-content:space-between;align-items:center;padding:3px 0 9px;border-bottom:1px solid #f1f5f9;margin-bottom:2px;}
.fat-fo-altlbl{font-size:10px;color:#64748b;font-weight:700;font-family:'Inter',monospace;letter-spacing:0.2px;}
.fat-fo-altaciklama{font-size:9px;color:#94a3b8;font-weight:600;font-style:italic;}
/* Hover Popup - tiklanabilir hesap detayi */
.fat-hover-cell{position:relative;cursor:help;}
.fat-hover-cell:hover{background:rgba(22,163,74,0.08)!important;}
.fat-yekdem-cell:hover #fat-yekdem-popup{display:block;}
.fat-popup{display:none;position:absolute;top:calc(100% + 8px);left:50%;transform:translateX(-50%);min-width:200px;background:#ffffff;border:1px solid #cbd5e1;border-radius:10px;padding:10px 12px;box-shadow:0 8px 28px rgba(15,23,42,0.18);z-index:9999;text-align:left;white-space:nowrap;pointer-events:none;}
.fat-popup.yukari{top:auto;bottom:calc(100% + 8px);}
.fat-popup.mor{border-color:rgba(124,58,237,0.4);}
.fat-popup.sari{border-color:rgba(217,119,6,0.4);}
.fat-popup.turuncu{border-color:rgba(234,88,12,0.4);}
.fat-popup.kirmizi{border-color:rgba(220,38,38,0.4);}
.fat-popup-aciklama{font-size:9px;color:#94a3b8;font-style:italic;margin-top:6px;padding-top:6px;border-top:1px solid #f1f5f9;text-align:center;}
/* Fayda analizi (GES) */
.fat-fayda{background:linear-gradient(135deg,rgba(37,99,235,0.06),rgba(37,99,235,0.01));border:1.5px solid rgba(37,99,235,0.25);border-radius:16px;padding:16px;margin:16px 0;}
.fat-fayda-baslik{font-size:13px;font-weight:900;color:#2563eb;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;text-align:center;padding-bottom:8px;border-bottom:1px solid rgba(37,99,235,0.2);}
.fat-fayda-row{display:flex;justify-content:space-between;align-items:center;padding:9px 12px;border-radius:10px;background:#fff;font-size:12px;font-weight:700;border:1px solid #eef2f6;margin-bottom:6px;position:relative;cursor:help;}
.fat-fayda-lbl{color:#475569;}
.fat-fayda-val{font-weight:900;font-family:'Inter',monospace;font-size:13px;}
.fat-fayda-toplam{display:flex;justify-content:space-between;align-items:center;margin-top:10px;padding:13px 14px;background:#fff;border-radius:12px;border:1.5px solid rgba(37,99,235,0.35);}
.fat-fayda-top-lbl{font-size:12px;font-weight:800;color:#1e293b;}
.fat-fayda-top-val{font-size:21px;font-weight:900;font-family:'Inter',monospace;}
.fat-popup::after{content:'';position:absolute;bottom:100%;left:50%;transform:translateX(-50%);border:6px solid transparent;border-bottom-color:#ffffff;}
.fat-popup.yukari::after{bottom:auto;top:100%;border-bottom-color:transparent;border-top-color:#ffffff;}
.fat-popup.mor::after{border-bottom-color:#ffffff;}
.fat-popup.mor.yukari::after{border-bottom-color:transparent;border-top-color:#ffffff;}
.fat-popup.sari::after{border-bottom-color:#ffffff;}
.fat-popup.sari.yukari::after{border-bottom-color:transparent;border-top-color:#ffffff;}
.fat-popup.turuncu::after{border-bottom-color:#ffffff;}
.fat-popup.turuncu.yukari::after{border-bottom-color:transparent;border-top-color:#ffffff;}
.fat-hover-cell:hover .fat-popup{display:block;}
.fat-popup-title{font-size:10px;font-weight:800;color:#16a34a;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;padding-bottom:5px;border-bottom:1px solid rgba(22,163,74,0.2);}
.fat-popup-title.mor{color:#7c3aed;border-bottom-color:rgba(124,58,237,0.2);}
.fat-popup-title.sari{color:#d97706;border-bottom-color:rgba(217,119,6,0.2);}
.fat-popup-row{display:flex;justify-content:space-between;align-items:center;font-size:11px;padding:2px 0;gap:14px;}
.fat-popup-row span:first-child{color:#64748b;font-weight:600;}
.fat-popup-row span:last-child{color:#1e293b;font-weight:800;font-family:'Inter',monospace;}
.fat-popup-row.sum{border-top:1px dashed #e2e8f0;padding-top:4px;margin-top:2px;}
.fat-popup-sonuc{display:flex;justify-content:space-between;align-items:center;padding:5px 0 2px;margin-top:5px;border-top:1px solid rgba(22,163,74,0.3);font-size:12px;font-weight:900;gap:14px;color:#16a34a;}
.fat-popup-sonuc.mor{color:#7c3aed;border-top-color:rgba(124,58,237,0.3);}
.fat-popup-sonuc.sari{color:#d97706;border-top-color:rgba(217,119,6,0.3);}
.fat-popup-sonuc span:last-child{font-family:'Inter',monospace;}
.f2-summary{background:linear-gradient(135deg,rgba(245,158,11,0.15) 0%,rgba(245,158,11,0.05) 100%);border:1px solid rgba(245,158,11,0.25);border-radius:18px;padding:16px;margin-bottom:14px;}
.f2-icon-wrap{display:flex;align-items:center;gap:12px;margin-bottom:12px;}
.f2-icon{width:44px;height:44px;background:linear-gradient(135deg,#f59e0b,#fbbf24);border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:22px;}
.f2-title{font-size:15px;font-weight:800;}
.f2-subtitle{color:#94a3b8;font-size:11px;margin-top:1px;}
.f2-big{font-size:26px;font-weight:900;}
.f2-big span{color:#fbbf24;}
.f2-small{font-size:12px;color:#94a3b8;margin-top:2px;}
/* F2Pool derli toplu tasarim */
.f2-hero{display:flex;justify-content:space-between;align-items:center;gap:12px;background:linear-gradient(135deg,#f59e0b,#d97706);border-radius:16px;padding:16px 18px;margin-bottom:14px;box-shadow:0 4px 16px rgba(217,119,6,0.25);}
/* F2Pool alt sekmeler */
.f2-alt-tabs{display:flex;gap:4px;background:#fff;border-radius:12px;padding:4px;margin-bottom:14px;border:1px solid #e2e8f0;}
.f2-alt-tab{flex:1;background:transparent;border:none;color:#64748b;padding:9px 8px;border-radius:9px;font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;transition:all 0.15s;}
.f2-alt-tab.active{background:#d97706;color:#fff;}
.f2-alt-content{display:none;}
.f2-alt-content.active{display:block;}
/* Kiyas */
.f2-kiyas-aciklama{font-size:11px;color:#64748b;background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;margin-bottom:12px;line-height:1.5;}
.f2-kiyas-zaman{background:transparent;border:none;color:#64748b;padding:6px 13px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;}
.f2-kiyas-zaman.active{background:#d97706;color:#fff;}
.f2-kiyas-ozet{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:14px;}
.f2-kiyas-kart{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04);}
.f2-kiyas-kart-lbl{font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;}
.f2-kiyas-kart-val{font-size:17px;font-weight:900;margin-top:4px;font-family:'Inter',monospace;}
.f2-kiyas-kart-sub{font-size:9px;color:#94a3b8;font-weight:600;margin-top:2px;}
.f2-harita-card{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,0.04);}
.f2-harita-baslik{font-size:12px;font-weight:800;color:#1e293b;margin-bottom:12px;}
.f2-harita-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:3px;}
.f2-harita-saat{aspect-ratio:1;border-radius:5px;display:flex;align-items:center;justify-content:center;font-size:8px;font-weight:800;color:#fff;cursor:help;position:relative;}
.f2-harita-lejant{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-top:12px;padding-top:10px;border-top:1px solid #f1f5f9;}
.f2-hl{display:flex;align-items:center;gap:4px;font-size:9px;font-weight:700;color:#64748b;}
.f2-hl-renk{width:10px;height:10px;border-radius:3px;display:inline-block;}
.f2-kiyas-row{display:flex;align-items:center;gap:8px;background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:9px 12px;margin-bottom:5px;font-size:11px;position:relative;cursor:help;}
.f2-kiyas-saat{font-weight:800;color:#1e293b;min-width:42px;}
.f2-kiyas-net{margin-left:auto;font-weight:900;font-family:'Inter',monospace;}
.f2-hero-left{display:flex;align-items:center;gap:13px;}
.f2-hero-ico{width:46px;height:46px;background:rgba(255,255,255,0.2);border-radius:13px;display:flex;align-items:center;justify-content:center;font-size:24px;flex-shrink:0;}
.f2-hero-lbl{font-size:11px;color:rgba(255,255,255,0.85);font-weight:700;text-transform:uppercase;letter-spacing:0.5px;}
.f2-hero-btc{font-size:25px;font-weight:900;color:#fff;line-height:1.1;margin-top:2px;}
.f2-hero-btc span{font-size:14px;opacity:0.85;}
.f2-hero-right{text-align:right;}
.f2-hero-tl{font-size:19px;font-weight:900;color:#fff;}
.f2-hero-sub{font-size:11px;color:rgba(255,255,255,0.8);font-weight:600;margin-top:2px;}
.f2-kontrol{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap;}
.f2-zaman-grup{display:flex;gap:3px;background:#f1f5f9;border-radius:10px;padding:3px;border:1px solid #e2e8f0;}
.f2-ay-sec{margin-left:auto;background:#fff;border:1px solid #cbd5e1;color:#1e293b;padding:8px 12px;border-radius:9px;font-size:12px;font-weight:700;font-family:inherit;cursor:pointer;}
.f2-chart-card{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:14px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04);}
.f2-chart-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px;}
.f2-chart-baslik{font-size:13px;font-weight:800;color:#1e293b;}
.f2-metric-grup{display:flex;gap:4px;}
.f2-lejant{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-top:10px;padding-top:10px;border-top:1px solid #f1f5f9;}
.f2-lej{display:flex;align-items:center;gap:5px;font-size:10px;font-weight:700;color:#64748b;}
.f2-lej-renk{width:11px;height:11px;border-radius:3px;display:inline-block;}
/* Drill-down: gun -> saat -> cihaz */
.f2-gun-ok{display:inline-block;font-size:8px;color:#94a3b8;transition:transform 0.2s;margin-right:3px;}
.f2-saat-konteyner{margin:0 0 6px;}
.f2-saat-yukleniyor,.f2-saat-bos,.f2-cihaz-bos{padding:14px;text-align:center;color:#94a3b8;font-size:11px;background:#fff;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:6px;}
.f2-saat-tablo{background:#fff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;margin-bottom:6px;}
.f2-saat-row{display:grid;grid-template-columns:1fr 1.1fr 1fr 1fr 0.6fr;gap:6px;padding:8px 11px;font-size:11px;align-items:center;border-bottom:1px solid #f1f5f9;}
.f2-saat-row span{text-align:right;}
.f2-saat-row span:first-child{text-align:left;}
.f2-saat-head{background:#f1f5f9;font-size:9px;font-weight:800;color:#64748b;text-transform:uppercase;letter-spacing:0.3px;}
.f2-saat-tikla{cursor:pointer;transition:background 0.12s;}
.f2-saat-tikla:hover{background:#f8fafc;}
.f2-saat-no{font-weight:800;color:#1e293b;}
.f2-saat-ok{display:inline-block;font-size:7px;color:#94a3b8;margin-right:4px;}
.f2-saat-row small{font-size:8px;color:#94a3b8;font-weight:600;}
.f2-cihaz-liste{background:#f8fafc;border-left:2px solid #2563eb;}
.f2-cihaz-satir{display:grid;grid-template-columns:2fr 1fr 1fr;gap:6px;padding:6px 11px 6px 22px;font-size:10px;align-items:center;border-bottom:1px solid #eef2f6;}
.f2-cihaz-satir span{text-align:right;}
.f2-cihaz-ad{text-align:left!important;color:#475569;font-weight:700;}
.f2-cihaz-ad small{color:#94a3b8;font-weight:600;}
.f2-kpi-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px;}
.f2-kpi{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:11px 10px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,0.04);}
.f2-kpi-lbl{font-size:9px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.4px;}
.f2-kpi-val{font-size:18px;font-weight:900;margin:4px 0 2px;letter-spacing:-0.3px;}
.f2-kpi-sub{font-size:9px;color:#94a3b8;font-weight:600;}
.daily-item{display:flex;align-items:center;gap:12px;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px;margin-bottom:6px;}
.daily-date{font-size:11px;color:#64748b;font-weight:600;min-width:80px;}
.daily-btc{font-size:13px;font-weight:800;color:#1e293b;}
.daily-hash{font-size:10px;color:#94a3b8;margin-top:1px;}
.daily-tl{margin-left:auto;text-align:right;}
.daily-tl-val{font-size:13px;font-weight:800;color:#16a34a;}
.f2-zaman-btn{background:transparent;border:none;color:#64748b;padding:6px 13px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;transition:all 0.15s;}
.f2-zaman-btn.active{background:#d97706;color:#fff;}
.f2-metric-btn{background:#f1f5f9;border:1px solid #e2e8f0;color:#64748b;padding:5px 10px;border-radius:7px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;transition:all 0.15s;}
.f2-metric-btn.active{background:#2563eb;border-color:#2563eb;color:#fff;}
.f2-hafta-baslik{font-size:11px;font-weight:800;color:#d97706;margin:14px 0 6px;padding:7px 11px;background:rgba(217,119,6,0.08);border-radius:8px;border-left:3px solid #d97706;}
.f2-hafta-ozet{font-size:10px;color:#64748b;font-weight:600;margin-left:auto;}
.cihaz-ozet{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:12px;}
.cihaz-ozet-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:10px 6px;text-align:center;}
.cihaz-ozet-val{font-size:18px;font-weight:900;}
.cihaz-ozet-lbl{font-size:9px;color:#64748b;margin-top:2px;text-transform:uppercase;letter-spacing:0.5px;font-weight:700;}
.cihaz-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;}
.cihaz-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:12px;cursor:pointer;border-left:3px solid #22c55e;}
.cihaz-card:active{transform:scale(0.97);}
.cihaz-card.uyuyor{border-left-color:#fbbf24;}
.cihaz-card.yavasliyor{border-left-color:#f59e0b;}
.cihaz-card.kapali{border-left-color:#ef4444;opacity:0.7;}
.cihaz-row1{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;}
.cihaz-no{font-size:18px;font-weight:900;}
.cihaz-badge{font-size:9px;font-weight:700;padding:3px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:0.5px;}
.badge-on{background:rgba(34,197,94,0.15);color:#4ade80;}
.badge-slow{background:rgba(245,158,11,0.15);color:#fbbf24;}
.badge-sleep{background:rgba(245,158,11,0.1);color:#fcd34d;}
.badge-off{background:rgba(239,68,68,0.15);color:#f87171;}
.cihaz-hash{font-size:14px;font-weight:800;color:#60a5fa;}
.cihaz-sub{font-size:10px;color:#64748b;margin-top:2px;}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.85);backdrop-filter:blur(8px);z-index:200;display:none;align-items:center;justify-content:center;padding:20px;}
.modal-overlay.active{display:flex;}
.modal{background:linear-gradient(180deg,#0a0e1a,#050917);border:1px solid #1e293b;border-radius:24px;padding:24px;width:100%;max-width:500px;max-height:90vh;overflow-y:auto;position:relative;}
.modal-close{position:absolute;top:12px;right:12px;width:32px;height:32px;background:rgba(255,255,255,0.05);border:none;border-radius:50%;color:white;font-size:18px;cursor:pointer;}
.modal-header{display:flex;align-items:center;gap:14px;margin-bottom:18px;}
.modal-icon{width:50px;height:50px;background:linear-gradient(135deg,#3b82f6,#6366f1);border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:24px;}
.modal-title{font-size:22px;font-weight:900;}
.modal-sub{font-size:11px;color:#94a3b8;margin-top:2px;}
.modal-stats{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:14px;}
.modal-stat{background:rgba(255,255,255,0.03);border-radius:10px;padding:10px;}
.modal-stat-lbl{font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;font-weight:700;margin-bottom:4px;}
.modal-stat-val{font-size:16px;font-weight:900;}
.modal-stat-sub{font-size:10px;color:#94a3b8;margin-top:2px;}
.chart-wrap{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:14px;position:relative;}
.chart-title{font-size:11px;color:#94a3b8;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;}
.chart-canvas{width:100%;height:200px;display:block;}
.tooltip{position:absolute;background:rgba(0,0,0,0.9);border:1px solid rgba(34,197,94,0.5);border-radius:8px;padding:6px 10px;font-size:11px;pointer-events:none;display:none;z-index:10;}
.tooltip-time{color:#94a3b8;font-size:9px;}
.tooltip-val{color:#4ade80;font-weight:800;font-size:13px;}

/* OSOS */
.osos-tabs{display:flex;gap:6px;background:rgba(255,255,255,0.04);padding:4px;border-radius:12px;margin-bottom:14px;overflow-x:auto;}
.osos-tabs::-webkit-scrollbar{display:none;}
.osos-tab{flex:1;min-width:90px;padding:10px 12px;font-size:11px;font-weight:700;color:#64748b;border:none;background:transparent;border-radius:8px;cursor:pointer;font-family:inherit;white-space:nowrap;}
.osos-tab.active{background:linear-gradient(135deg,#16a34a,#22c55e);color:white;}
.osos-info{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:14px;padding:14px;margin-bottom:12px;display:flex;align-items:center;gap:12px;}
.osos-info-ico{width:46px;height:46px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:24px;}
.osos-info.ges .osos-info-ico{background:linear-gradient(135deg,#f59e0b,#fbbf24);}
.osos-info.tuketim .osos-info-ico{background:linear-gradient(135deg,#dc2626,#ef4444);}
.osos-info.karma .osos-info-ico{background:linear-gradient(135deg,#7c3aed,#a78bfa);}
.osos-info-title{font-size:16px;font-weight:900;}
.osos-info-sub{font-size:11px;color:#94a3b8;margin-top:2px;}
.osos-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px;}
.osos-stat{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:12px 10px;text-align:center;}
.osos-stat-lbl{font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;font-weight:700;margin-bottom:4px;}
.osos-stat-val{font-size:18px;font-weight:900;}
.osos-stat-sub{font-size:10px;color:#94a3b8;margin-top:2px;}
.osos-section-tabs{display:flex;gap:4px;background:rgba(0,0,0,0.3);padding:4px;border-radius:10px;margin:14px 0 12px;}
.osos-sec-tab{flex:1;padding:8px 12px;font-size:11px;font-weight:700;color:#64748b;border:none;background:transparent;border-radius:8px;cursor:pointer;font-family:inherit;}
.osos-sec-tab.active{background:linear-gradient(135deg,#3b82f6,#6366f1);color:white;}
.osos-day-list{display:flex;gap:6px;overflow-x:auto;padding:4px 0 12px;margin-bottom:12px;}
.osos-day-list::-webkit-scrollbar{display:none;}
.osos-day-btn{padding:8px 12px;font-size:11px;font-weight:700;color:#94a3b8;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);border-radius:10px;cursor:pointer;white-space:nowrap;font-family:inherit;}
.osos-day-btn.active{background:linear-gradient(135deg,#16a34a,#22c55e);color:white;border-color:transparent;}

.ay-card{display:grid;grid-template-columns:80px 1fr 1fr 1fr 30px;gap:8px;align-items:center;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.05);border-radius:10px;padding:10px 12px;margin-bottom:6px;font-size:11px;}
.ay-name{font-weight:800;color:#cbd5e1;font-size:12px;}
.ay-cekis{color:#f87171;font-weight:700;text-align:right;}
.ay-veris{color:#4ade80;font-weight:700;text-align:right;}
.ay-net{color:#fbbf24;font-weight:800;text-align:right;}
.ay-tik{text-align:center;font-size:14px;}
.ay-tik.ok{color:#4ade80;}
.ay-tik.hata{color:#f87171;}
.ay-tik.bekliyor{color:#64748b;}

.yillik-card{background:linear-gradient(135deg,rgba(59,130,246,0.15) 0%,rgba(59,130,246,0.05) 100%);border:1px solid rgba(59,130,246,0.25);border-radius:16px;padding:16px;margin-bottom:14px;}
.yillik-title{font-size:13px;font-weight:800;color:#93c5fd;margin-bottom:10px;}
.yillik-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;}
.yillik-stat{text-align:center;}
.yillik-lbl{font-size:9px;color:#64748b;text-transform:uppercase;font-weight:700;}
.yillik-val{font-size:18px;font-weight:900;margin-top:4px;}

.guncelleme{font-size:11px;color:#334155;text-align:center;margin-top:14px;}
.empty-state{text-align:center;padding:40px 20px;color:#475569;font-size:13px;}
.tab-content{display:none;}
.tab-content.active{display:block;animation:otoTabGiris .28s cubic-bezier(.22,.8,.36,1);}
/* ════ MIKRO ANIMASYONLAR (b42) ════ */
@keyframes otoTabGiris{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:translateY(0);}}
@keyframes otoKartGiris{from{opacity:0;transform:translateY(10px) scale(.985);}to{opacity:1;transform:translateY(0) scale(1);}}
.cihaz-card,.chart-wrap,.f2-chart-card{transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease;}
.cihaz-card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(0,0,0,.35);border-color:rgba(245,185,33,.45);}
.chart-wrap:hover{border-color:rgba(52,210,235,.25);}
.f2-chart-card:hover{box-shadow:0 4px 14px rgba(0,0,0,.08);}
.t2k-gun-kart{animation:otoKartGiris .3s ease both;}
.t2k-gun-kart:nth-child(2){animation-delay:.03s;}
.t2k-gun-kart:nth-child(3){animation-delay:.06s;}
.t2k-gun-kart:nth-child(4){animation-delay:.09s;}
.t2k-gun-kart:nth-child(5){animation-delay:.12s;}
@media (prefers-reduced-motion: reduce){.tab-content.active,.t2k-gun-kart{animation:none;}}
.osos-sec-content{display:none;}
.osos-sec-content.active{display:block;}
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>@import url("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap");</style>
<script>
// ════════ OTOCOIN GRAFIK TEMASI (b41) — tum grafiklerde ortak ════════
const OTO_G = {
  gunes:  "#f5b921",   // uretim / solar
  cekis:  "#e84855",   // tuketim / sebeke cekis
  ptf:    "#34d2eb",   // spot fiyat / hashrate
  yesil:  "#3ddc84",   // TL gelir / pozitif
  mavi:   "#3b82f6",   // ikincil seri
  mono:   "'IBM Plex Mono', monospace",
  // acik kart (beyaz zemin) varyantlari
  gunesK: "#d99000", cekisK: "#d63040", ptfK: "#0e9ab5", yesilK: "#14a85e",
  gridA:  "rgba(148,163,184,0.28)",   // acik zemin izgara
  gridK:  "rgba(255,255,255,0.07)"    // koyu zemin izgara
};
// Koyu tooltip + mono eksen — Chart.js global varsayilanlari
if (window.Chart) {
  Chart.defaults.font.family = OTO_G.mono;
  Chart.defaults.font.size = 10;
  const tt = Chart.defaults.plugins.tooltip;
  tt.backgroundColor = "#161d25";
  tt.borderColor = "#2a3644";
  tt.borderWidth = 1;
  tt.cornerRadius = 4;
  tt.padding = 10;
  tt.titleColor = "#5d6c7b";
  tt.titleFont = { family: OTO_G.mono, size: 10, weight: "700" };
  tt.bodyColor = "#e8edf2";
  tt.bodyFont = { family: OTO_G.mono, size: 11, weight: "600" };
  tt.boxPadding = 4;
  tt.displayColors = true;
}
// Acik zeminli Chart.js grafikler icin ortak eksen ayari
function otoEksen(birim) {
  return {
    x: { grid: { display: false }, ticks: { color: "#64748b", font: { family: OTO_G.mono, size: 9 } } },
    y: { beginAtZero: true,
         grid: { color: OTO_G.gridA, borderDash: [3, 5], drawTicks: false },
         border: { display: false, dash: [3, 5] },
         ticks: { color: "#64748b", font: { family: OTO_G.mono, size: 9 },
                  callback: v => v.toLocaleString("tr-TR") + (birim ? " " + birim : "") } }
  };
}
</script>
</head><body>
<div id="versiyon-damgasi" onclick="versiyonPopupAc(event)" style="position:fixed; bottom:10px; right:10px; z-index:99999; background:rgba(15,23,42,0.92); border:1px solid rgba(34,197,94,0.4); border-radius:8px; padding:5px 10px; font-size:10px; font-weight:700; color:#4ade80; font-family:'Inter',monospace; box-shadow:0 2px 12px rgba(0,0,0,0.4); cursor:pointer; letter-spacing:0.3px; text-align:right; user-select:none;">
  {{ panel_versiyon }} <span style="color:#64748b; font-size:9px;">ⓘ</span>
  <div id="versiyon-popup" style="display:none; position:absolute; bottom:calc(100% + 8px); right:0; background:#0f172a; border:1px solid rgba(34,197,94,0.4); border-radius:12px; padding:14px 16px; min-width:240px; box-shadow:0 8px 32px rgba(0,0,0,0.5); text-align:left; cursor:default;">
    <div style="font-size:12px; font-weight:900; color:#4ade80; margin-bottom:3px;">{{ panel_versiyon }}</div>
    <div style="font-size:10px; color:#94a3b8; font-weight:600; margin-bottom:10px; padding-bottom:10px; border-bottom:1px solid rgba(148,163,184,0.2);">{{ panel_versiyon_tarih }}</div>
    <div style="display:flex; flex-direction:column; gap:7px;">
      <div style="display:flex; justify-content:space-between; gap:16px; font-size:10px;"><span style="color:#64748b; font-weight:600;">📦 Arşiv</span><span style="color:#e2e8f0; font-weight:700;">{{ sistem_durum.arsiv }}</span></div>
      <div style="display:flex; justify-content:space-between; gap:16px; font-size:10px;"><span style="color:#64748b; font-weight:600;">⚡ PTF</span><span style="color:#e2e8f0; font-weight:700;">{{ sistem_durum.ptf }}</span></div>
      <div style="display:flex; justify-content:space-between; gap:16px; font-size:10px;"><span style="color:#64748b; font-weight:600;">📊 OSOS</span><span style="color:#e2e8f0; font-weight:700;">{{ sistem_durum.osos }}</span></div>
    </div>
  </div>
</div>
<div class="header">
<div class="brand"><div class="brand-logo">⚡</div><div class="brand-text">Otocoin</div></div>
<div style="display:flex;align-items:center;gap:8px">
<div class="user-pill"><div class="user-avatar">{{ kullanici[:2].upper() }}</div><div class="user-name">{{ kullanici }}</div></div>
<a href="/cikis" class="cikis-link">Çıkış</a>
</div>
</div>
<div class="tabs">
<div class="tab active" onclick="sekme('ozet', this)">🏠 Özet</div>
<div class="tab" onclick="sekme('epias', this)">⚡ EPİAŞ</div>
<div class="tab" onclick="sekme('f2pool', this)">₿ F2Pool</div>
<div class="tab" onclick="sekme('cihazlar', this)">🖥️ Cihazlar</div>
<div class="tab" onclick="sekme('cihazlarim', this)" style="background:linear-gradient(135deg,rgba(251,191,36,0.15),rgba(34,197,94,0.15));border-color:rgba(251,191,36,0.4);">💎 Cihazlarım</div>
<div class="tab" onclick="sekme('maliyetler', this)" style="background:linear-gradient(135deg,rgba(239,68,68,0.12),rgba(245,158,11,0.08));border-color:rgba(245,158,11,0.4);">💸 Maliyetler</div>
<div class="tab" onclick="sekme('veri', this)" style="background:linear-gradient(135deg,rgba(59,130,246,0.12),rgba(99,102,241,0.08));border-color:rgba(59,130,246,0.4);">📊 Veri</div>
<div class="tab" onclick="sekme('mahsuplasma', this)" style="background:linear-gradient(135deg,rgba(139,92,246,0.12),rgba(217,70,239,0.08));border-color:rgba(139,92,246,0.4);">🔄 Mahsuplaşma</div>
<div class="tab" onclick="sekme('faturalandirma', this)" style="background:linear-gradient(135deg,rgba(251,191,36,0.12),rgba(245,158,11,0.08));border-color:rgba(251,191,36,0.4);">🧾 Faturalandırma</div>
<div class="tab" onclick="sekme('t2kiyas', this)" style="background:linear-gradient(135deg,rgba(139,92,246,0.15),rgba(168,85,247,0.10));border-color:rgba(139,92,246,0.4);">⚖️ T2 Kıyas</div>
<div class="tab" onclick="sekme('osos', this)">🔋 OSOS</div>
<div class="tab" onclick="sekme('inverter', this)">🌞 İnverter</div>
<div class="tab" onclick="sekme('antminer', this)">⛏️ Antminer Saha</div>
<div class="tab" onclick="sekme('rapor', this)" style="background:linear-gradient(135deg,rgba(100,116,139,0.12),rgba(71,85,105,0.08));border-color:rgba(100,116,139,0.4);">📋 Rapor</div>
</div>
<div class="content">

<div class="tab-content active" id="t-ozet">
<div class="status-card gri" id="status-card">
<div class="status-row">
<div class="status-icon" id="status-icon">⏳</div>
<div><div class="status-title" id="status-title">Yükleniyor...</div><div class="status-sub" id="status-sub"></div></div>
</div>
</div>
<div class="kpi-grid">
<div class="kpi-card highlight"><div class="kpi-label">💰 BTC Fiyatı</div><div class="kpi-value" id="btc-tl">—</div><div class="kpi-sub" id="btc-usd">—</div></div>
<div class="kpi-card"><div class="kpi-label">📊 Bugünkü Tahmini</div><div class="kpi-value" id="bugun-btc">—</div><div class="kpi-sub" id="bugun-tl">—</div></div>
<div class="kpi-card"><div class="kpi-label">₿ Dünkü Kazanç</div><div class="kpi-value" id="dun-btc">—</div><div class="kpi-sub" id="dun-tl">—</div></div>
<div class="kpi-card"><div class="kpi-label">📈 Aylık Net Kar</div><div class="kpi-value" id="ay-kar" style="color:#4ade80">—</div><div class="kpi-sub" id="ay-gun">—</div></div>
</div>
<div class="kpi-card"><div class="kpi-label">⚡ Toplam Hashrate</div><div class="kpi-value" id="toplam-hash" style="color:#60a5fa">—</div><div class="kpi-sub">24 saatlik ortalama</div></div>
</div>

<div class="tab-content" id="t-epias">

<!-- YEKDEM AYLIK TABLOSU -->
<div class="section-header">
<div class="section-title">💰 YEKDEM Birim Bedelleri (TL/MWh)</div>
<div style="font-size:10px;color:#64748b">EPİAŞ Şeffaflık · Versiyonlu değerler</div>
</div>

<div class="yekdem-yasal" style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:14px; margin-bottom:18px;">
  <div id="yekdem-kart-grid" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(180px, 1fr)); gap:10px;"></div>

  <div style="display:flex; gap:14px; flex-wrap:wrap; margin-top:14px; padding-top:12px; border-top:1px solid rgba(255,255,255,0.05); font-size:10px; color:#94a3b8;">
    <div style="display:flex; align-items:center; gap:6px;"><span style="width:12px; height:12px; border-radius:3px; background:rgba(34,197,94,0.18); border:1px solid rgba(34,197,94,0.5);"></span> Gerçekleşmiş (Kesinleşmiş)</div>
    <div style="display:flex; align-items:center; gap:6px;"><span style="width:12px; height:12px; border-radius:3px; background:rgba(251,146,60,0.18); border:1px solid rgba(251,146,60,0.5);"></span> Öngörü (Resmi Açıklama)</div>
    <div style="display:flex; align-items:center; gap:6px;"><span style="width:12px; height:12px; border-radius:3px; background:rgba(251,191,36,0.18); border:1px solid rgba(251,191,36,0.5);"></span> Tahmini (Sapma Uyarlanmış)</div>
  </div>
</div>

<!-- PTF TABLOSU -->
<div class="section-header">
<div class="section-title">📅 <span id="epias-baslik">PTF Tablosu</span></div>
<div style="display:flex;align-items:center;gap:10px;">
  <select id="epias-ay-secim" onchange="epiasAyDegisti()" style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); color:white; padding:7px 11px; border-radius:9px; font-size:12px; font-weight:700; font-family:inherit; cursor:pointer;">
    <option value="">Yükleniyor...</option>
  </select>
  <div style="font-size:10px;color:#64748b">⏸ Kapalı saatler mor</div>
</div>
</div>
<div class="aylik-wrap">
<table class="aylik-table" id="aylik-table"><thead id="aylik-thead"></thead><tbody id="aylik-tbody"></tbody></table>
</div>
</div>

<div class="tab-content" id="t-f2pool" style="background:#f1f5f9; border-radius:16px; padding:16px; margin-top:8px;">

<!-- F2Pool alt sekmeler -->
<div class="f2-alt-tabs">
  <button class="f2-alt-tab" data-alt="cihazlar" onclick="f2AltSekme('cihazlar', this)">🖥️ Cihazlar</button>
  <button class="f2-alt-tab active" data-alt="kazanc" onclick="f2AltSekme('kazanc', this)">💰 Kazanç</button>
  <button class="f2-alt-tab" data-alt="kiyas" onclick="f2AltSekme('kiyas', this)">⚖️ Kıyas</button>
</div>

<!-- ===== ALT SEKME: KAZANÇ ===== -->
<div class="f2-alt-content active" id="f2-alt-kazanc">

<!-- Hero: donem ozeti -->
<div class="f2-hero">
  <div class="f2-hero-left">
    <div class="f2-hero-ico">₿</div>
    <div>
      <div class="f2-hero-lbl" id="f2-hero-lbl">Tüm Dönem (30 gün)</div>
      <div class="f2-hero-btc" id="f2-hero-btc">— <span>BTC</span></div>
    </div>
  </div>
  <div class="f2-hero-right">
    <div class="f2-hero-tl" id="f2-hero-tl">— ₺</div>
    <div class="f2-hero-sub" id="f2-hero-sub">—</div>
  </div>
</div>

<!-- Kontroller: zaman + ay -->
<div class="f2-kontrol">
  <div class="f2-zaman-grup">
    <button class="f2-zaman-btn active" data-zaman="gunluk" onclick="f2ZamanSec('gunluk', this)">Günlük</button>
    <button class="f2-zaman-btn" data-zaman="haftalik" onclick="f2ZamanSec('haftalik', this)">Haftalık</button>
    <button class="f2-zaman-btn" data-zaman="aylik" onclick="f2ZamanSec('aylik', this)">Aylık</button>
  </div>
  <select id="f2-ay-secim" onchange="f2Render()" class="f2-ay-sec">
    <option value="tum">Tüm Veriler</option>
  </select>
</div>

<!-- Grafik karti -->
<div class="f2-chart-card">
  <div class="f2-chart-head">
    <div class="f2-chart-baslik" id="f2-chart-baslik">📊 Günlük Genel Görünüm</div>
  </div>
  <canvas id="f2-chart" style="width:100%; height:200px;"></canvas>
  <div class="f2-lejant">
    <span class="f2-lej"><span class="f2-lej-renk" style="background:rgba(14,154,181,0.8);"></span>Hashrate</span>
    <span class="f2-lej"><span class="f2-lej-renk" style="background:#d99000;"></span>BTC Üretim</span>
    <span class="f2-lej"><span class="f2-lej-renk" style="background:#d63040;"></span>Elektrik</span>
    <span class="f2-lej"><span class="f2-lej-renk" style="background:#7c3aed;"></span>BTC Fiyatı</span>
  </div>
</div>
<span id="f2-metric-gizli" style="display:none;">
  <button class="f2-metric-btn" data-metric="btc"></button>
  <button class="f2-metric-btn" data-metric="tl"></button>
  <button class="f2-metric-btn" data-metric="hash"></button>
</span>

<!-- KPI seridi: 3 ana metrik -->
<div class="f2-kpi-grid">
  <div class="f2-kpi">
    <div class="f2-kpi-lbl">Günlük Ortalama</div>
    <div class="f2-kpi-val" id="f2-ist-ort" style="color:#16a34a;">—</div>
    <div class="f2-kpi-sub" id="f2-ist-ort-sub">BTC/gün</div>
  </div>
  <div class="f2-kpi">
    <div class="f2-kpi-lbl">Ort. Hashrate</div>
    <div class="f2-kpi-val" id="f2-ist-hash" style="color:#2563eb;">—</div>
    <div class="f2-kpi-sub">TH/s</div>
  </div>
  <div class="f2-kpi">
    <div class="f2-kpi-lbl">Çalışan Cihaz</div>
    <div class="f2-kpi-val" id="f2-ist-cihaz" style="color:#d97706;">—</div>
    <div class="f2-kpi-sub" id="f2-ist-fiyat-sub">aktif / toplam</div>
  </div>
</div>

<!-- Gizli alanlar (eski JS uyumlulugu) -->
<span id="f2-ist-top" style="display:none;"></span>
<span id="f2-ist-fiyat" style="display:none;"></span>
<span id="f2-title" style="display:none;"></span>
<span id="f2-subtitle" style="display:none;"></span>
<span id="f2-big" style="display:none;"></span>
<span id="f2-small" style="display:none;"></span>

<div class="section-title" id="f2-liste-baslik" style="margin-top:6px;">📅 Günlük Üretim</div>
<div id="daily-list" style="margin-top:8px"><div class="empty-state">Yükleniyor...</div></div>
</div>
<!-- ===== /ALT SEKME: KAZANÇ ===== -->

<!-- ===== ALT SEKME: CIHAZLAR ===== -->
<div class="f2-alt-content" id="f2-alt-cihazlar">
<div class="cihaz-ozet">
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#16a34a" id="f2c-aktif">—</div><div class="cihaz-ozet-lbl">Çalışan</div></div>
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#d97706" id="f2c-uyku">—</div><div class="cihaz-ozet-lbl">Uyuyan</div></div>
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#dc2626" id="f2c-kapali">—</div><div class="cihaz-ozet-lbl">Kapalı</div></div>
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#2563eb" id="f2c-toplam">—</div><div class="cihaz-ozet-lbl">TH/s</div></div>
</div>
<div class="section-header">
<div class="section-title">🖥️ Cihaz Listesi</div>
<div style="font-size:10px;color:#64748b">Detay için dokunun</div>
</div>
<div class="cihaz-grid" id="f2c-grid"><div class="empty-state" style="grid-column:1/-1">Yükleniyor...</div></div>
</div>
<!-- ===== /ALT SEKME: CIHAZLAR ===== -->

<!-- ===== ALT SEKME: KIYAS (Madencilik Karliligi) ===== -->
<div class="f2-alt-content" id="f2-alt-kiyas">
<div class="f2-kiyas-aciklama">⚖️ Madencilik kârlılığı: BTC geliri vs elektrik gideri (T2 tüketimi = madencilik). Tüketim şimdilik hashrate'ten tahmini.</div>

<!-- Gun secici -->
<div class="f2-kontrol">
  <div class="f2-zaman-grup">
    <button class="f2-kiyas-zaman active" data-kz="gun" onclick="f2KiyasZaman('gun', this)">Günlük</button>
    <button class="f2-kiyas-zaman" data-kz="ay" onclick="f2KiyasZaman('ay', this)">Aylık</button>
  </div>
  <input type="date" id="f2-kiyas-tarih" onchange="f2KiyasRender()" class="f2-ay-sec" style="cursor:pointer;">
</div>

<!-- Ozet kartlari -->
<div class="f2-kiyas-ozet" id="f2-kiyas-ozet"></div>

<!-- Verimlilik haritasi (24 saat) -->
<div class="f2-harita-card">
  <div class="f2-harita-baslik">🗺️ Günlük Verimlilik Haritası <span style="font-size:9px;color:#94a3b8;font-weight:600;">(yeşil=kârlı, kırmızı=zararlı)</span></div>
  <div class="f2-harita-grid" id="f2-harita-grid"></div>
  <div class="f2-harita-lejant">
    <span class="f2-hl"><span class="f2-hl-renk" style="background:#16a34a;"></span>Kârlı</span>
    <span class="f2-hl"><span class="f2-hl-renk" style="background:#fbbf24;"></span>Başabaş</span>
    <span class="f2-hl"><span class="f2-hl-renk" style="background:#dc2626;"></span>Zararlı</span>
    <span class="f2-hl"><span class="f2-hl-renk" style="background:#e2e8f0;"></span>Veri yok</span>
  </div>
</div>

<!-- Saatlik kiyas tablosu -->
<div class="section-title" style="margin-top:14px;">📋 Saatlik Kıyas</div>
<div id="f2-kiyas-liste"><div class="empty-state">Gün seçin</div></div>
</div>
<!-- ===== /ALT SEKME: KIYAS ===== -->

</div>


<div class="tab-content" id="t-cihazlar">
<div class="cihaz-ozet">
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#4ade80" id="cihaz-aktif">—</div><div class="cihaz-ozet-lbl">Çalışan</div></div>
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#fbbf24" id="cihaz-uyku">—</div><div class="cihaz-ozet-lbl">Uyuyan</div></div>
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#f87171" id="cihaz-kapali">—</div><div class="cihaz-ozet-lbl">Kapalı</div></div>
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#60a5fa" id="cihaz-toplam">—</div><div class="cihaz-ozet-lbl">TH/s</div></div>
</div>
<div class="section-header">
<div class="section-title">🖥️ Cihaz Listesi</div>
<div style="font-size:10px;color:#64748b">Detay için dokunun</div>
</div>
<div class="cihaz-grid" id="cihaz-grid"><div class="empty-state" style="grid-column:1/-1">Yükleniyor...</div></div>
</div>

<div class="tab-content" id="t-osos">
<div class="osos-tabs">
<button class="osos-tab active" onclick="ososAbone('tekyildiz_1', this)">☀️ Tekyildiz 1</button>
<button class="osos-tab" onclick="ososAbone('tekyildiz_2', this)">⚡ Tekyildiz 2</button>
<button class="osos-tab" onclick="ososAbone('aksaray_3', this)">🏭 Aksaray 3</button>
</div>

<div class="osos-info" id="osos-info">
<div class="osos-info-ico" id="osos-info-ico">☀️</div>
<div><div class="osos-info-title" id="osos-info-title">—</div><div class="osos-info-sub" id="osos-info-sub">—</div></div>
</div>

<div class="osos-stats">
<div class="osos-stat"><div class="osos-stat-lbl">Toplam Çekiş</div><div class="osos-stat-val" style="color:#f87171" id="osos-cekis">—</div><div class="osos-stat-sub">kWh</div></div>
<div class="osos-stat"><div class="osos-stat-lbl">Toplam Veriş</div><div class="osos-stat-val" style="color:#4ade80" id="osos-veris">—</div><div class="osos-stat-sub">kWh</div></div>
<div class="osos-stat"><div class="osos-stat-lbl">Net</div><div class="osos-stat-val" id="osos-net">—</div><div class="osos-stat-sub">kWh</div></div>
</div>

<div class="osos-section-tabs">
<button class="osos-sec-tab active" onclick="ososSec('saatlik', this)">📅 Saatlik</button>
<button class="osos-sec-tab" onclick="ososSec('aylik', this)">📊 Aylık</button>
<button class="osos-sec-tab" onclick="ososSec('yillik', this)">🗓️ Yıllık</button>
</div>

<!-- SAATLİK -->
<div class="osos-sec-content active" id="osos-sec-saatlik">
<div class="chart-wrap" style="margin-bottom:12px">
<div class="chart-title">📊 Son 30 Gün</div>
<canvas class="chart-canvas" id="osos-chart" style="height:160px"></canvas>
<div class="tooltip" id="osos-tt"><div class="tooltip-time" id="osos-tt-time"></div><div class="tooltip-val" id="osos-tt-val"></div></div>
</div>
<div class="section-title" style="margin:12px 0 8px">📅 Gün Seçin</div>
<div class="osos-day-list" id="osos-day-list"></div>
<div class="aylik-wrap">
<table class="aylik-table">
<thead><tr><th class="saat-head">Saat</th><th style="color:#f87171">Çekiş</th><th style="color:#4ade80">Veriş</th><th class="saat-head">Net</th></tr></thead>
<tbody id="osos-saatlik-body"><tr><td colspan="4" class="empty-state">Gün seçin</td></tr></tbody>
</table>
</div>
</div>

<!-- AYLIK -->
<div class="osos-sec-content" id="osos-sec-aylik">
<div style="font-size:10px;color:#64748b;margin-bottom:8px;text-align:right">✅ Endeks doğrulandı · ⏳ Bekliyor · ❌ Fark var</div>
<div id="aylik-liste"><div class="empty-state">Yükleniyor...</div></div>
</div>

<!-- YILLIK -->
<div class="osos-sec-content" id="osos-sec-yillik">
<div id="yillik-liste"><div class="empty-state">Yükleniyor...</div></div>
</div>
</div>

<!-- ====================== İNVERTER SEKMESİ ====================== -->
<div class="tab-content" id="t-inverter">

<!-- TESİS SEKMELERİ -->
<div class="osos-tabs">
<button class="osos-tab active" onclick="invTesis('all', this)">⚡ Tümü</button>
<button class="osos-tab" onclick="invTesis('NE=59224704', this)">☀️ Tek Yıldız 1</button>
<button class="osos-tab" onclick="invTesis('NE=73686040', this)">☀️ Tek Yıldız 2</button>
</div>

<!-- TESİS ÖZET KARTI -->
<div class="osos-info ges" id="inv-info">
<div class="osos-info-ico">☀️</div>
<div style="flex:1">
<div class="osos-info-title" id="inv-info-title">Yükleniyor...</div>
<div class="osos-info-sub" id="inv-info-sub">—</div>
</div>
<div style="text-align:right">
<div style="font-size:20px;font-weight:900;color:#fbbf24" id="inv-info-power">—</div>
<div style="font-size:10px;color:#94a3b8">kW anlık</div>
</div>
</div>

<!-- İSTATİSTİKLER -->
<div class="osos-stats">
<div class="osos-stat"><div class="osos-stat-lbl">Anlık Güç</div><div class="osos-stat-val" style="color:#4ade80" id="inv-anlik">—</div><div class="osos-stat-sub">kW</div></div>
<div class="osos-stat"><div class="osos-stat-lbl">Bugünkü Üretim</div><div class="osos-stat-val" style="color:#fbbf24" id="inv-bugun">—</div><div class="osos-stat-sub">kWh</div></div>
<div class="osos-stat"><div class="osos-stat-lbl">Toplam Üretim</div><div class="osos-stat-val" style="color:#60a5fa" id="inv-toplam">—</div><div class="osos-stat-sub">MWh</div></div>
</div>

<!-- ALT SEKMELER -->
<div class="osos-section-tabs">
<button class="osos-sec-tab active" onclick="invSec('saatlik', this)">📅 Saatlik</button>
<button class="osos-sec-tab" onclick="invSec('aylik', this)">📊 Aylık</button>
<button class="osos-sec-tab" onclick="invSec('yillik', this)">🗓️ Yıllık</button>
<button class="osos-sec-tab" onclick="invSec('inverterler', this)">🖥️ İnverterler</button>
</div>

<!-- SAATLİK -->
<div class="osos-sec-content active" id="inv-sec-saatlik">
<div class="chart-wrap" style="margin-bottom:12px">
<div class="chart-title">📊 Son 30 Gün Üretim (kWh)</div>
<canvas class="chart-canvas" id="inv-chart" style="height:160px"></canvas>
<div class="tooltip" id="inv-tt"><div class="tooltip-time" id="inv-tt-time"></div><div class="tooltip-val" id="inv-tt-val"></div></div>
</div>
<div class="section-title" style="margin:12px 0 8px">📅 Gün Seçin</div>
<div class="osos-day-list" id="inv-day-list"></div>
<div class="aylik-wrap">
<table class="aylik-table">
<thead><tr><th class="saat-head">Saat</th><th style="color:#fbbf24">Güç (kW)</th><th style="color:#4ade80">Üretim (kWh)</th><th class="saat-head">Radyasyon</th></tr></thead>
<tbody id="inv-saatlik-body"><tr><td colspan="4" class="empty-state">Gün seçin</td></tr></tbody>
</table>
</div>
</div>

<!-- AYLIK -->
<div class="osos-sec-content" id="inv-sec-aylik">
<div class="chart-wrap" style="margin-bottom:12px">
<div class="chart-title">📊 Bu Ayın Günlük Üretimi</div>
<canvas class="chart-canvas" id="inv-aylik-chart" style="height:160px"></canvas>
<div class="tooltip" id="inv-aylik-tt"><div class="tooltip-time" id="inv-aylik-tt-time"></div><div class="tooltip-val" id="inv-aylik-tt-val"></div></div>
</div>
<div id="inv-aylik-liste"><div class="empty-state">Yükleniyor...</div></div>
</div>

<!-- YILLIK -->
<div class="osos-sec-content" id="inv-sec-yillik">
<div class="chart-wrap" style="margin-bottom:12px">
<div class="chart-title">📊 Yıllık Üretim (Aylık)</div>
<canvas class="chart-canvas" id="inv-yillik-chart" style="height:160px"></canvas>
<div class="tooltip" id="inv-yillik-tt"><div class="tooltip-time" id="inv-yillik-tt-time"></div><div class="tooltip-val" id="inv-yillik-tt-val"></div></div>
</div>
<div id="inv-yillik-liste"><div class="empty-state">Yükleniyor...</div></div>
</div>

<!-- İNVERTERLER -->
<div class="osos-sec-content" id="inv-sec-inverterler">
<div class="cihaz-ozet">
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#4ade80" id="inv-sayisi-aktif">—</div><div class="cihaz-ozet-lbl">Çalışan</div></div>
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#fbbf24" id="inv-sayisi-bekleme">—</div><div class="cihaz-ozet-lbl">Bekleme</div></div>
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#f87171" id="inv-sayisi-kapali">—</div><div class="cihaz-ozet-lbl">Kapalı</div></div>
<div class="cihaz-ozet-card"><div class="cihaz-ozet-val" style="color:#60a5fa" id="inv-sayisi-toplam">—</div><div class="cihaz-ozet-lbl">Toplam kW</div></div>
</div>
<div class="section-header">
<div class="section-title">🖥️ İnverter Listesi</div>
<div style="font-size:10px;color:#64748b">Detay için dokunun</div>
</div>
<div class="cihaz-grid" id="inv-grid"><div class="empty-state" style="grid-column:1/-1">Yükleniyor...</div></div>
</div>

</div>
<!-- ====================== İNVERTER SEKME SONU ====================== -->

<!-- ====================== ANTMINER SAHA SEKMESI ====================== -->
<div class="tab-content" id="t-antminer">

<div class="status-card" id="ant-status">
<div class="status-row">
<div class="status-icon" style="background:linear-gradient(135deg,#f59e0b,#fbbf24)">⛏️</div>
<div>
<div class="status-title" id="ant-info-title">Yükleniyor...</div>
<div class="status-sub" id="ant-info-sub">—</div>
</div>
</div>
</div>

<div class="kpi-grid">
<div class="kpi-card highlight">
<div class="kpi-label">⛏️ Toplam Hashrate</div>
<div class="kpi-value" id="ant-hash" style="color:#fbbf24">—</div>
<div class="kpi-sub" id="ant-hash-sub">TH/s</div>
</div>
<div class="kpi-card">
<div class="kpi-label">⚡ Verimlilik</div>
<div class="kpi-value" id="ant-eff" style="color:#4ade80">—</div>
<div class="kpi-sub">% nominal</div>
</div>
<div class="kpi-card">
<div class="kpi-label">✅ Çalışan</div>
<div class="kpi-value" id="ant-online" style="color:#22c55e">—</div>
<div class="kpi-sub" id="ant-online-sub">/ — cihaz</div>
</div>
<div class="kpi-card">
<div class="kpi-label">🌡️ Sıcaklık</div>
<div class="kpi-value" id="ant-temp" style="color:#fb923c">—</div>
<div class="kpi-sub" id="ant-temp-sub">°C</div>
</div>
</div>

<!-- Kazanç Kartları -->
<div class="kpi-grid" id="ant-kazanc-grid" style="display:none">
<div class="kpi-card" style="border-left:3px solid #fbbf24">
<div class="kpi-label">💰 Bugün</div>
<div class="kpi-value" id="ant-earn-today-try" style="color:#fbbf24;font-size:18px">—</div>
<div class="kpi-sub" id="ant-earn-today-sub">— USD · — BTC</div>
</div>
<div class="kpi-card" style="border-left:3px solid #94a3b8">
<div class="kpi-label">📅 Dün</div>
<div class="kpi-value" id="ant-earn-yesterday-try" style="color:#94a3b8;font-size:18px">—</div>
<div class="kpi-sub" id="ant-earn-yesterday-sub">— USD · — BTC</div>
</div>
<div class="kpi-card" style="border-left:3px solid #60a5fa">
<div class="kpi-label">📊 Son 7 Gün</div>
<div class="kpi-value" id="ant-earn-7d-try" style="color:#60a5fa;font-size:18px">—</div>
<div class="kpi-sub" id="ant-earn-7d-sub">— USD · — BTC</div>
</div>
<div class="kpi-card highlight" style="border-left:3px solid #22c55e">
<div class="kpi-label">🏆 Toplam Kazanç</div>
<div class="kpi-value" id="ant-earn-total-try" style="color:#22c55e;font-size:18px">—</div>
<div class="kpi-sub" id="ant-earn-total-sub">— USD · — BTC</div>
</div>
</div>

<div class="osos-section-tabs">
<button class="osos-sec-tab active" onclick="antSec('liste', this)">🖥️ Cihaz Listesi</button>
<button class="osos-sec-tab" onclick="antSec('modeller', this)">📊 Modeller</button>
<button class="osos-sec-tab" onclick="antSec('sorunlu', this)">⚠️ Sorunlular</button>
</div>

<div class="osos-sec-content active" id="ant-sec-liste">

<!-- Toplu kontrol butonlari -->
<div style="background:rgba(251,191,36,0.08); border:1px solid rgba(251,191,36,0.3); border-radius:10px; padding:10px; margin-bottom:12px; display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
<span style="font-size:11px; color:#94a3b8; font-weight:700;">🎛️ TOPLU İŞLEM:</span>
<button onclick="antBulk('wake')" style="background:linear-gradient(135deg,#22c55e,#16a34a); color:white; border:none; padding:8px 14px; border-radius:8px; font-weight:700; cursor:pointer; font-size:12px;">▶️ Hepsini Çalıştır</button>
<button onclick="antBulk('sleep')" style="background:linear-gradient(135deg,#f59e0b,#d97706); color:white; border:none; padding:8px 14px; border-radius:8px; font-weight:700; cursor:pointer; font-size:12px;">💤 Hepsini Uyut</button>
<div style="flex:1"></div>
<div id="ant-cmd-status" style="font-size:11px; color:#94a3b8;"></div>
</div>

<div class="cihaz-grid" id="ant-grid"><div class="empty-state" style="grid-column:1/-1">Yükleniyor...</div></div>
</div>

<div class="osos-sec-content" id="ant-sec-modeller">
<div id="ant-modeller-liste"><div class="empty-state">Yükleniyor...</div></div>
</div>

<div class="osos-sec-content" id="ant-sec-sorunlu">
<div id="ant-sorunlu-liste"><div class="empty-state">Yükleniyor...</div></div>
</div>

</div>
<!-- ====================== ANTMINER SEKME SONU ====================== -->


<!-- ====================== CIHAZLARIM SEKMESI ====================== -->
<div class="tab-content" id="t-cihazlarim">

<!-- BEKLEYEN ONAYLAR -->
<div id="cmm-bekleyen" style="display:none; background:linear-gradient(135deg, rgba(239,68,68,0.12), rgba(251,191,36,0.08)); border:2px solid rgba(251,191,36,0.4); border-radius:14px; padding:14px; margin-bottom:14px;">
  <div style="font-size:14px; font-weight:900; color:#fbbf24; margin-bottom:10px;">⏰ BEKLEYEN ONAYLAR</div>
  <div id="cmm-bekleyen-liste"></div>
</div>

<!-- HEADER -->
<div style="background:linear-gradient(135deg, rgba(251,191,36,0.12), rgba(34,197,94,0.08)); border:1px solid rgba(251,191,36,0.25); border-radius:16px; padding:18px; margin-bottom:14px; position:relative; overflow:hidden;">
  <div style="position:absolute; top:-30px; right:-30px; width:140px; height:140px; background:radial-gradient(circle, rgba(251,191,36,0.15), transparent 70%); border-radius:50%; pointer-events:none;"></div>
  <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px;">
    <div>
      <div style="font-size:22px; font-weight:900; background:linear-gradient(90deg,#fbbf24,#22c55e); -webkit-background-clip:text; background-clip:text; color:transparent;">💎 Cihazlarım</div>
      <div id="cmm-sub" style="font-size:11px; color:#94a3b8; margin-top:4px;">Saha & Havuz tek ekranda</div>
    </div>
    <div id="cmm-stat" style="font-size:11px; color:#94a3b8;">—</div>
  </div>
</div>

<!-- ANA KPI -->
<div class="kpi-grid" style="margin-bottom:14px;">
  <div class="kpi-card highlight" style="background:linear-gradient(135deg, rgba(251,191,36,0.08), rgba(0,0,0,0)); border-left:3px solid #fbbf24;">
    <div class="kpi-label">⛏️ Toplam Hashrate</div>
    <div class="kpi-value" id="cmm-hash" style="color:#fbbf24">—</div>
    <div class="kpi-sub" id="cmm-hash-sub">TH/s</div>
  </div>
  <div class="kpi-card" style="background:linear-gradient(135deg, rgba(34,197,94,0.08), rgba(0,0,0,0)); border-left:3px solid #22c55e;">
    <div class="kpi-label">💰 Toplam Kazanç</div>
    <div class="kpi-value" id="cmm-total-earn" style="color:#22c55e;font-size:22px">—</div>
    <div class="kpi-sub" id="cmm-total-earn-sub">—</div>
  </div>
  <div class="kpi-card" style="background:linear-gradient(135deg, rgba(96,165,250,0.08), rgba(0,0,0,0)); border-left:3px solid #60a5fa;">
    <div class="kpi-label">✅ Çalışan Cihaz</div>
    <div class="kpi-value" id="cmm-online" style="color:#60a5fa">—</div>
    <div class="kpi-sub" id="cmm-online-sub">/ — cihaz</div>
  </div>
  <div class="kpi-card" style="background:linear-gradient(135deg, rgba(168,85,247,0.08), rgba(0,0,0,0)); border-left:3px solid #a855f7;">
    <div class="kpi-label">⚡ Verimlilik</div>
    <div class="kpi-value" id="cmm-eff" style="color:#a855f7">—</div>
    <div class="kpi-sub">% nominal</div>
  </div>
</div>

<!-- KAZANC OZET -->
<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-radius:14px; padding:14px; margin-bottom:14px;">
  <div style="font-size:13px; font-weight:900; color:#fbbf24; margin-bottom:10px;">💰 KAZANÇ ÖZETİ</div>
  <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:8px;">
    <div style="background:#0f172a; padding:10px; border-radius:8px; border-left:3px solid #fbbf24;">
      <div style="font-size:10px; color:#94a3b8;">Bugün</div>
      <div id="cmm-earn-today" style="font-size:16px; font-weight:900; color:#fbbf24;">—</div>
      <div id="cmm-earn-today-sub" style="font-size:9px; color:#64748b;">—</div>
    </div>
    <div style="background:#0f172a; padding:10px; border-radius:8px; border-left:3px solid #94a3b8;">
      <div style="font-size:10px; color:#94a3b8;">Dün</div>
      <div id="cmm-earn-yesterday" style="font-size:16px; font-weight:900; color:#94a3b8;">—</div>
      <div id="cmm-earn-yesterday-sub" style="font-size:9px; color:#64748b;">—</div>
    </div>
    <div style="background:#0f172a; padding:10px; border-radius:8px; border-left:3px solid #60a5fa;">
      <div style="font-size:10px; color:#94a3b8;">7 Gün</div>
      <div id="cmm-earn-7d" style="font-size:16px; font-weight:900; color:#60a5fa;">—</div>
      <div id="cmm-earn-7d-sub" style="font-size:9px; color:#64748b;">—</div>
    </div>
    <div style="background:#0f172a; padding:10px; border-radius:8px; border-left:3px solid #22c55e;">
      <div style="font-size:10px; color:#94a3b8;">Toplam</div>
      <div id="cmm-earn-total" style="font-size:16px; font-weight:900; color:#22c55e;">—</div>
      <div id="cmm-earn-total-sub" style="font-size:9px; color:#64748b;">—</div>
    </div>
  </div>
</div>

<!-- TOPLU KONTROL -->
<div style="background:rgba(251,191,36,0.04); border:1px solid rgba(251,191,36,0.2); border-radius:12px; padding:12px; margin-bottom:14px;">
  <div style="font-size:11px; color:#94a3b8; font-weight:700; margin-bottom:8px;">🎛️ TOPLU İŞLEM (10 sn aralıklı, sıralı)</div>
  <div style="display:flex; gap:8px; flex-wrap:wrap;">
    <button onclick="cmmBulkSirali('wake')" style="background:linear-gradient(135deg,#22c55e,#16a34a); color:white; border:none; padding:10px 14px; border-radius:8px; font-weight:700; cursor:pointer; font-size:12px;">▶️ Sıralı Çalıştır (yüksek→düşük)</button>
    <button onclick="cmmBulkSirali('sleep')" style="background:linear-gradient(135deg,#f59e0b,#d97706); color:white; border:none; padding:10px 14px; border-radius:8px; font-weight:700; cursor:pointer; font-size:12px;">💤 Sıralı Uyut (düşük→yüksek)</button>
    <button onclick="cmmBulk('wake')" style="background:rgba(34,197,94,0.15); color:#4ade80; border:1px solid rgba(34,197,94,0.3); padding:10px 14px; border-radius:8px; font-weight:700; cursor:pointer; font-size:12px;">▶️ Hepsi Anlık</button>
    <button onclick="cmmBulk('sleep')" style="background:rgba(245,158,11,0.15); color:#fbbf24; border:1px solid rgba(245,158,11,0.3); padding:10px 14px; border-radius:8px; font-weight:700; cursor:pointer; font-size:12px;">💤 Hepsi Anlık</button>
  </div>
  <div id="cmm-cmd-status" style="font-size:11px; color:#94a3b8; margin-top:8px;"></div>
</div>

<!-- AYLIK URETIM GRAFIK -->
<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-radius:14px; padding:14px; margin-bottom:14px;">
  <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
    <div style="font-size:13px; font-weight:900; color:#60a5fa;">📈 AYLIK ÜRETİM (Son 12 Ay)</div>
    <div id="cmm-monthly-info" style="font-size:10px; color:#64748b;">—</div>
  </div>
  <div id="cmm-monthly-chart" style="display:flex; align-items:flex-end; gap:4px; height:140px; padding:6px 0;"></div>
</div>

<!-- CIHAZ GRID -->
<div style="font-size:13px; font-weight:900; color:#fbbf24; margin-bottom:8px;">⛏️ CİHAZLAR</div>
<div id="cmm-grid" class="cihaz-grid" style="margin-bottom:14px;"><div class="empty-state" style="grid-column:1/-1">Yükleniyor...</div></div>

<!-- GUNLUK URETIM LISTE -->
<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-radius:14px; padding:14px;">
  <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
    <div style="font-size:13px; font-weight:900; color:#22c55e;">📅 GÜNLÜK ÜRETİM (Son 30 Gün)</div>
    <div id="cmm-daily-info" style="font-size:10px; color:#64748b;">—</div>
  </div>
  <div id="cmm-daily-list" style="max-height:300px; overflow-y:auto;"></div>
</div>

</div>
<!-- ====================== CIHAZLARIM SEKMESI SONU ====================== -->


<!-- ====================== MALIYETLER SEKMESI ====================== -->
<div class="tab-content" id="t-maliyetler">

<!-- HEADER -->
<div style="margin-bottom:14px;">
  <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;">
    <div>
      <div style="font-size:18px; font-weight:600; color:#1e293b;">⚡ Aksaray 3 - Elektrik Maliyeti</div>
      <div style="font-size:12px; color:#64748b; margin-top:2px;">(PTF + YEKDEM) × 1.035 × Tüketim</div>
    </div>
    <select id="mlt-ay" onchange="mltYukle()" style="background:#fff; border:1px solid #cbd5e1; color:#1e293b; padding:6px 10px; border-radius:6px; font-size:13px;">
      <option value="">Mevcut Ay</option>
    </select>
  </div>
</div>

<!-- KPI -->
<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-bottom:16px;">
  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#64748b; margin-bottom:4px;">Toplam Maliyet</div>
    <div id="mlt-toplam" style="font-size:22px; font-weight:600; color:#1e293b;">—</div>
    <div id="mlt-toplam-sub" style="font-size:10px; color:#94a3b8; margin-top:2px;">— gün</div>
  </div>
  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#64748b; margin-bottom:4px;">Toplam Tüketim</div>
    <div id="mlt-tuketim" style="font-size:22px; font-weight:600; color:#1e293b;">—</div>
    <div style="font-size:10px; color:#94a3b8; margin-top:2px;">kWh</div>
  </div>
  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#64748b; margin-bottom:4px;">Birim Maliyet</div>
    <div id="mlt-birim" style="font-size:22px; font-weight:600; color:#1e293b;">—</div>
    <div style="font-size:10px; color:#94a3b8; margin-top:2px;">TL/kWh</div>
  </div>
  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#64748b; margin-bottom:4px;">Ortalama PTF</div>
    <div id="mlt-ortptf" style="font-size:22px; font-weight:600; color:#1e293b;">—</div>
    <div style="font-size:10px; color:#94a3b8; margin-top:2px;">TL/MWh</div>
  </div>
</div>

<!-- TABLO -->
<div style="background:#fff; border:1px solid #e2e8f0; border-radius:10px; overflow:hidden; margin-bottom:16px;">
  <table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
      <tr style="background:#f1f5f9; border-bottom:1px solid #e2e8f0;">
        <th style="padding:10px 8px; text-align:left; width:36px;"></th>
        <th style="padding:10px 12px; text-align:left; font-weight:600; color:#64748b;">Tarih</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600; color:#64748b;">Tüketim (kWh)</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600; color:#64748b;">Ort PTF</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600; color:#64748b;">Birim</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600; color:#64748b;">Maliyet</th>
      </tr>
    </thead>
    <tbody id="mlt-tablo"></tbody>
  </table>
</div>

<!-- CIZGI GRAFIK -->
<div style="background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:14px; margin-bottom:24px;">
  <div style="font-size:13px; font-weight:600; color:#475569; margin-bottom:10px;">📈 Günlük Tüketim (kWh)</div>
  <div style="position:relative; width:100%; height:240px;">
    <canvas id="mlt-chart"></canvas>
  </div>
</div>


<!-- ====== TEK YILDIZ 1+2 ====== -->
<div style="margin-bottom:14px; padding-top:18px; border-top:1px solid #e2e8f0;">
  <div>
    <div style="font-size:18px; font-weight:600; color:#1e293b;">📊 Tek Yıldız 1+2 - Üretim/Tüketim</div>
    <div style="font-size:12px; color:#64748b; margin-top:2px;">Toplam Üretim − TY2 Tüketim = NET</div>
  </div>
</div>

<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-bottom:16px;">
  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#64748b; margin-bottom:4px;">Toplam Üretim (TY1+TY2)</div>
    <div id="ut-ay-uretim" style="font-size:22px; font-weight:600; color:#0c447c;">—</div>
    <div style="font-size:10px; color:#94a3b8; margin-top:2px;">kWh</div>
  </div>
  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#64748b; margin-bottom:4px;">TY2 Tüketim (Sera 2)</div>
    <div id="ut-ay-tuketim" style="font-size:22px; font-weight:600; color:#993c1d;">—</div>
    <div style="font-size:10px; color:#94a3b8; margin-top:2px;">kWh</div>
  </div>
  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#64748b; margin-bottom:4px;">NET</div>
    <div id="ut-ay-net" style="font-size:22px; font-weight:600; color:#1e293b;">—</div>
    <div id="ut-ay-net-sub" style="font-size:10px; color:#94a3b8; margin-top:2px;">kWh</div>
  </div>
</div>

<!-- TY1+TY2 TABLO -->
<div style="background:#fff; border:1px solid #e2e8f0; border-radius:10px; overflow:hidden; margin-bottom:16px;">
  <table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
      <tr style="background:#f1f5f9; border-bottom:1px solid #e2e8f0;">
        <th style="padding:10px 8px; text-align:left; width:36px;"></th>
        <th style="padding:10px 12px; text-align:left; font-weight:600; color:#64748b;">Tarih</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600; color:#64748b;">TY1 Üretim</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600; color:#64748b;">TY2 Üretim</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600; color:#64748b;">TY2 Tüketim</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600; color:#64748b;">NET</th>
      </tr>
    </thead>
    <tbody id="ut-tablo"></tbody>
  </table>
</div>

<!-- TY1+TY2 GRAFIK -->
<div style="background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:14px; margin-bottom:18px;">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
    <div style="font-size:13px; font-weight:600; color:#475569;">📈 Günlük Üretim/Tüketim</div>
    <div style="font-size:11px; color:#64748b;">
      <span style="display:inline-flex; align-items:center; gap:4px; margin-right:12px;"><span style="width:10px; height:10px; border-radius:2px; background:#d99000;"></span>Üretim</span>
      <span style="display:inline-flex; align-items:center; gap:4px;"><span style="width:10px; height:10px; border-radius:2px; background:#d63040;"></span>Tüketim</span>
    </div>
  </div>
  <div style="position:relative; width:100%; height:240px;">
    <canvas id="ut-chart"></canvas>
  </div>
</div>

</div>
<!-- ====================== MALIYETLER SEKMESI SONU ====================== -->

<!-- ====================== VERI SEKMESI ====================== -->
<div class="tab-content" id="t-veri">

<div style="margin-bottom:14px;">
  <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;">
    <div>
      <div style="font-size:18px; font-weight:600; color:#1e293b;">📊 3 Abone Üretim/Tüketim</div>
      <div style="font-size:12px; color:#64748b; margin-top:2px;">TY1, TY2 ve Aksaray 3 birleşik tablo</div>
    </div>
    <select id="veri-ay" onchange="veriYukle()" style="background:#fff; border:1px solid #cbd5e1; color:#1e293b; padding:6px 10px; border-radius:6px; font-size:13px;">
      <option value="">— Yükleniyor —</option>
    </select>
  </div>
</div>

<!-- KPI -->
<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-bottom:16px;">
  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#64748b; margin-bottom:4px;">Toplam Üretim (TY1+TY2)</div>
    <div id="veri-uretim" style="font-size:22px; font-weight:600; color:#0c447c;">—</div>
    <div style="font-size:10px; color:#94a3b8; margin-top:2px;">kWh</div>
  </div>
  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#64748b; margin-bottom:4px;">Toplam Tüketim (TY2+AKS3)</div>
    <div id="veri-tuketim" style="font-size:22px; font-weight:600; color:#993c1d;">—</div>
    <div style="font-size:10px; color:#94a3b8; margin-top:2px;">kWh</div>
  </div>
  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#64748b; margin-bottom:4px;">TY Mahsup (Ür - TY2 Tük)</div>
    <div id="veri-mahsup" style="font-size:22px; font-weight:600; color:#1e293b;">—</div>
    <div style="font-size:10px; color:#94a3b8; margin-top:2px;">kWh</div>
  </div>
  <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#64748b; margin-bottom:4px;">AKS3 Tüketim (Mining)</div>
    <div id="veri-aks3" style="font-size:22px; font-weight:600; color:#d85a30;">—</div>
    <div style="font-size:10px; color:#94a3b8; margin-top:2px;">kWh</div>
  </div>
</div>

<!-- TABLO -->
<div style="background:#fff; border:1px solid #e2e8f0; border-radius:10px; overflow:hidden; margin-bottom:16px;">
  <table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
      <tr style="background:#f1f5f9; border-bottom:1px solid #e2e8f0;">
        <th style="padding:10px 8px; text-align:left; width:30px;"></th>
        <th style="padding:10px 12px; text-align:left; font-weight:600; color:#64748b;">Tarih</th>
        <th style="padding:10px 8px; text-align:right; font-weight:600; color:#185fa5;">TY1 Üret</th>
        <th style="padding:10px 8px; text-align:right; font-weight:600; color:#185fa5;">TY2 Üret</th>
        <th style="padding:10px 8px; text-align:right; font-weight:600; color:#d85a30;">TY2 Tük</th>
        <th style="padding:10px 8px; text-align:right; font-weight:600; color:#d85a30;">AKS3 Tük</th>
        <th style="padding:10px 8px; text-align:right; font-weight:600; color:#64748b;">Mahsup</th>
      </tr>
    </thead>
    <tbody id="veri-tablo"></tbody>
  </table>
</div>

<!-- CIZGI GRAFIK -->
<div style="background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:14px; margin-bottom:24px;">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
    <div style="font-size:13px; font-weight:600; color:#475569;">📈 Günlük Üretim/Tüketim</div>
    <div style="font-size:11px; color:#64748b;">
      <span style="display:inline-flex; align-items:center; gap:4px; margin-right:12px;"><span style="width:10px; height:10px; border-radius:2px; background:#d99000;"></span>Üretim</span>
      <span style="display:inline-flex; align-items:center; gap:4px;"><span style="width:10px; height:10px; border-radius:2px; background:#d63040;"></span>Tüketim</span>
    </div>
  </div>
  <div style="position:relative; width:100%; height:240px;">
    <canvas id="veri-chart"></canvas>
  </div>
</div>

</div>
<!-- ====================== VERI SEKMESI SONU ====================== -->

<!-- ====================== MAHSUPLAŞMA SEKMESI ====================== -->
<div class="tab-content" id="t-mahsuplasma">

<div style="margin-bottom:14px;">
  <div>
    <div style="font-size:18px; font-weight:600; color:#1e293b;">🔄 2026 Mahsuplaşma Tablosu</div>
    <div style="font-size:12px; color:#64748b; margin-top:2px;">EPDK Kararı 14531 · Aylık Üretim/Tüketim Mahsuplaşması</div>
  </div>
</div>

<!-- KPI 4 KUTU -->
<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:10px; margin-bottom:16px;">
  <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#1e40af; margin-bottom:4px;">Toplam Üretim</div>
    <div id="mhs-uretim" style="font-size:22px; font-weight:600; color:#185fa5;">—</div>
    <div style="font-size:10px; color:#64748b; margin-top:2px;">kWh · 2026</div>
  </div>
  <div style="background:#fef2f2; border:1px solid #fecaca; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#991b1b; margin-bottom:4px;">Toplam Tüketim</div>
    <div id="mhs-tuketim" style="font-size:22px; font-weight:600; color:#dc2626;">—</div>
    <div style="font-size:10px; color:#64748b; margin-top:2px;">kWh · 2026</div>
  </div>
  <div style="background:#faf5ff; border:1px solid #e9d5ff; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#6b21a8; margin-bottom:4px;">Toplam Mahsuplaşma</div>
    <div id="mhs-mahsup" style="font-size:22px; font-weight:600; color:#7c3aed;">—</div>
    <div style="font-size:10px; color:#64748b; margin-top:2px;">kWh · 2026</div>
  </div>
  <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; padding:12px 14px;">
    <div style="font-size:12px; color:#166534; margin-bottom:4px;">Toplam Bedelli Satış</div>
    <div id="mhs-bedelli" style="font-size:22px; font-weight:600; color:#16a34a;">—</div>
    <div style="font-size:10px; color:#64748b; margin-top:2px;">kWh · 2026</div>
  </div>
</div>

<!-- BEDELLI LIMIT PROGRESS -->
<div style="background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:16px 20px; margin-bottom:16px;">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
    <div>
      <div style="font-size:13px; color:#64748b;">2026 Bedelli Satış Limiti</div>
      <div style="font-size:11px; color:#94a3b8; margin-top:2px;">2025 Dahil Toplam Tüketim × 2 = <span id="mhs-limit-deger">2.905.914</span> kWh</div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:16px; font-weight:600;"><span id="mhs-bedelli-toplam" style="color:#16a34a;">—</span> <span style="color:#94a3b8;">/</span> <span id="mhs-limit-toplam" style="color:#64748b;">2.905.914</span></div>
      <div style="font-size:11px; color:#94a3b8;">kWh &bull; <span id="mhs-yuzde">%0.0</span></div>
    </div>
  </div>
  <div style="height:14px; background:#fef3c7; border-radius:7px; overflow:hidden; position:relative;">
    <div id="mhs-progress" style="width:0%; height:100%; background:linear-gradient(90deg, #16a34a, #22c55e); border-radius:7px; transition:width 0.6s;"></div>
  </div>
</div>

<!-- AYLIK TABLO -->
<div style="background:#fff; border:1px solid #e2e8f0; border-radius:10px; overflow:auto; margin-bottom:16px;">
  <div style="padding:12px 18px; border-bottom:1px solid #e2e8f0; background:#f8fafc; display:flex; justify-content:space-between; align-items:center;">
    <div style="font-size:14px; font-weight:600; color:#1e293b;">📋 Aylık → Günlük → Saatlik Mahsuplaşma</div>
    <button onclick="mhsAboneToggle()" id="mhs-abone-btn" style="background:#fff; border:1px solid #cbd5e1; color:#1e293b; padding:6px 14px; border-radius:6px; font-size:12px; cursor:pointer; font-weight:500;">
      🔍 Abone Detay (T1/T2/A3) Göster
    </button>
  </div>
  <table style="width:100%; border-collapse:collapse; font-size:11px;" id="mhs-tablo-el">
    <thead id="mhs-thead"></thead>
    <tbody id="mhs-tablo"></tbody>
  </table>
</div>

<!-- AÇIKLAMA -->
<div style="background:#eff6ff; border-left:3px solid #185fa5; border-radius:6px; padding:10px 14px; margin-bottom:24px; font-size:12px; color:#1e40af;">
  <strong>Mahsuplaşma kuralı:</strong> Üretim &gt; Tüketim → Mahsup = Tüketim, Bedelli = Üretim − Tüketim. Üretim ≤ Tüketim → Mahsup = Üretim, Bedelli = 0.
</div>

</div>
<!-- ====================== MAHSUPLAŞMA SEKMESI SONU ====================== -->

<!-- ====================== FATURALANDIRMA SEKMESI ====================== -->
<div class="tab-content" id="t-faturalandirma" style="background:#f1f5f9; border-radius:16px; padding:16px; margin-top:8px;">

  <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 0 16px; border-bottom:1px solid #e2e8f0; margin-bottom:18px; flex-wrap:wrap;">
    <div>
      <div style="font-size:20px; font-weight:900; background:linear-gradient(135deg,#d97706,#f59e0b); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;">🧾 Faturalandırma</div>
      <div style="font-size:11px; color:#64748b; margin-top:3px; font-weight:600;">Mahsup sonrası kalan tüketim · Enerji maliyeti hesabı</div>
    </div>
    <select id="fat-ay-secim" onchange="faturaRender()" style="background:#ffffff; border:1px solid #cbd5e1; color:#1e293b; padding:8px 12px; border-radius:10px; font-size:12px; font-weight:700; font-family:inherit; cursor:pointer;">
      <option value="2026-01">Ocak 2026</option>
      <option value="2026-02">Şubat 2026</option>
      <option value="2026-03">Mart 2026</option>
      <option value="2026-04">Nisan 2026</option>
      <option value="2026-05">Mayıs 2026</option>
      <option value="2026-06" selected>Haziran 2026</option>
    </select>
  </div>

  <div id="fat-formul-bar" style="background:rgba(22,163,74,0.06); border:1px solid rgba(22,163,74,0.2); border-radius:10px; padding:9px 13px; font-size:11px; color:#15803d; margin-bottom:14px; font-weight:600; position:relative;">
    📐 <b style="color:#16a34a;">Enerji Maliyeti</b> = (PTF + YEKDEM) × 1,035 / 1000 &nbsp;·&nbsp; 
    <span class="fat-yekdem-cell" style="position:relative; display:inline-block; cursor:help; border-bottom:1px dashed #94a3b8;">
      <b style="color:#16a34a;">YEKDEM:</b> <span id="fat-yekdem-bilgi">1.088,89 TL/MWh ⚡ tahmini</span>
      <div id="fat-yekdem-popup" class="fat-popup" style="white-space:normal; min-width:280px; left:0; transform:none;"></div>
    </span>
  </div>

  <div class="fat-subtabs" id="fat-subtabs">
    <div class="fat-subtab t1" id="fst-T1" onclick="fatAboneSec('T1')">☀️ TEKYILDIZ 1</div>
    <div class="fat-subtab t2" id="fst-T2" onclick="fatAboneSec('T2')">⚡ TEKYILDIZ 2</div>
    <div class="fat-subtab a3 aktif" id="fst-A3" onclick="fatAboneSec('A3')">🏭 AKSARAY 3</div>
  </div>

  <div id="fat-kartlar"><div style="padding:30px; text-align:center; color:#64748b; font-size:12px;">Yükleniyor...</div></div>

</div>
<!-- ====================== FATURALANDIRMA SEKMESI SONU ====================== -->

<!-- ====================== T2 KIYAS SEKMESI ====================== -->
<div class="tab-content" id="t-t2kiyas" style="background:#f1f5f9; border-radius:16px; padding:16px; margin-top:8px;">

  <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 0 16px; border-bottom:1px solid #e2e8f0; margin-bottom:18px; flex-wrap:wrap;">
    <div>
      <div style="font-size:20px; font-weight:900; background:linear-gradient(135deg,#8b5cf6,#a855f7); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;">⚖️ T2 Kıyas</div>
      <div style="font-size:11px; color:#64748b; margin-top:3px; font-weight:600;">Saat saat mining ile bedelli satıs karsilastirmasi</div>
    </div>
    <select id="t2k-ay-secim" onchange="t2KiyasYukle()" style="background:#ffffff; border:1px solid #cbd5e1; color:#1e293b; padding:8px 12px; border-radius:10px; font-size:12px; font-weight:700; font-family:inherit; cursor:pointer;">
      <option value="2026-01">Ocak 2026</option>
      <option value="2026-02">Subat 2026</option>
      <option value="2026-03">Mart 2026</option>
      <option value="2026-04">Nisan 2026</option>
      <option value="2026-05">Mayis 2026</option>
      <option value="2026-06" selected>Haziran 2026</option>
    </select>
  </div>

  <div style="background:rgba(139,92,246,0.06); border:1px solid rgba(139,92,246,0.2); border-radius:10px; padding:10px 13px; font-size:11px; color:#6b21a8; margin-bottom:14px; line-height:1.6;">
    <b style="color:#8b5cf6;">A) Bedelli Satis:</b> 2,2537 TL/kWh sabit gelir<br>
    <b style="color:#8b5cf6;">B11) Sebekeden Cek + Mining:</b> Maliyet = (PTF+YEKDEM)/1000 × 1,035 + DB <br>
    <b style="color:#8b5cf6;">B12) GES&#39;i Mining&#39;de Kullan:</b> Firsat maliyeti = Bedelli Satis<br>
    <span style="color:#94a3b8;">Karar: B11 maliyeti < Bedelli ise T2 ABONE DEVAM, degilse ABONE DEGISTIR</span>
  </div>

  <div id="t2k-ozet" style="margin-bottom:14px;"></div>

  <div id="t2k-tablo"><div style="padding:30px; text-align:center; color:#64748b; font-size:12px;">Yükleniyor...</div></div>

  <!-- Hucre Detay Popup -->
  <div id="t2k-hucre-popup" onclick="t2HucreKapat(event)" style="display:none; position:fixed; inset:0; background:rgba(15,23,42,0.85); z-index:99999; backdrop-filter:blur(4px); align-items:center; justify-content:center; padding:14px;">
    <div onclick="event.stopPropagation()" style="background:#fff; border-radius:16px; max-width:420px; width:100%; max-height:90vh; overflow-y:auto; padding:18px; box-shadow:0 20px 60px rgba(0,0,0,0.5);">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding-bottom:10px; border-bottom:1px solid #e2e8f0; margin-bottom:12px;">
        <div id="t2k-popup-baslik" style="font-size:16px; font-weight:900; background:linear-gradient(135deg,#8b5cf6,#a855f7); -webkit-background-clip:text; -webkit-text-fill-color:transparent;">Yukleniyor</div>
        <button onclick="t2HucreKapat()" style="background:#f1f5f9; border:none; width:32px; height:32px; border-radius:8px; font-size:16px; font-weight:900; color:#475569; cursor:pointer;">✕</button>
      </div>
      <div id="t2k-popup-icerik" style="font-size:12px; color:#1e293b; line-height:1.6;"></div>
    </div>
  </div>


</div>
<!-- ====================== T2 KIYAS SEKMESI SONU ====================== -->

<!-- ====================== RAPOR SEKMESI ====================== -->
<div class="tab-content" id="t-rapor">
  <div style="font-size:11px;color:#64748b;background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;margin-bottom:12px;line-height:1.5;">
    Sistem aktivite raporu. GitHub commits API'den son güncellemeler. Saat değerleri TR (UTC+3).
  </div>
  <div style="background:linear-gradient(135deg,#0f172a,#1e293b);color:#fff;border-radius:14px;padding:18px 16px;margin-bottom:14px;">
    <div style="font-size:10px;letter-spacing:1.2px;color:#94a3b8;text-transform:uppercase;font-weight:700;margin-bottom:4px;">Sistem Saati (TR)</div>
    <div style="font-size:24px;font-weight:800;" id="rpr-saat">--:--</div>
    <div style="font-size:11px;color:#64748b;margin-top:6px;" id="rpr-tarih">Yükleniyor...</div>
  </div>
  <div id="rpr-saglik"></div>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <div style="font-size:13px;font-weight:800;color:#0f172a;">Güncelleme Geçmişi</div>
    <button onclick="raporYukle()" style="font-size:11px;font-weight:700;background:linear-gradient(135deg,#0ea5e9,#2563eb);color:#fff;border:none;border-radius:8px;padding:7px 14px;cursor:pointer;">Yenile</button>
  </div>
  <div id="rpr-icerik"><div class="empty-state">Yükleniyor...</div></div>
</div>
<!-- ====================== RAPOR SEKMESI SONU ====================== -->

<!-- Antminer Cihaz Detay Modal -->
<div class="modal-overlay" id="ant-modal" onclick="if(event.target.id==='ant-modal')kapatAntModal()">
<div class="modal" style="max-width:500px;">
<button onclick="kapatAntModal()" style="position:absolute;top:12px;right:12px;background:rgba(255,255,255,0.05);border:none;color:#cbd5e1;width:32px;height:32px;border-radius:50%;cursor:pointer;font-size:16px;">✕</button>
<div id="ant-modal-icerik"></div>
</div>
</div>

<!-- Cihazlarim Premium Modal -->
<div class="modal-overlay" id="cmm-modal" onclick="if(event.target.id==='cmm-modal')kapatCmmModal()">
<div class="modal" style="max-width:620px; max-height:90vh; overflow-y:auto; background:linear-gradient(180deg, #0a0f1f, #050917); border:1px solid rgba(251,191,36,0.2);">
<button onclick="kapatCmmModal()" style="position:absolute;top:12px;right:12px;background:rgba(255,255,255,0.05);border:none;color:#cbd5e1;width:34px;height:34px;border-radius:50%;cursor:pointer;font-size:16px;z-index:10;">✕</button>
<div id="cmm-modal-icerik"></div>
</div>
</div>

<div class="guncelleme" id="guncelleme"></div>
</div>

<div class="modal-overlay" id="modal" onclick="if(event.target.id==='modal')kapatModal()">
<div class="modal">
<button class="modal-close" onclick="kapatModal()">✕</button>
<div class="modal-header">
<div class="modal-icon">🖥️</div>
<div><div class="modal-title" id="m-title">—</div><div class="modal-sub" id="m-sub">—</div></div>
</div>
<div class="modal-stats">
<div class="modal-stat"><div class="modal-stat-lbl">Anlık</div><div class="modal-stat-val" style="color:#4ade80" id="m-anlik">—</div><div class="modal-stat-sub">TH/s</div></div>
<div class="modal-stat"><div class="modal-stat-lbl">1 Saat Ort.</div><div class="modal-stat-val" style="color:#60a5fa" id="m-h1">—</div><div class="modal-stat-sub">TH/s</div></div>
<div class="modal-stat"><div class="modal-stat-lbl">24h Ort.</div><div class="modal-stat-val" style="color:#a78bfa" id="m-h24">—</div><div class="modal-stat-sub">TH/s</div></div>
<div class="modal-stat"><div class="modal-stat-lbl">Durum</div><div class="modal-stat-val" id="m-durum">—</div><div class="modal-stat-sub" id="m-son">—</div></div>
</div>
<div class="section-title" style="margin:14px 0 8px">💰 Tahmini Kazanç</div>
<div class="modal-stats">
<div class="modal-stat"><div class="modal-stat-lbl">Bugün BTC</div><div class="modal-stat-val" style="color:#fbbf24" id="m-btc">—</div><div class="modal-stat-sub" id="m-tl">—</div></div>
<div class="modal-stat"><div class="modal-stat-lbl">Bugün USD</div><div class="modal-stat-val" style="color:#4ade80" id="m-usd">—</div><div class="modal-stat-sub">$</div></div>
</div>
<div class="section-title" style="margin:14px 0 8px">⏱️ Çalışma Saati</div>
<div class="modal-stats">
<div class="modal-stat"><div class="modal-stat-lbl">Bugün</div><div class="modal-stat-val" style="color:#22c55e" id="m-bugun-saat">—</div><div class="modal-stat-sub">saat</div></div>
<div class="modal-stat"><div class="modal-stat-lbl">Son 24h</div><div class="modal-stat-val" style="color:#22c55e" id="m-24h-saat">—</div><div class="modal-stat-sub">saat</div></div>
</div>
<div class="chart-wrap">
<div class="chart-title">📊 24 Saatlik Hashrate Grafiği</div>
<canvas class="chart-canvas" id="chart"></canvas>
<div class="tooltip" id="tooltip"><div class="tooltip-time" id="tt-time"></div><div class="tooltip-val" id="tt-val"></div></div>
</div>
</div>
</div>

<!-- ====================== İNVERTER DETAY MODAL ====================== -->
<div class="modal-overlay" id="inv-modal" onclick="if(event.target.id==='inv-modal')kapatInvModal()">
<div class="modal">
<button class="modal-close" onclick="kapatInvModal()">✕</button>
<div class="modal-header">
<div class="modal-icon" style="background:linear-gradient(135deg,#f59e0b,#fbbf24)">☀️</div>
<div><div class="modal-title" id="im-title">—</div><div class="modal-sub" id="im-sub">—</div></div>
</div>
<div class="modal-stats">
<div class="modal-stat"><div class="modal-stat-lbl">Anlık Güç</div><div class="modal-stat-val" style="color:#4ade80" id="im-anlik">—</div><div class="modal-stat-sub">kW</div></div>
<div class="modal-stat"><div class="modal-stat-lbl">Bugün Üretim</div><div class="modal-stat-val" style="color:#fbbf24" id="im-bugun">—</div><div class="modal-stat-sub">kWh</div></div>
<div class="modal-stat"><div class="modal-stat-lbl">Toplam Üretim</div><div class="modal-stat-val" style="color:#60a5fa" id="im-toplam">—</div><div class="modal-stat-sub">MWh</div></div>
<div class="modal-stat"><div class="modal-stat-lbl">Durum</div><div class="modal-stat-val" id="im-durum">—</div><div class="modal-stat-sub" id="im-sicaklik">—</div></div>
</div>
<div class="section-title" style="margin:14px 0 8px">⚙️ Teknik Bilgiler</div>
<div class="modal-stats">
<div class="modal-stat"><div class="modal-stat-lbl">Verimlilik</div><div class="modal-stat-val" style="color:#a78bfa" id="im-verim">—</div><div class="modal-stat-sub">%</div></div>
<div class="modal-stat"><div class="modal-stat-lbl">Sıcaklık</div><div class="modal-stat-val" style="color:#fb923c" id="im-temp">—</div><div class="modal-stat-sub">°C</div></div>
<div class="modal-stat"><div class="modal-stat-lbl">Frekans</div><div class="modal-stat-val" style="color:#60a5fa" id="im-freq">—</div><div class="modal-stat-sub">Hz</div></div>
<div class="modal-stat"><div class="modal-stat-lbl">Aktif Süre</div><div class="modal-stat-val" style="color:#22c55e" id="im-aktif">—</div><div class="modal-stat-sub">saat</div></div>
</div>
</div>
</div>
"""
print("HTML kısmı ok")

PANEL_HTML += """
<script>
const ZARARLI_ESIK = 2200;
let chartData = null;
let ososData = null;
let secilenAbone = 'tekyildiz_1';

function sekme(ad, btn) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('t-' + ad).classList.add('active');
  if (ad === 'osos') ososYukle();
  if (ad === 'inverter') invYukle();
  if (ad === 'antminer') antYukle();
  if (ad === 'cihazlarim') antYukle();
  if (ad === 'maliyetler') { mltDropdownDoldur().then(() => mltYukle()); utYukle(); }
  if (ad === 'mahsuplasma') mahsupYukle();
  if (ad === 'faturalandirma') faturaYukle();
  if (ad === 't2kiyas') t2KiyasYukle();
  if (ad === 'epias') epiasYukle();
  if (ad === 'f2pool') { try { if (window.f2GunlukHam && window.f2GunlukHam.length) f2Render(); } catch(e) { console.error('f2 sekme render:', e); } }
  if (ad === 'rapor') raporYukle();
}

// === RAPOR SEKMESI ===
var raporSaatTimer = null;

function raporSaatGuncelle() {
  var el = document.getElementById('rpr-saat');
  var sub = document.getElementById('rpr-tarih');
  if (!el) return;
  var now = new Date();
  var gunler = ['Pazar','Pazartesi','Sali','Carsamba','Persembe','Cuma','Cumartesi'];
  var aylar = ['Ocak','Subat','Mart','Nisan','Mayis','Haziran','Temmuz','Agustos','Eylul','Ekim','Kasim','Aralik'];
  var hh = String(now.getHours()).padStart(2, '0');
  var mm = String(now.getMinutes()).padStart(2, '0');
  var ss = String(now.getSeconds()).padStart(2, '0');
  el.textContent = hh + ':' + mm + ':' + ss;
  if (sub) sub.textContent = gunler[now.getDay()] + ' ' + now.getDate() + ' ' + aylar[now.getMonth()] + ' ' + now.getFullYear();
}

function raporYukle() {
  if (raporSaatTimer) clearInterval(raporSaatTimer);
  raporSaatGuncelle();
  raporSaatTimer = setInterval(raporSaatGuncelle, 1000);

  var kon = document.getElementById('rpr-icerik');
  if (!kon) return;
  kon.innerHTML = '<div class="empty-state">Yukleniyor...</div>';

  fetch('/api/rapor').then(function(r){return r.json();}).then(function(d){
    if (d.hata) {
      kon.innerHTML = '<div class="empty-state">Hata: ' + d.hata + '</div>';
      return;
    }
    // Saglik kartlari
    var sagKon = document.getElementById('rpr-saglik');
    if (sagKon && d.saglik) {
      var sagHtml = '';
      var rozeAd = {ok: 'CALISIYOR', yavas: 'GECIKMIS', calismiyor: 'CALISMIYOR', bilinmiyor: 'BILINMIYOR'};
      var renkler = {ok: '#22c55e', yavas: '#f59e0b', calismiyor: '#ef4444', bilinmiyor: '#94a3b8'};
      var bgRenk = {ok: 'rgba(34,197,94,0.10)', yavas: 'rgba(251,191,36,0.12)', calismiyor: 'rgba(239,68,68,0.14)', bilinmiyor: '#f8fafc'};
      var keys = Object.keys(d.saglik);
      for (var i = 0; i < keys.length; i++) {
        var ad = keys[i];
        var info = d.saglik[ad];
        var dur = info.durum;
        var detay = '';
        if (info.son_calisma) {
          detay = 'Son: ' + info.son_calisma;
          if (info.saat_once != null) {
            if (info.saat_once < 1) detay += ' (' + Math.round(info.saat_once * 60) + ' dk once)';
            else detay += ' (' + info.saat_once + ' saat once)';
          }
        } else {
          detay = 'Son 50 commit icinde otomatik yazim yok.';
        }
        sagHtml += '<div style="display:flex;justify-content:space-between;align-items:center;padding:11px 14px;border-radius:11px;margin-bottom:8px;background:' + bgRenk[dur] + ';border:1px solid ' + renkler[dur] + ';">';
        sagHtml += '<div style="flex:1;min-width:0;">';
        sagHtml += '<div style="font-size:12px;font-weight:800;color:#0f172a;margin-bottom:3px;">' + ad + '</div>';
        sagHtml += '<div style="font-size:10px;color:#64748b;line-height:1.4;">' + detay + '</div>';
        sagHtml += '</div>';
        sagHtml += '<div style="font-size:10px;font-weight:800;padding:5px 10px;border-radius:10px;color:#fff;background:' + renkler[dur] + ';margin-left:8px;">' + rozeAd[dur] + '</div>';
        sagHtml += '</div>';
      }
      sagKon.innerHTML = sagHtml;
      // Debug satırı kartların altına ekle
      if (d.debug) {
        const dbug = d.debug;
        const renkDbg = (dbug.hata || dbug.commit_say === 0) ? '#ef4444' : '#22c55e';
        let dbg = '<div style="background:#1e293b;border:1px solid ' + renkDbg + ';color:#cbd5e1;padding:10px 12px;border-radius:10px;margin-bottom:10px;font-size:11px;line-height:1.5;font-family:monospace;">';
        dbg += '<div style="color:' + renkDbg + ';font-weight:800;margin-bottom:4px;">🔍 DEBUG (rapor endpoint)</div>';
        dbg += 'Token: ' + (dbug.token_var_mi ? '✓ tanımlı' : '✗ TANIMLI DEĞİL') + '<br>';
        if (dbug.token_tip) dbg += 'Token tipi: ' + dbug.token_tip + ' (' + (dbug.token_onek || '') + ')<br>';
        dbg += 'Repo: ' + dbug.repo + '<br>';
        dbg += 'Çekilen commit sayısı: ' + dbug.commit_say + '<br>';
        if (dbug.hata) dbg += '<span style="color:#fca5a5;font-weight:700;">Hata: ' + dbug.hata + '</span>';
        dbg += '</div>';
        sagKon.insertAdjacentHTML('beforeend', dbg);
      }
    }
    // Olaylar listesi
    if (!d.olaylar || d.olaylar.length === 0) {
      kon.innerHTML = '<div class="empty-state">Henuz aktivite kaydi yok.</div>';
      return;
    }
    var html = '';
    var aylar2 = ['Oca','Sub','Mar','Nis','May','Haz','Tem','Agu','Eyl','Eki','Kas','Ara'];
    for (var j = 0; j < d.olaylar.length; j++) {
      var grup = d.olaylar[j];
      var parcalar = grup.gun.split('-');
      var tarihEt = parseInt(parcalar[2]) + ' ' + aylar2[parseInt(parcalar[1]) - 1] + ' ' + parcalar[0];
      html += '<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;margin-bottom:10px;overflow:hidden;">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:11px 14px;background:#f8fafc;border-bottom:1px solid #e2e8f0;">';
      html += '<span style="font-size:12px;font-weight:700;color:#0f172a;">' + tarihEt + '</span>';
      html += '<span style="font-size:10px;color:#64748b;background:#e2e8f0;padding:3px 8px;border-radius:10px;">' + grup.kayitlar.length + ' kayit</span>';
      html += '</div>';
      for (var k = 0; k < grup.kayitlar.length; k++) {
        var ky = grup.kayitlar[k];
        html += '<div style="display:flex;gap:10px;padding:9px 14px;border-bottom:1px solid #f1f5f9;">';
        html += '<div style="font-size:11px;font-weight:700;color:#64748b;min-width:42px;">' + ky.saat + '</div>';
        html += '<div style="font-size:14px;min-width:20px;">' + (ky.ikon || '') + '</div>';
        html += '<div style="flex:1;min-width:0;">';
        html += '<div style="font-size:11px;font-weight:800;color:#0f172a;margin-bottom:2px;">' + (ky.etiket || '') + '</div>';
        html += '<div style="font-size:10px;color:#64748b;line-height:1.4;word-break:break-all;">' + (ky.mesaj || '') + '</div>';
        html += '</div>';
        html += '</div>';
      }
      html += '</div>';
    }
    kon.innerHTML = html;
  }).catch(function(e){
    kon.innerHTML = '<div class="empty-state">Baglanti hatasi: ' + e.message + '</div>';
  });
}

// EPIAS sekmesi - aylik PTF dropdown ile
let epiasPtfData = null;  // tum aylarin PTF verisi

// YEKDEM aylik veriler (EPIAS Seffaflik kayitlari)
// 'gercek': ay sonu kesinlesmis bedel (yesil)
// 'ongoru': resmi olarak yayinlanan ongoru (turuncu - gerceklesmediyse)
// 'tahmin': onceki ayin sapmasi ile uyarlanmis (sari - sadece gercek+ongoru yoksa)
const EPIAS_YEKDEM = {
  '2026-01': {ongoru: 162.727, gercek: 162.849},
  '2026-02': {ongoru: 479.347, gercek: 480.015},
  '2026-03': {ongoru: 747.797, gercek: 747.398},
  '2026-04': {ongoru: 574.54,  gercek: 1038.343},
  '2026-05': {ongoru: 602.51,  gercek: 1306.10},
  '2026-06': {ongoru: 580.99,  gercek: null},
  '2026-07': {ongoru: 189.15,  gercek: null},
  '2026-08': {ongoru: 213.89,  gercek: null},
};

const AY_ISIM = ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'];

// Bir ay icin YEKDEM degeri ve durumunu hesapla
// Donus: {deger, durum: 'kesin'|'ongoru'|'tahmin', not, ongoru, gercek, kat}
function yekdemHesapla(ay) {
  const v = EPIAS_YEKDEM[ay] || {};
  // 1) Gerceklesme varsa - YESIL
  if (v.gercek !== null && v.gercek !== undefined) {
    return {deger: v.gercek, durum: 'kesin', not: '✓ Gerçekleşmiş', ongoru: v.ongoru, gercek: v.gercek};
  }
  // 2) Bir onceki ayin sapmasi varsa - SARI (tahmin)
  // Onceki ay = ay - 1
  const yil = parseInt(ay.substring(0, 4), 10);
  const a = parseInt(ay.substring(5, 7), 10);
  let oncekiYil = yil, oncekiA = a - 1;
  if (oncekiA < 1) { oncekiA = 12; oncekiYil -= 1; }
  const oncekiKey = oncekiYil + '-' + String(oncekiA).padStart(2, '0');
  const onceki = EPIAS_YEKDEM[oncekiKey];
  if (v.ongoru !== undefined && onceki && onceki.gercek !== null && onceki.ongoru !== undefined) {
    const kat = onceki.gercek / onceki.ongoru;
    const tahmin = v.ongoru * kat;
    return {
      deger: tahmin,
      durum: 'tahmin',
      not: '⚡ Önceki ay sapması (' + kat.toFixed(4) + '×)',
      ongoru: v.ongoru,
      gercek: null,
      kat: kat,
      oncekiAy: oncekiKey,
      oncekiOngoru: onceki.ongoru,
      oncekiGercek: onceki.gercek
    };
  }
  // 3) Sadece ongoru varsa - TURUNCU
  if (v.ongoru !== undefined) {
    return {deger: v.ongoru, durum: 'ongoru', not: '📋 Resmi öngörü', ongoru: v.ongoru, gercek: null};
  }
  // Hicbiri yoksa
  return null;
}

// Tum YEKDEM kartlarini render et
function yekdemKartlariRender() {
  const grid = document.getElementById('yekdem-kart-grid');
  if (!grid) return;
  const aylar = Object.keys(EPIAS_YEKDEM).sort();
  let html = '';
  aylar.forEach(function(ay) {
    const h = yekdemHesapla(ay);
    if (!h) return;
    const yil = ay.substring(0, 4);
    const a = parseInt(ay.substring(5, 7), 10) - 1;
    const ayAd = AY_ISIM[a] + ' ' + yil;
    
    // Tooltip icerigi - sapma detayi tahmin icin
    let detay = '';
    if (h.durum === 'tahmin') {
      const fark = (h.kat - 1) * 100;
      detay = '<div class="yk-not">Önceki: ' + ay_fmt(h.oncekiOngoru) + ' → ' + ay_fmt(h.oncekiGercek) + ' (+%' + fark.toFixed(1) + ')</div>';
    } else if (h.durum === 'kesin' && h.ongoru) {
      const sapma = ((h.gercek / h.ongoru) - 1) * 100;
      const isaret = sapma >= 0 ? '+' : '';
      detay = '<div class="yk-not">Öngörü: ' + ay_fmt(h.ongoru) + ' (sapma ' + isaret + sapma.toFixed(1) + '%)</div>';
    } else if (h.durum === 'ongoru') {
      detay = '<div class="yk-not">Ay sonu revize edilecek</div>';
    }
    
    html += '<div class="yekdem-kart ' + h.durum + '">';
    html += '<div class="yk-ay">' + ayAd + '</div>';
    html += '<div class="yk-deger">' + ay_fmt(h.deger) + '</div>';
    html += '<div class="yk-birim">' + h.not + '</div>';
    html += detay;
    html += '</div>';
  });
  grid.innerHTML = html;
}

function ay_fmt(v) {
  if (v === null || v === undefined) return '—';
  return Number(v).toLocaleString('tr-TR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

async function epiasYukle() {
  // 0. YEKDEM kartlarini render et
  yekdemKartlariRender();

  // 1. PTF Dropdown'u doldur - HER SEKME ACILISINDA YENIDEN CEK
  // Cron yazdigi yeni gunleri gormek icin cache yapmiyoruz
  const sel = document.getElementById('epias-ay-secim');
  try {
    const r = await fetch('/api/aylik_ptf?_=' + Date.now());
    if (r.ok) epiasPtfData = await r.json();
    else epiasPtfData = epiasPtfData || {};
  } catch (e) {
    console.error('EPIAS PTF cekilemedi:', e);
    epiasPtfData = epiasPtfData || {};
  }
  // Dropdown'u doldur - en yeni ay ustte
  const aylar = Object.keys(epiasPtfData).sort().reverse();
  if (aylar.length === 0) {
    sel.innerHTML = '<option value="">Veri yok</option>';
    return;
  }
  const mevcutSecim = sel.value;
  const ayIsim = ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'];
  sel.innerHTML = aylar.map(function(ay) {
    const yil = ay.substring(0, 4);
    const a = parseInt(ay.substring(5, 7), 10) - 1;
    return '<option value="' + ay + '">' + ayIsim[a] + ' ' + yil + '</option>';
  }).join('');
  // Onceki secim varsa onu koru, yoksa guncel ay
  if (mevcutSecim && aylar.indexOf(mevcutSecim) !== -1) {
    sel.value = mevcutSecim;
  } else {
    const bugun = new Date();
    const gunAy = bugun.getFullYear() + '-' + String(bugun.getMonth() + 1).padStart(2, '0');
    if (aylar.indexOf(gunAy) !== -1) sel.value = gunAy;
    else sel.value = aylar[0];
  }
  epiasAyDegisti();
}

function epiasAyDegisti() {
  const sel = document.getElementById('epias-ay-secim');
  if (!sel || !epiasPtfData) return;
  const ay = sel.value;
  const ayIsim = ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'];
  const a = parseInt(ay.substring(5, 7), 10) - 1;
  const yil = ay.substring(0, 4);
  document.getElementById('epias-baslik').textContent = (ayIsim[a] || ay) + ' ' + yil + ' PTF Tablosu';
  aylikRender(epiasPtfData[ay] || {});
}

function renkSinif(v) {
  if (v >= ZARARLI_ESIK) return 'l5 kapali-cell';
  if (v < 500) return 'l0';
  if (v < 1000) return 'l1';
  if (v < 2000) return 'l2';
  return 'l3';
}


function aylikRender(aylikData) {
  if (!aylikData) return;
  const gunler = Object.keys(aylikData).sort();
  if (gunler.length === 0) return;
  let thead = '<tr><th class="saat-head">Saat</th>';
  gunler.forEach(g => { thead += '<th>' + g + '</th>'; });
  thead += '<th class="saat-head">Ort</th></tr>';
  document.getElementById('aylik-thead').innerHTML = thead;
  let tbody = '';
  for (let saat = 0; saat < 24; saat++) {
    tbody += '<tr><td class="saat-cell">' + String(saat).padStart(2,'0') + '</td>';
    let toplam = 0, sayi = 0;
    gunler.forEach(g => {
      const v = aylikData[g][saat] || 0;
      tbody += '<td class="' + renkSinif(v) + '">' + Math.round(v) + '</td>';
      toplam += v; sayi++;
    });
    const ort = sayi ? toplam/sayi : 0;
    tbody += '<td class="saat-cell l2">' + Math.round(ort) + '</td></tr>';
  }
  tbody += '<tr style="border-top:2px solid rgba(34,197,94,0.4)"><td class="saat-cell" style="background:linear-gradient(180deg,#16a34a,#15803d);color:white">Ort.</td>';
  let ayToplam = 0, ayCount = 0;
  gunler.forEach(g => {
    const saatler = aylikData[g];
    const t = saatler.reduce((a,b) => a+b, 0);
    const o = t / saatler.length;
    tbody += '<td class="' + renkSinif(o) + '" style="font-weight:900">' + Math.round(o) + '</td>';
    ayToplam += t; ayCount += saatler.length;
  });
  const ayOrt = ayCount ? ayToplam/ayCount : 0;
  tbody += '<td class="saat-cell l2" style="font-weight:900">' + Math.round(ayOrt) + '</td></tr>';
  document.getElementById('aylik-tbody').innerHTML = tbody;
}

function durumBilgisi(durum) {
  if (durum === 'calisiyor') return {label:'Çalışıyor', cls:'badge-on', ico:'✅', renk:'#4ade80'};
  if (durum === 'yavasliyor') return {label:'Yavaşlıyor', cls:'badge-slow', ico:'⚠️', renk:'#fbbf24'};
  if (durum === 'uyuyor') return {label:'Uyuyor', cls:'badge-sleep', ico:'😴', renk:'#fcd34d'};
  return {label:'Kapalı', cls:'badge-off', ico:'❌', renk:'#f87171'};
}

// ════════════════ F2POOL GRAFIK + ZAMAN DILIMI ════════════════
window.f2Zaman = 'gunluk';
window.f2Metric = 'btc';

function f2ZamanSec(z, btn) {
  window.f2Zaman = z;
  document.querySelectorAll('.f2-zaman-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  f2Render();
}
function f2MetricSec(m, btn) {
  window.f2Metric = m;
  document.querySelectorAll('.f2-metric-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  f2Render();
}

function f2AySeceneksDoldur() {
  const ham = window.f2GunlukHam || [];
  const aylar = {};
  ham.forEach(g => { aylar[g.iso.slice(0,7)] = true; });

  // Veriden gelmeyen aylari da ekle (panel arsivinde olabilir)
  // Son 12 ayi otomatik ekle
  const bugun = new Date();
  for (let i = 0; i < 12; i++) {
    const d = new Date(bugun.getFullYear(), bugun.getMonth() - i, 1);
    const ay = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
    aylar[ay] = true;
  }

  const sel = document.getElementById('f2-ay-secim');
  if (!sel) return;
  const mevcut = sel.value;
  let html = '<option value="tum">Tüm Veriler (30 gün)</option>';
  const ayAd = ['','Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'];
  Object.keys(aylar).sort().reverse().forEach(ay => {
    const [yil, m] = ay.split('-');
    html += '<option value="' + ay + '">' + ayAd[parseInt(m)] + ' ' + yil + '</option>';
  });
  sel.innerHTML = html;
  if (mevcut && sel.querySelector('option[value="' + mevcut + '"]')) sel.value = mevcut;
}

function f2VeriFiltrele() {
  let ham = (window.f2GunlukHam || []).slice();
  const ay = document.getElementById('f2-ay-secim') ? document.getElementById('f2-ay-secim').value : 'tum';
  if (ay !== 'tum') ham = ham.filter(g => g.iso.slice(0,7) === ay);
  return ham;
}

// ISO tarihten hafta anahtari (yil-hafta no)
function f2HaftaKey(iso) {
  const d = new Date(iso + 'T00:00:00');
  const onceki = new Date(d);
  onceki.setDate(d.getDate() - ((d.getDay() + 6) % 7)); // Pazartesi'ye git
  return onceki.toISOString().slice(0,10);
}

function f2Grupla(ham, zaman) {
  // Donus: [{etiket, btc, tl, hash_ort, gun_sayisi, iso_bas}]
  if (zaman === 'gunluk') {
    return ham.map(g => ({
      etiket: g.iso.slice(8,10) + '.' + g.iso.slice(5,7),
      btc: g.btc, tl: g.tl, hash_ort: g.hash, gun_sayisi: 1, iso_bas: g.iso
    }));
  }
  const gruplar = {};
  ham.forEach(g => {
    const key = (zaman === 'haftalik') ? f2HaftaKey(g.iso) : g.iso.slice(0,7);
    if (!gruplar[key]) gruplar[key] = { btc:0, tl:0, hash_top:0, gun:0, iso_bas:g.iso };
    gruplar[key].btc += g.btc;
    gruplar[key].tl += g.tl;
    gruplar[key].hash_top += g.hash;
    gruplar[key].gun++;
    if (g.iso < gruplar[key].iso_bas) gruplar[key].iso_bas = g.iso;
  });
  const ayAd = ['','Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara'];
  return Object.keys(gruplar).sort().map(key => {
    const gr = gruplar[key];
    let etiket;
    if (zaman === 'haftalik') {
      const d = new Date(key + 'T00:00:00');
      etiket = d.getDate() + '.' + ayAd[d.getMonth()+1];
    } else {
      const [yil, m] = key.split('-');
      etiket = ayAd[parseInt(m)] + ' ' + yil.slice(2);
    }
    return { etiket: etiket, btc: gr.btc, tl: gr.tl, hash_ort: gr.hash_top/gr.gun, gun_sayisi: gr.gun, iso_bas: gr.iso_bas, key: key };
  });
}

function f2Render() {
  const ham = f2VeriFiltrele();
  if (ham.length === 0) {
    document.getElementById('daily-list').innerHTML = '<div class="empty-state">Veri yok</div>';
    return;
  }
  const zaman = window.f2Zaman, metric = window.f2Metric;
  const gruplar = f2Grupla(ham, zaman);

  // Baslik
  const zamanAd = { gunluk:'Günlük', haftalik:'Haftalık', aylik:'Aylık' };
  document.getElementById('f2-chart-baslik').textContent = '📊 ' + zamanAd[zaman] + ' Genel Görünüm';
  document.getElementById('f2-liste-baslik').textContent = '📅 ' + zamanAd[zaman] + ' Üretim';

  // Cok katmanli grafik verisi hazirla
  // Ortalama verimlilik (J/TH) - antData'dan, yoksa varsayilan 25
  let ortJth = 25.0;
  if (window.antData && window.antData.devices && window.antData.devices.length > 0) {
    let topW = 0, topHr = 0;
    window.antData.devices.forEach(d => {
      const hr = d.hashrate_TH || 0;
      if (hr > 0) { topW += hr * antVerimlilik(d.model); topHr += hr; }
    });
    if (topHr > 0) ortJth = topW / topHr;
  }
  const btcKur = window.f2BtcKur || 0;
  const katmanlar = {
    etiketler: gruplar.map(g => g.etiket),
    hashrate: gruplar.map(g => g.hash_ort),                                  // TH/s ortalama
    uretim:   gruplar.map(g => g.btc),                                       // BTC (donem toplami)
    // Elektrik tuketimi (kWh): hashrate(TH/s) x J/TH x saat / 1000
    //   gunluk: 24 saat, haftalik: gun_sayisi*24, aylik: gun_sayisi*24
    tuketim:  gruplar.map(g => (g.hash_ort * ortJth * (g.gun_sayisi * 24)) / 1000),
    fiyat:    gruplar.map(() => btcKur),                                     // BTC fiyati (anlik, sabit cizgi)
  };
  f2ChartCokKatman(katmanlar);

  // Istatistikler
  const topBtc = ham.reduce((s,g) => s+g.btc, 0);
  const topTl = ham.reduce((s,g) => s+g.tl, 0);
  const ortHash = ham.reduce((s,g) => s+g.hash, 0) / ham.length;
  const gunSayisi = ham.length;
  const ortBtcFiyat = window.f2BtcKur || 0;

  // Hero karti - donem ozeti
  const heroLblEl = document.getElementById('f2-hero-lbl');
  const aySecim = document.getElementById('f2-ay-secim');
  if (heroLblEl) {
    let donemAd = 'Tüm Dönem (' + gunSayisi + ' gün)';
    if (aySecim && aySecim.value !== 'tum') {
      const opt = aySecim.options[aySecim.selectedIndex];
      donemAd = (opt ? opt.text : '') + ' (' + gunSayisi + ' gün)';
    }
    heroLblEl.textContent = donemAd;
  }
  const heroBtcEl = document.getElementById('f2-hero-btc');
  if (heroBtcEl) heroBtcEl.innerHTML = topBtc.toFixed(5) + ' <span>BTC</span>';
  const heroTlEl = document.getElementById('f2-hero-tl');
  if (heroTlEl) heroTlEl.textContent = Math.round(topTl).toLocaleString('tr-TR') + ' ₺';
  const heroSubEl = document.getElementById('f2-hero-sub');
  if (heroSubEl) heroSubEl.textContent = 'Ort. ' + Math.round(topTl/gunSayisi).toLocaleString('tr-TR') + ' ₺/gün';

  // KPI: gunluk ortalama (her zaman BTC bazli, net)
  const ortEl = document.getElementById('f2-ist-ort');
  const ortSubEl = document.getElementById('f2-ist-ort-sub');
  if (metric === 'tl') {
    if (ortEl) ortEl.textContent = Math.round(topTl/gunSayisi).toLocaleString('tr-TR') + ' ₺';
    if (ortSubEl) ortSubEl.textContent = 'TL/gün';
  } else {
    if (ortEl) ortEl.textContent = (topBtc/gunSayisi).toFixed(5);
    if (ortSubEl) ortSubEl.textContent = 'BTC/gün';
  }
  const topEl = document.getElementById('f2-ist-top');
  if (topEl) topEl.textContent = topBtc.toFixed(5);
  const hashEl = document.getElementById('f2-ist-hash');
  if (hashEl) hashEl.textContent = Math.round(ortHash).toLocaleString('tr-TR');
  const fiyatEl = document.getElementById('f2-ist-fiyat');
  if (fiyatEl) fiyatEl.textContent = ortBtcFiyat > 0 ? (Math.round(ortBtcFiyat).toLocaleString('tr-TR') + ' ₺') : '—';

  // Liste (haftalik/aylik dilimli)
  f2ListeRender(ham, zaman, gruplar);
}

function f2ListeRender(ham, zaman, gruplar) {
  let html = '';
  if (zaman === 'gunluk') {
    // Gunluk: haftalik dilimlere bol
    const haftalar = {};
    ham.slice().reverse().forEach(g => {
      const hk = f2HaftaKey(g.iso);
      if (!haftalar[hk]) haftalar[hk] = [];
      haftalar[hk].push(g);
    });
    const ayAd = ['','Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara'];
    Object.keys(haftalar).sort().reverse().forEach(hk => {
      const gunler = haftalar[hk];
      const hBtc = gunler.reduce((s,g)=>s+g.btc,0);
      const hTl = gunler.reduce((s,g)=>s+g.tl,0);
      const d = new Date(hk + 'T00:00:00');
      const son = new Date(d); son.setDate(d.getDate()+6);
      html += '<div class="f2-hafta-baslik" style="display:flex; align-items:center;">📆 ' + d.getDate() + '.' + ayAd[d.getMonth()+1] + ' - ' + son.getDate() + '.' + ayAd[son.getMonth()+1];
      html += '<span class="f2-hafta-ozet">' + hBtc.toFixed(5) + ' BTC · ' + Math.round(hTl).toLocaleString('tr-TR') + ' ₺</span></div>';
      gunler.forEach(g => {
        const tarih = g.iso.slice(8,10) + '.' + g.iso.slice(5,7) + '.' + g.iso.slice(0,4);
        html += '<div class="daily-item f2-gun-tikla" onclick="f2GunAc(&quot;' + g.iso + '&quot;, this)" style="cursor:pointer;">'
          + '<div class="daily-date"><span class="f2-gun-ok">▶</span> ' + tarih + '</div>'
          + '<div><div class="daily-btc">' + g.btc.toFixed(5) + ' BTC</div><div class="daily-hash">' + Math.round(g.hash).toLocaleString('tr-TR') + ' TH/s</div></div>'
          + '<div class="daily-tl"><div class="daily-tl-val">' + Math.round(g.tl).toLocaleString('tr-TR') + ' TL</div></div></div>';
        html += '<div class="f2-saat-konteyner" id="f2-saat-' + g.iso + '"></div>';
      });
    });
  } else {
    // Haftalik/Aylik: grup ozet satirlari
    gruplar.slice().reverse().forEach(gr => {
      html += '<div class="daily-item"><div class="daily-date">' + gr.etiket + '</div><div><div class="daily-btc">' + gr.btc.toFixed(5) + ' BTC</div><div class="daily-hash">' + Math.round(gr.hash_ort).toLocaleString('tr-TR') + ' TH/s ort · ' + gr.gun_sayisi + ' gün</div></div><div class="daily-tl"><div class="daily-tl-val">' + Math.round(gr.tl).toLocaleString('tr-TR') + ' TL</div></div></div>';
    });
  }
  document.getElementById('daily-list').innerHTML = html || '<div class="empty-state">Veri yok</div>';
}

// Drill-down: gune tikla -> saatleri ac
window.f2AcikGun = null;
function f2GunAc(iso, el) {
  const kon = document.getElementById('f2-saat-' + iso);
  if (!kon) return;
  // Acik olani kapat (toggle)
  if (window.f2AcikGun === iso) {
    kon.innerHTML = '';
    window.f2AcikGun = null;
    if (el) el.querySelector('.f2-gun-ok').textContent = '▶';
    return;
  }
  // Onceki acigi kapat
  if (window.f2AcikGun) {
    const onceki = document.getElementById('f2-saat-' + window.f2AcikGun);
    if (onceki) onceki.innerHTML = '';
    document.querySelectorAll('.f2-gun-ok').forEach(o => o.textContent = '▶');
  }
  window.f2AcikGun = iso;
  if (el) el.querySelector('.f2-gun-ok').textContent = '▼';
  kon.innerHTML = '<div class="f2-saat-yukleniyor">⏳ Saatlik veri yükleniyor...</div>';

  fetch('/api/f2pool_saatlik?gun=' + iso)
    .then(r => r.json())
    .then(d => {
      if (!d.veri_var) {
        kon.innerHTML = '<div class="f2-saat-bos">📭 Bu gün için saatlik veri yok<br><span style="font-size:9px;">(F2Pool sadece son ~48 saati saklar)</span></div>';
        return;
      }
      // Ortalama verimlilik (tuketim icin)
      let ortJth = 25.0;
      if (window.antData && window.antData.devices) {
        let tW=0, tH=0;
        window.antData.devices.forEach(x => { const hr=x.hashrate_TH||0; if(hr>0){tW+=hr*antVerimlilik(x.model); tH+=hr;} });
        if (tH>0) ortJth = tW/tH;
      }
      let h = '<div class="f2-saat-tablo">';
      h += '<div class="f2-saat-row f2-saat-head"><span>Saat</span><span>Hashrate</span><span>Üretim</span><span>Tüketim</span><span>Cihaz</span></div>';
      d.saatler.forEach(s => {
        if (s.hash <= 0) return;  // bos saati atla
        const tuketim = (s.hash * ortJth) / 1000;  // kWh (1 saat)
        h += '<div class="f2-saat-row f2-saat-tikla" onclick="f2SaatAc(&quot;' + iso + '&quot;,&quot;' + s.saat + '&quot;,this)">'
          + '<span class="f2-saat-no"><span class="f2-saat-ok">▸</span>' + s.saat + ':00</span>'
          + '<span style="color:#2563eb;font-weight:800;">' + Math.round(s.hash).toLocaleString('tr-TR') + ' <small>TH/s</small></span>'
          + '<span style="color:#d97706;font-weight:800;">' + s.btc.toFixed(6) + '</span>'
          + '<span style="color:#dc2626;font-weight:800;">' + tuketim.toFixed(1) + ' <small>kWh</small></span>'
          + '<span style="color:#16a34a;font-weight:800;">' + s.cihaz_sayisi + '</span>'
          + '</div>';
        h += '<div class="f2-cihaz-konteyner" id="f2-cihaz-' + iso + '-' + s.saat + '"></div>';
      });
      h += '</div>';
      // Saatlik veriyi sakla (cihaz drill icin)
      window.f2SaatlikVeri = window.f2SaatlikVeri || {};
      window.f2SaatlikVeri[iso] = d.saatler;
      window.f2SaatlikJth = ortJth;
      kon.innerHTML = h;
    })
    .catch(e => {
      kon.innerHTML = '<div class="f2-saat-bos">⚠️ Veri alınamadı</div>';
    });
}

// Drill-down: saate tikla -> cihazlari ac
window.f2AcikSaat = null;
function f2SaatAc(iso, saat, el) {
  const kon = document.getElementById('f2-cihaz-' + iso + '-' + saat);
  if (!kon) return;
  const anahtar = iso + '-' + saat;
  if (window.f2AcikSaat === anahtar) {
    kon.innerHTML = '';
    window.f2AcikSaat = null;
    if (el) el.querySelector('.f2-saat-ok').textContent = '▸';
    return;
  }
  if (window.f2AcikSaat) {
    const o = document.getElementById('f2-cihaz-' + window.f2AcikSaat);
    if (o) o.innerHTML = '';
    document.querySelectorAll('.f2-saat-ok').forEach(x => x.textContent = '▸');
  }
  window.f2AcikSaat = anahtar;
  if (el) el.querySelector('.f2-saat-ok').textContent = '▾';

  const saatler = (window.f2SaatlikVeri || {})[iso] || [];
  const s = saatler.find(x => x.saat === saat);
  if (!s || !s.cihazlar || Object.keys(s.cihazlar).length === 0) {
    kon.innerHTML = '<div class="f2-cihaz-bos">Cihaz verisi yok</div>';
    return;
  }
  const ortJth = window.f2SaatlikJth || 25.0;
  // Cihaz model bilgisi (antData'dan eslesti)
  const modelMap = {};
  if (window.antData && window.antData.devices) {
    window.antData.devices.forEach(d => {
      const w = d.havuz_worker || d.actual_worker || d.saha_worker || d.name;
      if (w) modelMap[w] = d.model;
    });
  }
  let h = '<div class="f2-cihaz-liste">';
  const sirali = Object.entries(s.cihazlar).sort((a,b) => b[1]-a[1]);
  sirali.forEach(([name, hash]) => {
    const model = modelMap[name] || '';
    const jth = model ? antVerimlilik(model) : ortJth;
    const guc = (hash * jth) / 1000;  // kW
    h += '<div class="f2-cihaz-satir">'
      + '<span class="f2-cihaz-ad">⛏️ ' + name + (model ? ' <small>(' + model + ')</small>' : '') + '</span>'
      + '<span style="color:#2563eb;font-weight:700;">' + Math.round(hash) + ' TH/s</span>'
      + '<span style="color:#dc2626;font-weight:700;">' + guc.toFixed(2) + ' kW</span>'
      + '</div>';
  });
  h += '</div>';
  kon.innerHTML = h;
}

function f2ChartCiz(etiketler, degerler, metric) {
  const canvas = document.getElementById('f2-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = 190;
  canvas.width = W * dpr; canvas.height = H * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0,0,W,H);
  if (degerler.length === 0) return;

  const padL = 8, padR = 8, padT = 16, padB = 24;
  const cw = W - padL - padR, ch = H - padT - padB;
  const maxV = Math.max(...degerler) * 1.1 || 1;
  const renk = metric === 'btc' ? OTO_G.gunesK : (metric === 'tl' ? OTO_G.yesilK : OTO_G.ptfK);
  const n = degerler.length;
  const barW = Math.min(cw / n * 0.7, 40);
  const gap = cw / n;

  degerler.forEach((v, i) => {
    const x = padL + gap * i + (gap - barW)/2;
    const h = (v / maxV) * ch;
    const y = padT + ch - h;
    const grad = ctx.createLinearGradient(0, y, 0, padT+ch);
    grad.addColorStop(0, renk);
    grad.addColorStop(1, renk + '44');
    ctx.fillStyle = grad;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, barW, h, [4,4,0,0]);
    else ctx.rect(x, y, barW, h);
    ctx.fill();
    if (n <= 16 || i % Math.ceil(n/16) === 0) {
      ctx.fillStyle = '#64748b';
      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText(etiketler[i], x + barW/2, H - 8);
    }
  });
}

// Cok katmanli grafik: hashrate (sutun) + uretim/tuketim/fiyat (cizgiler)
// Sol eksen: hashrate & tuketim (kWh/TH-s) | Sag eksen: BTC & fiyat
function f2ChartCokKatman(k) {
  const canvas = document.getElementById('f2-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  let W = canvas.clientWidth, H = 200;
  if (W < 50) W = (canvas.parentElement ? canvas.parentElement.clientWidth : 0) || 320;  // sekme gizliyken fallback
  canvas.width = W * dpr; canvas.height = H * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0,0,W,H);
  const n = k.etiketler.length;
  if (n === 0) return;

  const padL = 6, padR = 6, padT = 14, padB = 22;
  const cw = W - padL - padR, ch = H - padT - padB;
  const gap = cw / n;

  // Olcekler (her seri kendi maksimumuna gore normalize - karismasin)
  const maxHash = Math.max(...k.hashrate, 0.001) * 1.15;
  const maxUret = Math.max(...k.uretim, 0.0000001) * 1.25;
  const maxTuk  = Math.max(...k.tuketim, 0.001) * 1.25;
  const maxFiyat= Math.max(...k.fiyat, 1) * 1.1;
  const minFiyat= Math.min(...k.fiyat.filter(v=>v>0), maxFiyat);

  // 1) HASHRATE - sutun (acik mavi, arka plan)
  const barW = Math.min(gap * 0.55, 32);
  k.hashrate.forEach((v, i) => {
    const x = padL + gap * i + (gap - barW)/2;
    const h = (v / maxHash) * ch;
    const y = padT + ch - h;
    const grad = ctx.createLinearGradient(0, y, 0, padT+ch);
    grad.addColorStop(0, 'rgba(14,154,181,0.55)');
    grad.addColorStop(1, 'rgba(14,154,181,0.10)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, barW, h, [3,3,0,0]);
    else ctx.rect(x, y, barW, h);
    ctx.fill();
  });

  // Cizgi cizici yardimci
  function cizgi(dizi, maxV, renk, kalin, minV) {
    const lo = minV !== undefined ? minV : 0;
    const aralik = (maxV - lo) || 1;
    ctx.beginPath();
    dizi.forEach((v, i) => {
      const x = padL + gap * i + gap/2;
      const y = padT + ch - ((v - lo) / aralik) * ch;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = renk;
    ctx.lineWidth = kalin;
    ctx.stroke();
    // Noktalar
    dizi.forEach((v, i) => {
      const x = padL + gap * i + gap/2;
      const y = padT + ch - ((v - lo) / aralik) * ch;
      ctx.beginPath();
      ctx.arc(x, y, kalin === 2.5 ? 2.5 : 2, 0, Math.PI*2);
      ctx.fillStyle = renk;
      ctx.fill();
    });
  }

  // 2) ELEKTRIK TUKETIMI - kirmizi cizgi
  cizgi(k.tuketim, maxTuk, OTO_G.cekisK, 2);
  // 3) BTC URETIMI - turuncu cizgi
  cizgi(k.uretim, maxUret, OTO_G.gunesK, 2.5);
  // 4) BTC FIYATI - mor cizgi (dar aralikta, min-max ile gorunur)
  cizgi(k.fiyat, maxFiyat, '#7c3aed', 1.5, minFiyat * 0.98);

  // Etiketler (alt - tarih)
  ctx.fillStyle = '#94a3b8';
  ctx.font = '8px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  k.etiketler.forEach((et, i) => {
    if (n <= 14 || i % Math.ceil(n/14) === 0) {
      ctx.fillText(et, padL + gap*i + gap/2, H - 7);
    }
  });
}


function cihazRender(workers) {
  if (!workers || workers.length === 0) {
    document.getElementById('cihaz-grid').innerHTML = '<div class="empty-state" style="grid-column:1/-1">Cihaz yok</div>';
    return;
  }
  let calisan = 0, uyuyan = 0, kapali = 0, toplam = 0;
  workers.forEach(w => {
    if (w.durum === 'calisiyor') calisan++;
    else if (w.durum === 'uyuyor' || w.durum === 'yavasliyor') uyuyan++;
    else kapali++;
    toplam += w.anlik;
  });
  document.getElementById('cihaz-aktif').textContent = calisan;
  document.getElementById('cihaz-uyku').textContent = uyuyan;
  document.getElementById('cihaz-kapali').textContent = kapali;
  document.getElementById('cihaz-toplam').textContent = Math.round(toplam);
  // F2Pool sekmesindeki calisan cihaz kartini da guncelle
  window.f2CalisanCihaz = calisan;
  const f2c = document.getElementById('f2-ist-cihaz');
  if (f2c) f2c.textContent = calisan + ' / ' + workers.length;
  const f2cs = document.getElementById('f2-ist-fiyat-sub');
  if (f2cs) f2cs.textContent = 'aktif / toplam';
  let html = '';
  workers.sort((a,b) => a.name.localeCompare(b.name)).forEach(w => {
    const d = durumBilgisi(w.durum);
    const nameEsc = w.name.replace(/'/g, "\\'");
    html += '<div class="cihaz-card ' + w.durum + '" onclick="cihazDetay(&quot;' + w.name + '&quot;)">'
      + '<div class="cihaz-row1"><div class="cihaz-no">' + w.name + '</div><div class="cihaz-badge ' + d.cls + '">' + d.label + '</div></div>'
      + '<div class="cihaz-hash">' + Math.round(w.anlik) + ' <span style="font-size:11px;color:#64748b">TH/s anlık</span></div>'
      + '<div class="cihaz-sub">24h ort: ' + Math.round(w.h24) + ' TH/s</div>'
      + '</div>';
  });
  document.getElementById('cihaz-grid').innerHTML = html;
}

function cihazDetay(name) {
  document.getElementById('m-title').textContent = 'Cihaz ' + name;
  document.getElementById('m-sub').textContent = 'mehmetas.' + name;
  ['m-anlik','m-h1','m-h24','m-durum','m-son','m-btc','m-tl','m-usd','m-bugun-saat','m-24h-saat'].forEach(id => {
    document.getElementById(id).textContent = '—';
  });
  document.getElementById('modal').classList.add('active');
  chartData = null;
  fetch('/api/cihaz/' + name).then(r => r.json()).then(d => {
    if (d.anlik !== undefined) {
      document.getElementById('m-anlik').textContent = Math.round(d.anlik);
      document.getElementById('m-h1').textContent = Math.round(d.h1);
      document.getElementById('m-h24').textContent = Math.round(d.h24);
      const dr = durumBilgisi(d.durum);
      document.getElementById('m-durum').textContent = dr.ico + ' ' + dr.label;
      document.getElementById('m-durum').style.color = dr.renk;
      document.getElementById('m-son').textContent = d.last_share;
      document.getElementById('m-btc').textContent = (d.gunluk_btc || 0).toFixed(6);
      document.getElementById('m-tl').textContent = Math.round(d.gunluk_tl || 0).toLocaleString('tr-TR') + ' TL';
      document.getElementById('m-usd').textContent = Math.round(d.gunluk_usd || 0).toLocaleString('tr-TR');
      document.getElementById('m-bugun-saat').textContent = (d.bugun_saat || 0).toFixed(1);
      document.getElementById('m-24h-saat').textContent = (d.h24_saat || 0).toFixed(1);
      if (d.history) {
        chartData = d.history;
        cizGrafikLine('chart', d.history, OTO_G.ptf);
      }
    }
  });
}

function kapatModal() { document.getElementById('modal').classList.remove('active'); }

function cizGrafikLine(canvasId, data, renk) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext('2d');
  const W = canvas.width = canvas.offsetWidth * 2;
  const H = canvas.height = canvas.offsetHeight * 2;
  ctx.scale(2, 2);
  const w = W / 2;
  const h = H / 2;
  ctx.clearRect(0, 0, w, h);
  
  const isArray = Array.isArray(data);
  const entries = isArray ? data : Object.entries(data);
  if (entries.length === 0) return;
  const values = isArray ? data.map(e => e.value) : entries.map(e => e[1]/1e12);
  const max = Math.max(...values, 1);
  const ana = renk || OTO_G.gunes;          // varsayilan: solar amber
  
  // Kesikli yatay izgara (kontrol odasi stili)
  ctx.strokeStyle = OTO_G.gridK;
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 6]);
  for (let i = 0; i <= 4; i++) {
    const y = h * i / 4;
    ctx.beginPath(); ctx.moveTo(45, y); ctx.lineTo(w, y); ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.fillStyle = '#5d6c7b';
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const v = max - (max * i / 4);
    ctx.fillText(Math.round(v).toLocaleString('tr-TR'), 41, h * i / 4 + 4);
  }
  
  // Alan dolgusu
  const gradient = ctx.createLinearGradient(0, 0, 0, h);
  gradient.addColorStop(0, ana + '55');
  gradient.addColorStop(1, ana + '00');
  
  function yol() {
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = 45 + (w - 45) * i / (values.length - 1);
      const y = h - (v / max) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
  }
  yol();
  ctx.lineTo(w, h); ctx.lineTo(45, h); ctx.closePath();
  ctx.fillStyle = gradient; ctx.fill();
  
  // Parilti + ana cizgi
  yol();
  ctx.shadowColor = ana; ctx.shadowBlur = 8;
  ctx.strokeStyle = ana; ctx.lineWidth = 2; ctx.stroke();
  ctx.shadowBlur = 0;
  
  // Son nokta vurgusu
  const sx = w, sv = values[values.length - 1];
  const sy = h - (sv / max) * h;
  ctx.beginPath(); ctx.arc(sx - 1, sy, 3.5, 0, Math.PI * 2);
  ctx.fillStyle = ana; ctx.fill();
  ctx.beginPath(); ctx.arc(sx - 1, sy, 6, 0, Math.PI * 2);
  ctx.strokeStyle = ana + '66'; ctx.lineWidth = 1.5; ctx.stroke();
}

document.getElementById('chart').addEventListener('mousemove', (e) => tooltipDevice(e));
document.getElementById('chart').addEventListener('touchmove', (e) => { e.preventDefault(); tooltipDevice(e.touches[0]); });
document.getElementById('chart').addEventListener('mouseleave', () => { document.getElementById('tooltip').style.display = 'none'; });

function tooltipDevice(e) {
  if (!chartData) return;
  const canvas = document.getElementById('chart');
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const w = canvas.offsetWidth;
  const entries = Object.entries(chartData);
  if (entries.length === 0) return;
  const i = Math.round((x - 22) / (w - 22) * (entries.length - 1));
  if (i < 0 || i >= entries.length) return;
  const dt = new Date(entries[i][0]);
  document.getElementById('tt-time').textContent = String(dt.getHours()).padStart(2,'0') + ':' + String(dt.getMinutes()).padStart(2,'0');
  document.getElementById('tt-val').textContent = Math.round(entries[i][1]/1e12) + ' TH/s';
  const tt = document.getElementById('tooltip');
  tt.style.display = 'block';
  tt.style.left = (e.clientX - rect.left + 10) + 'px';
  tt.style.top = (e.clientY - rect.top - 40) + 'px';
}

// OSOS
let ososChartData = null;

function ososYukle() {
  if (ososData) { ososRender(); return; }
  document.getElementById('osos-info-title').textContent = 'Yükleniyor...';
  fetch('/api/osos').then(r => r.json()).then(d => {
    ososData = d;
    ososRender();
  });
}

function ososAbone(key, btn) {
  document.querySelectorAll('.osos-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  secilenAbone = key;
  ososRender();
}

function ososSec(sec, btn) {
  document.querySelectorAll('.osos-sec-tab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.osos-sec-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('osos-sec-' + sec).classList.add('active');
}

function ososRender() {
  if (!ososData || !ososData[secilenAbone]) return;
  const a = ososData[secilenAbone];
  
  const tipIco = a.tip === 'ges' ? '☀️' : (a.tip === 'tuketim' ? '🏭' : '⚡');
  const tipText = a.tip === 'ges' ? 'GES (Sadece Üretim)' : (a.tip === 'tuketim' ? 'Tüketim Tesisi' : 'GES + Tüketim');
  document.getElementById('osos-info').className = 'osos-info ' + a.tip;
  document.getElementById('osos-info-ico').textContent = tipIco;
  document.getElementById('osos-info-title').textContent = a.ad;
  document.getElementById('osos-info-sub').textContent = tipText + ' · Çarpan: ' + a.carpan;
  
  let toplamCekis = 0, toplamVeris = 0;
  const gunler = Object.keys(a.veri).sort();
  gunler.forEach(g => {
    Object.values(a.veri[g]).forEach(s => {
      toplamCekis += s.cekis || 0;
      toplamVeris += s.veris || 0;
    });
  });
  document.getElementById('osos-cekis').textContent = Math.round(toplamCekis).toLocaleString('tr-TR');
  document.getElementById('osos-veris').textContent = Math.round(toplamVeris).toLocaleString('tr-TR');
  const net = toplamCekis - toplamVeris;
  document.getElementById('osos-net').textContent = Math.round(net).toLocaleString('tr-TR');
  document.getElementById('osos-net').style.color = net > 0 ? '#f87171' : '#4ade80';
  
  // Son 30 gün grafiği
  const son30 = gunler.slice(-30);
  const grafikData = son30.map(g => {
    let c = 0, v = 0;
    Object.values(a.veri[g]).forEach(s => { c += s.cekis || 0; v += s.veris || 0; });
    const value = a.tip === 'ges' ? v : (a.tip === 'tuketim' ? c : Math.abs(v - c));
    const tarih = new Date(g);
    return { label: tarih.getDate() + '.' + (tarih.getMonth()+1).toString().padStart(2,'0'), value: value, tarih: g };
  });
  ososChartData = grafikData;
  cizGrafikLine('osos-chart', grafikData, OTO_G.yesil);
  
  // Gün listesi (son 14 gün)
  const son14 = gunler.slice(-14).reverse();
  let dayHtml = '';
  son14.forEach(g => {
    const tarih = new Date(g);
    const lbl = tarih.getDate() + '.' + (tarih.getMonth()+1).toString().padStart(2,'0');
    dayHtml += '<button class="osos-day-btn" onclick="ososGunSec(\"' + g + '\", this)">' + lbl + '</button>';
  });
  document.getElementById('osos-day-list').innerHTML = dayHtml;
  
  if (son14.length > 0) {
    const ilkBtn = document.querySelector('.osos-day-btn');
    if (ilkBtn) ososGunSec(son14[0], ilkBtn);
  }
  
  // Aylık liste
  ososAylikRender(a);
  
  // Yıllık liste
  ososYillikRender(a);
}

function ososAylikRender(abone) {
  if (!abone.aylar) {
    document.getElementById('aylik-liste').innerHTML = '<div class="empty-state">Veri yok</div>';
    return;
  }
  const aylar = abone.aylar;
  const sorted = Object.keys(aylar).sort().reverse();
  let html = '';
  sorted.forEach(ay => {
    const a = aylar[ay];
    const net = a.cekis - a.veris;
    let tikIco = '⏳', tikCls = 'bekliyor';
    if (a.dogrulama === 'ok') { tikIco = '✅'; tikCls = 'ok'; }
    else if (a.dogrulama === 'hata') { tikIco = '❌'; tikCls = 'hata'; }
    html += '<div class="ay-card">'
      + '<div class="ay-name">' + ay + '<br><span style="font-size:9px;color:#64748b;font-weight:600">' + a.gun_sayisi + ' gün</span></div>'
      + '<div class="ay-cekis">↓ ' + Math.round(a.cekis).toLocaleString('tr-TR') + '</div>'
      + '<div class="ay-veris">↑ ' + Math.round(a.veris).toLocaleString('tr-TR') + '</div>'
      + '<div class="ay-net" style="color:' + (net > 0 ? '#f87171' : '#4ade80') + '">' + Math.round(net).toLocaleString('tr-TR') + '</div>'
      + '<div class="ay-tik ' + tikCls + '" title="' + (a.dogrulama === 'hata' ? 'Endeks: ' + Math.round(a.endeks_cekis||0) + ' / ' + Math.round(a.endeks_veris||0) : '') + '">' + tikIco + '</div>'
      + '</div>';
  });
  document.getElementById('aylik-liste').innerHTML = html;
}

function ososYillikRender(abone) {
  if (!abone.aylar) {
    document.getElementById('yillik-liste').innerHTML = '<div class="empty-state">Veri yok</div>';
    return;
  }
  const yillar = {};
  Object.entries(abone.aylar).forEach(([ay, v]) => {
    const yil = ay.substring(0, 4);
    if (!yillar[yil]) yillar[yil] = {cekis: 0, veris: 0, gun: 0};
    yillar[yil].cekis += v.cekis;
    yillar[yil].veris += v.veris;
    yillar[yil].gun += v.gun_sayisi;
  });
  let html = '';
  Object.keys(yillar).sort().reverse().forEach(yil => {
    const y = yillar[yil];
    const net = y.cekis - y.veris;
    html += '<div class="yillik-card">'
      + '<div class="yillik-title">📅 ' + yil + ' Yılı (' + y.gun + ' gün)</div>'
      + '<div class="yillik-grid">'
      + '<div class="yillik-stat"><div class="yillik-lbl">Çekiş</div><div class="yillik-val" style="color:#f87171">' + Math.round(y.cekis).toLocaleString('tr-TR') + '</div></div>'
      + '<div class="yillik-stat"><div class="yillik-lbl">Veriş</div><div class="yillik-val" style="color:#4ade80">' + Math.round(y.veris).toLocaleString('tr-TR') + '</div></div>'
      + '<div class="yillik-stat"><div class="yillik-lbl">Net (kWh)</div><div class="yillik-val" style="color:' + (net > 0 ? '#f87171' : '#4ade80') + '">' + Math.round(net).toLocaleString('tr-TR') + '</div></div>'
      + '</div></div>';
  });
  document.getElementById('yillik-liste').innerHTML = html;
}

function ososGunSec(tarih, btn) {
  document.querySelectorAll('.osos-day-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const a = ososData[secilenAbone];
  const gun = a.veri[tarih] || {};
  let tbody = '';
  let tC = 0, tV = 0;
  for (let s = 0; s < 24; s++) {
    const ss = String(s).padStart(2,'0');
    const d = gun[ss] || {cekis:0, veris:0};
    const net = d.cekis - d.veris;
    tC += d.cekis; tV += d.veris;
    tbody += '<tr><td class="saat-cell">' + ss + '</td>'
      + '<td class="l4">' + (d.cekis ? Math.round(d.cekis).toLocaleString('tr-TR') : '—') + '</td>'
      + '<td class="l0">' + (d.veris ? Math.round(d.veris).toLocaleString('tr-TR') : '—') + '</td>'
      + '<td class="saat-cell" style="color:' + (net > 0 ? '#f87171' : '#4ade80') + '">' + Math.round(net).toLocaleString('tr-TR') + '</td></tr>';
  }
  tbody += '<tr style="border-top:2px solid rgba(34,197,94,0.4)"><td class="saat-cell" style="background:linear-gradient(180deg,#16a34a,#15803d);color:white">TOP</td>'
    + '<td class="l4" style="font-weight:900">' + Math.round(tC).toLocaleString('tr-TR') + '</td>'
    + '<td class="l0" style="font-weight:900">' + Math.round(tV).toLocaleString('tr-TR') + '</td>'
    + '<td class="saat-cell" style="font-weight:900;color:' + ((tC-tV) > 0 ? '#f87171' : '#4ade80') + '">' + Math.round(tC-tV).toLocaleString('tr-TR') + '</td></tr>';
  document.getElementById('osos-saatlik-body').innerHTML = tbody;
}

function versiyonPopupAc(e) {
  e.stopPropagation();
  var p = document.getElementById('versiyon-popup');
  if (!p) return;
  p.style.display = (p.style.display === 'none' || !p.style.display) ? 'block' : 'none';
}

// F2Pool alt sekme gecisi
function f2AltSekme(ad, btn) {
  document.querySelectorAll('.f2-alt-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.f2-alt-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('f2-alt-' + ad).classList.add('active');
  if (ad === 'kazanc') { try { if (window.f2GunlukHam && window.f2GunlukHam.length) f2Render(); } catch(e){} }
  if (ad === 'cihazlar') { try { if (window.f2Workers) f2CihazRender(window.f2Workers); } catch(e){} }
  if (ad === 'kiyas') { try { f2KiyasRender(); } catch(e){ console.error('kiyas:', e); } }
}

// F2Pool Cihazlar alt sekmesi (backend duz format: name, anlik, h24, durum)
function f2CihazRender(workers) {
  const g = document.getElementById('f2c-grid');
  if (!workers || workers.length === 0) {
    if (g) g.innerHTML = '<div class="empty-state" style="grid-column:1/-1">Cihaz yok</div>';
    return;
  }
  let calisan=0, uyuyan=0, kapali=0, toplam=0;
  workers.forEach(w => {
    if (w.durum === 'calisiyor') calisan++;
    else if (w.durum === 'uyuyor' || w.durum === 'yavasliyor') uyuyan++;
    else kapali++;
    toplam += (w.anlik || 0);
  });
  const set = (id,v) => { const e=document.getElementById(id); if(e) e.textContent=v; };
  set('f2c-aktif', calisan); set('f2c-uyku', uyuyan); set('f2c-kapali', kapali); set('f2c-toplam', Math.round(toplam));
  let html = '';
  workers.slice().sort((a,b) => a.name.localeCompare(b.name)).forEach(w => {
    const d = durumBilgisi(w.durum);
    html += '<div class="cihaz-card ' + w.durum + '" onclick="cihazDetay(&quot;' + w.name + '&quot;)">'
      + '<div class="cihaz-row1"><div class="cihaz-no">' + w.name + '</div><div class="cihaz-badge ' + d.cls + '">' + d.label + '</div></div>'
      + '<div class="cihaz-hash">' + Math.round(w.anlik || 0) + ' <span style="font-size:11px;color:#64748b">TH/s anlık</span></div>'
      + '<div class="cihaz-sub">24h ort: ' + Math.round(w.h24 || 0) + ' TH/s</div>'
      + '</div>';
  });
  if (g) g.innerHTML = html;
}

// ===== KIYAS: Madencilik karliligi =====
window.f2KiyasZamanTip = 'gun';
function f2KiyasZaman(tip, btn) {
  window.f2KiyasZamanTip = tip;
  document.querySelectorAll('.f2-kiyas-zaman').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  f2KiyasRender();
}

function f2KiyasRender() {
  const tarihEl = document.getElementById('f2-kiyas-tarih');
  if (!tarihEl) return;
  if (!tarihEl.value) {
    const bugun = new Date();
    tarihEl.value = bugun.toISOString().slice(0,10);
  }
  const gun = tarihEl.value;
  const mod = window.f2KiyasZamanTip || 'gun';

  if (mod === 'ay') {
    f2KiyasAylikRender(gun);
    return;
  }

  // Saatlik F2Pool verisi cek (hashrate -> tuketim) + PTF
  fetch('/api/f2pool_saatlik?gun=' + gun)
    .then(r => r.json())
    .then(d => {
      f2KiyasHesapla(d, gun);
    })
    .catch(e => {
      document.getElementById('f2-kiyas-liste').innerHTML = '<div class="empty-state">Veri alınamadı</div>';
    });
}

// Aylik mod: secilen tarihin ayini al, her gunu cek, toplam goster
function f2KiyasAylikRender(tarih) {
  const ay = tarih.slice(0, 7);  // "2026-06"
  const yil = parseInt(ay.slice(0, 4));
  const ayNo = parseInt(ay.slice(5, 7));
  const ayGunSay = new Date(yil, ayNo, 0).getDate();  // ayin gun sayisi
  const bugun = new Date().toISOString().slice(0, 10);

  // Yuklenme mesaji
  const liste = document.getElementById('f2-kiyas-liste');
  const ozet = document.getElementById('f2-kiyas-ozet');
  const harita = document.getElementById('f2-harita-grid');
  if (harita) harita.innerHTML = '';
  if (liste) liste.innerHTML = '<div class="empty-state">⏳ ' + ay + ' ayı yükleniyor (' + ayGunSay + ' gün)...</div>';
  if (ozet) ozet.innerHTML = '';

  // Her gun icin /api/f2pool_saatlik cek
  const promises = [];
  const gunler = [];
  for (let g = 1; g <= ayGunSay; g++) {
    const gunStr = ay + '-' + String(g).padStart(2, '0');
    if (gunStr > bugun) break;  // gelecek gunler atla
    gunler.push(gunStr);
    promises.push(fetch('/api/f2pool_saatlik?gun=' + gunStr).then(r => r.json()).catch(() => null));
  }

  Promise.all(promises).then(sonuclar => {
    const MHS_FIYAT = 2.909687;
    let ortJth = 25.0;
    if (window.antData && window.antData.devices) {
      let tW=0, tH=0;
      window.antData.devices.forEach(x => { const hr=x.hashrate_TH||0; if(hr>0){tW+=hr*antVerimlilik(x.model); tH+=hr;} });
      if (tH>0) ortJth = tW/tH;
    }
    const ptfAy = (window.fatAylikPtf && window.fatAylikPtf[ay]) || {};
    const btcKur = window.f2BtcKur || 0;

    let topGelir = 0, topGiderPtf = 0, topGiderMhs = 0, topTuketim = 0, topBtc = 0;
    let veriliGun = 0;
    const gunDetay = [];

    sonuclar.forEach((d, idx) => {
      const gunStr = gunler[idx];
      const gunNo = String(parseInt(gunStr.slice(8, 10)));
      const ptfGun = ptfAy[gunNo] || ptfAy[gunStr] || [];

      if (!d || !d.saatler) {
        gunDetay.push({gun: gunStr, gelir:0, giderPtf:0, giderMhs:0, tuketim:0, btc:0, netPtf:0, netMhs:0, veri:false});
        return;
      }
      let gunGelir = 0, gunGiderPtf = 0, gunGiderMhs = 0, gunTuketim = 0, gunBtcT = 0;
      let dolu = false;
      for (let h = 0; h < 24; h++) {
        const sk = String(h).padStart(2, '0');
        const s = d.saatler.find(x => x.saat === sk);
        if (!s || s.hash <= 0) continue;
        dolu = true;
        const tuketim = (s.hash * ortJth) / 1000;
        const gelir = (s.btc || 0) * btcKur;
        const ptf = (ptfGun[h] !== undefined ? ptfGun[h] : 0) / 1000;
        gunTuketim += tuketim;
        gunGelir += gelir;
        gunGiderPtf += tuketim * ptf;
        gunGiderMhs += tuketim * MHS_FIYAT;
        gunBtcT += (s.btc || 0);
      }
      if (dolu) veriliGun++;
      topGelir += gunGelir; topGiderPtf += gunGiderPtf; topGiderMhs += gunGiderMhs;
      topTuketim += gunTuketim; topBtc += gunBtcT;
      gunDetay.push({
        gun: gunStr,
        gelir: gunGelir, giderPtf: gunGiderPtf, giderMhs: gunGiderMhs,
        tuketim: gunTuketim, btc: gunBtcT,
        netPtf: gunGelir - gunGiderPtf, netMhs: gunGelir - gunGiderMhs,
        veri: dolu,
      });
    });

    const netPtfTop = topGelir - topGiderPtf;
    const netMhsTop = topGelir - topGiderMhs;

    // Ozet kartlari
    const aylar = ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'];
    const ayAdi = aylar[ayNo - 1] + ' ' + yil;
    let o = '';
    o += '<div class="f2-kiyas-kart"><div class="f2-kiyas-kart-lbl">📅 ' + ayAdi + '</div><div class="f2-kiyas-kart-val" style="color:#0f172a;font-size:18px;">' + veriliGun + '/' + gunler.length + '</div><div class="f2-kiyas-kart-sub">veri olan gün</div></div>';
    o += '<div class="f2-kiyas-kart"><div class="f2-kiyas-kart-lbl">💰 BTC Geliri</div><div class="f2-kiyas-kart-val" style="color:#d97706;">' + Math.round(topGelir).toLocaleString('tr-TR') + ' ₺</div><div class="f2-kiyas-kart-sub">' + topBtc.toFixed(5) + ' BTC</div></div>';
    o += '<div class="f2-kiyas-kart"><div class="f2-kiyas-kart-lbl">⚡ Tüketim</div><div class="f2-kiyas-kart-val" style="color:#2563eb;">' + Math.round(topTuketim).toLocaleString('tr-TR') + '</div><div class="f2-kiyas-kart-sub">kWh (tahmini)</div></div>';
    o += '<div class="f2-kiyas-kart"><div class="f2-kiyas-kart-lbl">📈 Net (PTF)</div><div class="f2-kiyas-kart-val" style="color:' + (netPtfTop>=0?'#16a34a':'#dc2626') + ';">' + Math.round(netPtfTop).toLocaleString('tr-TR') + ' ₺</div><div class="f2-kiyas-kart-sub">gelir − PTF gideri</div></div>';
    o += '<div class="f2-kiyas-kart"><div class="f2-kiyas-kart-lbl">🔄 Net (Mahsup)</div><div class="f2-kiyas-kart-val" style="color:' + (netMhsTop>=0?'#16a34a':'#dc2626') + ';">' + Math.round(netMhsTop).toLocaleString('tr-TR') + ' ₺</div><div class="f2-kiyas-kart-sub">gelir − 2,90×tüketim</div></div>';
    if (ozet) ozet.innerHTML = o;

    // Gun bazli liste
    let l = '';
    gunDetay.forEach(g => {
      if (!g.veri) {
        l += '<div class="f2-kiyas-row" style="opacity:0.5;">';
        l += '<span class="f2-kiyas-saat">' + g.gun.slice(8,10) + '.' + g.gun.slice(5,7) + '</span>';
        l += '<span style="color:#94a3b8;font-size:11px;">veri yok</span>';
        l += '<span></span><span></span>';
        l += '</div>';
        return;
      }
      const netRenk = g.netPtf >= 0 ? '#16a34a' : '#dc2626';
      l += '<div class="f2-kiyas-row">';
      l += '<span class="f2-kiyas-saat">' + g.gun.slice(8,10) + '.' + g.gun.slice(5,7) + '</span>';
      l += '<span style="color:#d97706;">' + Math.round(g.gelir).toLocaleString('tr-TR') + '₺</span>';
      l += '<span style="color:#2563eb;font-size:10px;">' + Math.round(g.tuketim).toLocaleString('tr-TR') + ' kWh</span>';
      l += '<span class="f2-kiyas-net" style="color:' + netRenk + ';">' + Math.round(g.netPtf).toLocaleString('tr-TR') + '₺</span>';
      l += '</div>';
    });
    if (liste) liste.innerHTML = l || '<div class="empty-state">Bu ayda veri yok</div>';
  });
}

function f2KiyasHesapla(d, gun) {
  const MHS_FIYAT = 2.909687;  // mahsup fiyati TL/kWh
  const btcKur = window.f2BtcKur || (d.btc_kur || 0);
  // Ortalama verimlilik (J/TH)
  let ortJth = 25.0;
  if (window.antData && window.antData.devices) {
    let tW=0, tH=0;
    window.antData.devices.forEach(x => { const hr=x.hashrate_TH||0; if(hr>0){tW+=hr*antVerimlilik(x.model); tH+=hr;} });
    if (tH>0) ortJth = tW/tH;
  }
  // PTF verisi (aylik_ptf.json) - o gunun saatlik
  const ay = gun.slice(0,7);
  const gunNo = String(parseInt(gun.slice(8,10)));
  const ptfAy = (window.fatAylikPtf && window.fatAylikPtf[ay]) || {};
  const ptfGun = ptfAy[gunNo] || ptfAy[gun] || [];

  // Backend'den gelen tum saatler (hash=0 olanlar = cihaz durmus, onlari da goster)
  const saatler = (d.saatler || []);
  const dolukSaat = saatler.filter(s => s.hash > 0);
  if (saatler.length === 0 || dolukSaat.length === 0) {
    document.getElementById('f2-harita-grid').innerHTML = '';
    document.getElementById('f2-kiyas-liste').innerHTML = '<div class="empty-state">📭 Bu gün için saatlik veri yok (F2Pool son ~48 saat)</div>';
    document.getElementById('f2-kiyas-ozet').innerHTML = '';
    return;
  }

  let topGelir=0, topGiderPtf=0, topGiderMhs=0, topTuketim=0, topBtc=0;
  const saatVeri = [];
  for (let h=0; h<24; h++) {
    const sk = String(h).padStart(2,'0');
    const s = saatler.find(x => x.saat === sk);
    if (!s) { saatVeri.push(null); continue; }  // backend'de hic yok = veri yok
    const tuketim = (s.hash * ortJth) / 1000;  // kWh (hash=0 ise tuketim=0)
    const gelir = (s.btc || 0) * btcKur;        // TL
    const ptf = (ptfGun[h] !== undefined ? ptfGun[h] : 0) / 1000;  // PTF TL/MWh -> TL/kWh
    const giderPtf = tuketim * ptf;
    const giderMhs = tuketim * MHS_FIYAT;  // mahsup fiyati ile
    const netPtf = gelir - giderPtf;
    const netMhs = gelir - giderMhs;
    const durdu = (s.hash <= 0);  // cihaz durmus mu
    topGelir += gelir; topGiderPtf += giderPtf; topGiderMhs += giderMhs;
    topTuketim += tuketim; topBtc += (s.btc||0);
    saatVeri.push({ saat:sk, tuketim, gelir, ptf:ptfGun[h]||0, giderPtf, giderMhs, netPtf, netMhs, hash:s.hash, btc:s.btc||0, durdu });
  }

  const netPtfTop = topGelir - topGiderPtf;
  const netMhsTop = topGelir - topGiderMhs;

  // Ozet kartlari
  let ozet = '';
  ozet += '<div class="f2-kiyas-kart"><div class="f2-kiyas-kart-lbl">💰 BTC Geliri</div><div class="f2-kiyas-kart-val" style="color:#d97706;">' + Math.round(topGelir).toLocaleString('tr-TR') + ' ₺</div><div class="f2-kiyas-kart-sub">' + topBtc.toFixed(6) + ' BTC</div></div>';
  ozet += '<div class="f2-kiyas-kart"><div class="f2-kiyas-kart-lbl">⚡ Tüketim</div><div class="f2-kiyas-kart-val" style="color:#2563eb;">' + Math.round(topTuketim).toLocaleString('tr-TR') + '</div><div class="f2-kiyas-kart-sub">kWh (tahmini)</div></div>';
  ozet += '<div class="f2-kiyas-kart"><div class="f2-kiyas-kart-lbl">📈 Net (PTF)</div><div class="f2-kiyas-kart-val" style="color:' + (netPtfTop>=0?'#16a34a':'#dc2626') + ';">' + Math.round(netPtfTop).toLocaleString('tr-TR') + ' ₺</div><div class="f2-kiyas-kart-sub">gelir − PTF gideri</div></div>';
  ozet += '<div class="f2-kiyas-kart"><div class="f2-kiyas-kart-lbl">🔄 Net (Mahsup)</div><div class="f2-kiyas-kart-val" style="color:' + (netMhsTop>=0?'#16a34a':'#dc2626') + ';">' + Math.round(netMhsTop).toLocaleString('tr-TR') + ' ₺</div><div class="f2-kiyas-kart-sub">gelir − 2,90×tüketim</div></div>';
  document.getElementById('f2-kiyas-ozet').innerHTML = ozet;

  // Verimlilik haritasi (24 saat, net PTF'ye gore renk)
  let harita = '';
  for (let h=0; h<24; h++) {
    const v = saatVeri[h];
    let renk = '#e2e8f0', baslik = h + ':00 veri yok';
    if (v) {
      if (v.durdu) { renk = '#cbd5e1'; baslik = h + ':00 → Cihaz durdu (hash 0)'; }
      else if (v.netPtf > 5) { renk = '#16a34a'; baslik = h + ':00 → Net: ' + Math.round(v.netPtf) + ' TL'; }
      else if (v.netPtf >= -5) { renk = '#fbbf24'; baslik = h + ':00 → Net: ' + Math.round(v.netPtf) + ' TL'; }
      else { renk = '#dc2626'; baslik = h + ':00 → Net: ' + Math.round(v.netPtf) + ' TL'; }
    }
    harita += '<div class="f2-harita-saat" style="background:' + renk + ';" title="' + baslik + '">' + h + '</div>';
  }
  document.getElementById('f2-harita-grid').innerHTML = harita;

  // Saatlik kiyas listesi (popuplı)
  let liste = '';
  saatVeri.forEach((v, h) => {
    if (!v) return;
    if (v.durdu) {
      // Cihaz durmus saat - sade goster
      liste += '<div class="f2-kiyas-row" style="opacity:0.6;">';
      liste += '<span class="f2-kiyas-saat">' + v.saat + ':00</span>';
      liste += '<span style="color:#94a3b8;font-size:11px;">⏸️ Cihaz durdu</span>';
      liste += '<span class="f2-kiyas-net" style="color:#94a3b8;">0₺</span>';
      liste += '</div>';
      return;
    }
    const netRenk = v.netPtf >= 0 ? '#16a34a' : '#dc2626';
    liste += '<div class="f2-kiyas-row">';
    liste += '<span class="f2-kiyas-saat">' + v.saat + ':00</span>';
    liste += '<span style="color:#d97706;">' + Math.round(v.gelir) + '₺</span>';
    liste += '<span style="color:#2563eb;font-size:10px;">' + v.tuketim.toFixed(1) + 'kWh</span>';
    liste += '<span class="f2-kiyas-net" style="color:' + netRenk + ';">' + Math.round(v.netPtf) + '₺</span>';
    // Popup
    liste += '<div class="fat-popup">';
    liste += '<div class="fat-popup-title">⚖️ Saat ' + v.saat + ':00 Kıyas</div>';
    liste += '<div class="fat-popup-row"><span>Hashrate</span><span>' + Math.round(v.hash) + ' TH/s</span></div>';
    liste += '<div class="fat-popup-row"><span>Tüketim (tahmini)</span><span>' + v.tuketim.toFixed(2) + ' kWh</span></div>';
    liste += '<div class="fat-popup-row"><span>BTC Üretim</span><span>' + v.btc.toFixed(6) + '</span></div>';
    liste += '<div class="fat-popup-row sum"><span>💰 BTC Geliri</span><span style="color:#d97706;">' + Math.round(v.gelir) + ' ₺</span></div>';
    liste += '<div class="fat-popup-row"><span>PTF (' + v.saat + ':00)</span><span>' + fatFmt(v.ptf, 2) + ' TL/MWh</span></div>';
    liste += '<div class="fat-popup-row"><span>− Gider (PTF)</span><span style="color:#dc2626;">' + Math.round(v.giderPtf) + ' ₺</span></div>';
    liste += '<div class="fat-popup-sonuc"><span>= Net (PTF)</span><span style="color:' + netRenk + ';">' + Math.round(v.netPtf) + ' ₺</span></div>';
    liste += '<div class="fat-popup-row"><span>− Gider (Mahsup 2,90)</span><span style="color:#dc2626;">' + Math.round(v.giderMhs) + ' ₺</span></div>';
    liste += '<div class="fat-popup-sonuc"><span>= Net (Mahsup)</span><span style="color:' + (v.netMhs>=0?'#16a34a':'#dc2626') + ';">' + Math.round(v.netMhs) + ' ₺</span></div>';
    liste += '</div>';
    liste += '</div>';
  });
  document.getElementById('f2-kiyas-liste').innerHTML = liste || '<div class="empty-state">Veri yok</div>';
}
document.addEventListener('click', function(e) {
  var d = document.getElementById('versiyon-damgasi');
  var p = document.getElementById('versiyon-popup');
  if (p && d && !d.contains(e.target)) p.style.display = 'none';
});

function yukle() {
  fetch('/api/ozet').then(r => r.json()).then(d => {
    try {
    if (d.sinyal) {
      const kart = document.getElementById('status-card');
      const ico = document.getElementById('status-icon');
      kart.className = 'status-card ' + (d.sinyal.veri_var ? (d.sinyal.karli ? '' : 'zarar') : 'gri');
      ico.textContent = d.sinyal.veri_var ? (d.sinyal.karli ? '✓' : '✕') : '⏳';
      document.getElementById('status-title').textContent = d.sinyal.veri_var ? (d.sinyal.karli ? 'ÇALIŞMA VAR' : 'ÇALIŞMA YOK') : 'Veri Bekleniyor';
      document.getElementById('status-sub').textContent = d.sinyal.mesaj || '';
    }
    } catch(e) { console.error('sinyal render:', e); }
    try {
    if (d.btc) {
      document.getElementById('btc-tl').textContent = d.btc.tl;
      document.getElementById('btc-usd').textContent = '$' + d.btc.usd + ' USD';
    }
    } catch(e) { console.error('btc render:', e); }
    try {
    if (d.f2pool) {
      document.getElementById('bugun-btc').textContent = d.f2pool.bugun_btc;
      document.getElementById('bugun-tl').textContent = '~' + d.f2pool.bugun_tl + ' TL';
      document.getElementById('dun-btc').textContent = d.f2pool.dun_btc;
      document.getElementById('dun-tl').textContent = '~' + d.f2pool.dun_tl + ' TL';
      document.getElementById('toplam-hash').innerHTML = d.f2pool.hash + ' <span style="font-size:14px;color:#64748b">TH/s</span>';
    }
    } catch(e) { console.error('f2pool render:', e); }
    try {
    if (d.aylik) {
      document.getElementById('ay-kar').textContent = '+' + d.aylik.kar;
      document.getElementById('ay-gun').textContent = 'TL | ' + d.aylik.gun + ' gün';
      document.getElementById('f2-title').textContent = d.aylik.ay + ' Toplam';
      document.getElementById('f2-subtitle').textContent = d.aylik.gun + ' gün üretim';
      document.getElementById('f2-big').innerHTML = d.aylik.btc + '<span> BTC</span>';
      document.getElementById('f2-small').textContent = '~' + d.aylik.tl + ' TL';
    }
    } catch(e) { console.error('aylik render:', e); }
    try { if (d.aylik_ptf) aylikRender(d.aylik_ptf); } catch(e) { console.error('aylikRender:', e); }
    try {
    if (d.gunluk_ham) {
      window.f2GunlukHam = d.gunluk_ham;
      window.f2BtcKur = d.btc_kur || 0;
      f2AySeceneksDoldur();
      f2Render();
    }
    } catch(e) { console.error('f2Render:', e); }
    try { if (d.gunluk_liste) { window.f2GunlukListe = d.gunluk_liste; } } catch(e) {}
    try { if (d.workers) { window.f2Workers = d.workers; cihazRender(d.workers); f2CihazRender(d.workers); } } catch(e) { console.error('cihazRender:', e); }
    try { document.getElementById('guncelleme').textContent = 'Güncellendi: ' + new Date().toLocaleTimeString('tr-TR'); } catch(e) {}
  }).catch(e => { console.error('yukle fetch:', e); });
}
yukle();
setInterval(yukle, 60000);

// ====================== İNVERTER (Huawei FusionSolar) ======================
let invData = null;
let invSecilenTesis = 'all';

function invYukle() {
  if (invData) { invRender(); return; }
  document.getElementById('inv-info-title').textContent = 'Yükleniyor...';
  fetch('/api/inverter').then(r => r.json()).then(d => {
    if (d.hata) {
      document.getElementById('inv-info-title').textContent = 'Veri yok';
      document.getElementById('inv-info-sub').textContent = d.hata;
      return;
    }
    invData = d;
    invRender();
  }).catch(e => {
    document.getElementById('inv-info-title').textContent = 'Bağlantı hatası';
  });
}

function invTesis(code, btn) {
  document.querySelectorAll('#t-inverter > .osos-tabs .osos-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  invSecilenTesis = code;
  invRender();
}

function invSec(sec, btn) {
  document.querySelectorAll('#t-inverter .osos-sec-tab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('#t-inverter .osos-sec-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('inv-sec-' + sec).classList.add('active');
  if (sec === 'aylik') setTimeout(invAylikRender, 50);
  if (sec === 'yillik') setTimeout(invYillikRender, 50);
  if (sec === 'saatlik') setTimeout(invSaatlikRender, 50);
}

function invRender() {
  if (!invData) return;
  const tesisler = invData.stations || [];
  let aktifTesisler = tesisler;
  let inverters = invData.inverters || [];

  if (invSecilenTesis !== 'all') {
    aktifTesisler = tesisler.filter(t => t.code === invSecilenTesis);
    inverters = inverters.filter(i => i.stationCode === invSecilenTesis);
  }

  // Toplam hesaplama
  let anlik = 0, bugun = 0, toplam = 0, kapasite = 0;
  aktifTesisler.forEach(t => {
    anlik += t.current_power_kW || 0;
    bugun += t.day_energy_kWh || 0;
    toplam += t.lifetime_kWh || 0;
    kapasite += (t.capacity_MW || 0) * 1000;
  });

  // Info kartı
  if (invSecilenTesis === 'all') {
    document.getElementById('inv-info-title').textContent = 'Tüm Tesisler';
    document.getElementById('inv-info-sub').textContent = 
      tesisler.length + ' tesis · ' + inverters.length + ' inverter · ' + (kapasite/1000).toFixed(2) + ' MW kurulu';
  } else {
    const t = aktifTesisler[0];
    document.getElementById('inv-info-title').textContent = t ? t.name : '—';
    document.getElementById('inv-info-sub').textContent = 
      (t ? t.inverter_count + ' inverter · ' + t.capacity_MW.toFixed(3) + ' MW · ' + (t.address || '') : '—');
  }

  const oran = kapasite > 0 ? (anlik / kapasite * 100) : 0;
  document.getElementById('inv-info-power').textContent = Math.round(anlik);

  document.getElementById('inv-anlik').textContent = Math.round(anlik).toLocaleString('tr-TR');
  document.getElementById('inv-bugun').textContent = Math.round(bugun).toLocaleString('tr-TR');
  document.getElementById('inv-toplam').textContent = (toplam / 1000).toFixed(1);

  // Alt sekmeler
  invSaatlikRender();
  invAylikRender();
  invYillikRender();
  invListeRender(inverters);
}

function invSaatlikRender() {
  if (!invData) return;
  const monthly = invData.monthly || {};
  
  // Birden fazla tesis toplam
  const gunler = {};
  Object.entries(monthly).forEach(([code, m]) => {
    if (invSecilenTesis !== 'all' && code !== invSecilenTesis) return;
    Object.entries(m.daily || {}).forEach(([gun, v]) => {
      gunler[gun] = (gunler[gun] || 0) + (v.production_kWh || 0);
    });
  });

  // Son 30 gün grafiği
  const son30 = Object.keys(gunler).sort().slice(-30);
  const chartData = son30.map(g => {
    const tarih = new Date(g);
    return { label: tarih.getDate() + '.' + (tarih.getMonth()+1).toString().padStart(2,'0'),
             value: gunler[g], tarih: g };
  });
  cizGrafikLine('inv-chart', chartData);

  // Gün listesi (son 14)
  const son14 = Object.keys(gunler).sort().slice(-14).reverse();
  let dayHtml = '';
  son14.forEach((g, i) => {
    const tarih = new Date(g);
    const lbl = tarih.getDate() + '.' + (tarih.getMonth()+1).toString().padStart(2,'0');
    dayHtml += '<button class="osos-day-btn' + (i === 0 ? ' active' : '') + '" onclick="invGunSec(\"' + g + '\", this)">' + lbl + '</button>';
  });
  document.getElementById('inv-day-list').innerHTML = dayHtml;

  if (son14.length > 0) {
    invGunSec(son14[0], document.querySelector('#inv-day-list .osos-day-btn'));
  }
}

function invGunSec(tarih, btn) {
  document.querySelectorAll('#inv-day-list .osos-day-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');

  const daily = invData.daily || {};
  // Tesisleri birleştir
  const saatler = {};
  Object.entries(daily).forEach(([code, d]) => {
    if (invSecilenTesis !== 'all' && code !== invSecilenTesis) return;
    if (d.date !== tarih) return;
    Object.entries(d.hourly || {}).forEach(([saat, v]) => {
      if (!saatler[saat]) saatler[saat] = { power_kW: 0, production_kWh: 0, radiation: 0, sayim: 0 };
      saatler[saat].power_kW += v.power_kW || 0;
      saatler[saat].production_kWh += v.production_kWh || 0;
      saatler[saat].radiation += v.radiation || 0;
      saatler[saat].sayim++;
    });
  });

  let tbody = '';
  let toplamUretim = 0;
  for (let s = 0; s < 24; s++) {
    const ss = String(s).padStart(2, '0');
    const d = saatler[ss] || { power_kW: 0, production_kWh: 0, radiation: 0, sayim: 0 };
    const rad = d.sayim ? (d.radiation / d.sayim) : 0;
    toplamUretim += d.production_kWh;
    const cls = d.production_kWh > 500 ? 'l3' : (d.production_kWh > 200 ? 'l2' : (d.production_kWh > 0 ? 'l1' : 'l0'));
    tbody += '<tr><td class="saat-cell">' + ss + ':00</td>'
      + '<td class="' + cls + '">' + (d.power_kW ? d.power_kW.toFixed(1) : '—') + '</td>'
      + '<td class="' + cls + '">' + (d.production_kWh ? d.production_kWh.toFixed(1) : '—') + '</td>'
      + '<td class="l2">' + (rad ? rad.toFixed(2) : '—') + '</td></tr>';
  }
  tbody += '<tr style="border-top:2px solid rgba(34,197,94,0.4)">'
    + '<td class="saat-cell" style="background:linear-gradient(180deg,#16a34a,#15803d);color:white">TOP</td>'
    + '<td>—</td>'
    + '<td class="l0" style="font-weight:900">' + Math.round(toplamUretim).toLocaleString('tr-TR') + '</td>'
    + '<td>—</td></tr>';
  document.getElementById('inv-saatlik-body').innerHTML = tbody;
}

function invAylikRender() {
  if (!invData) return;
  const monthly = invData.monthly || {};

  // Birleşik günlük üretim
  const gunler = {};
  Object.entries(monthly).forEach(([code, m]) => {
    if (invSecilenTesis !== 'all' && code !== invSecilenTesis) return;
    Object.entries(m.daily || {}).forEach(([gun, v]) => {
      gunler[gun] = (gunler[gun] || 0) + (v.production_kWh || 0);
    });
  });

  const sorted = Object.keys(gunler).sort();
  // Bu ay
  const buAy = new Date().toISOString().substring(0, 7);
  const buAyGunler = sorted.filter(g => g.startsWith(buAy));

  const chartData = buAyGunler.map(g => {
    const tarih = new Date(g);
    return { label: tarih.getDate().toString(), value: gunler[g], tarih: g };
  });
  cizGrafikLine('inv-aylik-chart', chartData);

  // Aylık özet
  const aylar = {};
  Object.keys(gunler).forEach(g => {
    const ay = g.substring(0, 7);
    if (!aylar[ay]) aylar[ay] = { uretim: 0, gun: 0 };
    aylar[ay].uretim += gunler[g];
    aylar[ay].gun++;
  });

  let html = '';
  Object.keys(aylar).sort().reverse().forEach(ay => {
    const a = aylar[ay];
    const ortalama = a.gun ? a.uretim / a.gun : 0;
    html += '<div class="ay-card">'
      + '<div class="ay-name">' + ay + '<br><span style="font-size:9px;color:#64748b;font-weight:600">' + a.gun + ' gün</span></div>'
      + '<div class="ay-veris">↑ ' + Math.round(a.uretim).toLocaleString('tr-TR') + '</div>'
      + '<div class="ay-net" style="color:#fbbf24">Ø ' + Math.round(ortalama).toLocaleString('tr-TR') + '</div>'
      + '<div class="ay-tik ok">☀️</div>'
      + '<div></div>'
      + '</div>';
  });
  document.getElementById('inv-aylik-liste').innerHTML = html || '<div class="empty-state">Veri yok</div>';
}

function invYillikRender() {
  if (!invData) return;
  const monthly = invData.monthly || {};

  // Aylık birikim
  const aylar = {};
  Object.entries(monthly).forEach(([code, m]) => {
    if (invSecilenTesis !== 'all' && code !== invSecilenTesis) return;
    Object.entries(m.daily || {}).forEach(([gun, v]) => {
      const ay = gun.substring(0, 7);
      aylar[ay] = (aylar[ay] || 0) + (v.production_kWh || 0);
    });
  });

  // Yıl bazlı toplam
  const yillar = {};
  Object.entries(aylar).forEach(([ay, uretim]) => {
    const yil = ay.substring(0, 4);
    if (!yillar[yil]) yillar[yil] = { uretim: 0, ay: 0, aylar: {} };
    yillar[yil].uretim += uretim;
    yillar[yil].ay++;
    yillar[yil].aylar[ay.substring(5)] = uretim;
  });

  // Grafik: bu yıl aylık
  const buYil = new Date().getFullYear().toString();
  const buYilAylar = Object.keys(aylar).filter(a => a.startsWith(buYil)).sort();
  const chartData = buYilAylar.map(a => {
    const ayAd = ['Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara'];
    const ayNo = parseInt(a.substring(5, 7)) - 1;
    return { label: ayAd[ayNo], value: aylar[a], tarih: a };
  });
  cizGrafikLine('inv-yillik-chart', chartData);

  let html = '';
  Object.keys(yillar).sort().reverse().forEach(yil => {
    const y = yillar[yil];
    html += '<div class="yillik-card">'
      + '<div class="yillik-title">📅 ' + yil + ' Yılı (' + y.ay + ' ay)</div>'
      + '<div class="yillik-grid">'
      + '<div class="yillik-stat"><div class="yillik-lbl">Toplam Üretim</div><div class="yillik-val" style="color:#fbbf24">' + Math.round(y.uretim).toLocaleString('tr-TR') + '</div><div class="yillik-lbl">kWh</div></div>'
      + '<div class="yillik-stat"><div class="yillik-lbl">Aylık Ort.</div><div class="yillik-val" style="color:#4ade80">' + Math.round(y.uretim / y.ay).toLocaleString('tr-TR') + '</div><div class="yillik-lbl">kWh/ay</div></div>'
      + '<div class="yillik-stat"><div class="yillik-lbl">MWh</div><div class="yillik-val" style="color:#60a5fa">' + (y.uretim / 1000).toFixed(1) + '</div><div class="yillik-lbl">toplam</div></div>'
      + '</div></div>';
  });
  document.getElementById('inv-yillik-liste').innerHTML = html || '<div class="empty-state">Veri yok</div>';
}

function invListeRender(inverters) {
  if (!inverters) inverters = invData.inverters || [];
  let calisan = 0, bekleme = 0, kapali = 0, toplam = 0;

  inverters.forEach(inv => {
    const power = inv.activePower_kW || 0;
    toplam += power;
    if (power > 0.5) calisan++;
    else if (inv.runState === 0) kapali++;
    else bekleme++;
  });

  document.getElementById('inv-sayisi-aktif').textContent = calisan;
  document.getElementById('inv-sayisi-bekleme').textContent = bekleme;
  document.getElementById('inv-sayisi-kapali').textContent = kapali;
  document.getElementById('inv-sayisi-toplam').textContent = Math.round(toplam);

  let html = '';
  const sorted = [...inverters].sort((a, b) => {
    if (a.stationName !== b.stationName) return a.stationName.localeCompare(b.stationName);
    return a.devName.localeCompare(b.devName);
  });

  sorted.forEach(inv => {
    const power = inv.activePower_kW || 0;
    const aktif = power > 0.5;
    let cls = '', badge = '', lbl = '';
    if (aktif) { cls = ''; badge = 'badge-on'; lbl = 'Çalışıyor'; }
    else if (inv.runState === 0) { cls = 'kapali'; badge = 'badge-off'; lbl = 'Kapalı'; }
    else { cls = 'uyuyor'; badge = 'badge-sleep'; lbl = 'Bekleme'; }

    const stationKisa = inv.stationName.replace(' GES', '');

    html += '<div class="cihaz-card ' + cls + '" onclick="invDetay(&quot;' + inv.devId + '&quot;)">'
      + '<div class="cihaz-row1">'
      + '<div class="cihaz-no" style="font-size:14px">' + inv.devName + '</div>'
      + '<div class="cihaz-badge ' + badge + '">' + lbl + '</div>'
      + '</div>'
      + '<div class="cihaz-hash" style="color:#fbbf24">' + power.toFixed(1) + ' <span style="font-size:11px;color:#64748b">kW</span></div>'
      + '<div class="cihaz-sub">Bugün: ' + Math.round(inv.dayEnergy_kWh || 0) + ' kWh · ' + stationKisa + '</div>'
      + '</div>';
  });
  document.getElementById('inv-grid').innerHTML = html || '<div class="empty-state" style="grid-column:1/-1">İnverter yok</div>';
}

function invDetay(devId) {
  if (!invData) return;
  const inv = (invData.inverters || []).find(i => String(i.devId) === String(devId));
  if (!inv) return;

  document.getElementById('im-title').textContent = inv.devName;
  document.getElementById('im-sub').textContent = inv.stationName;
  document.getElementById('im-anlik').textContent = (inv.activePower_kW || 0).toFixed(2);
  document.getElementById('im-bugun').textContent = Math.round(inv.dayEnergy_kWh || 0).toLocaleString('tr-TR');
  document.getElementById('im-toplam').textContent = ((inv.totalEnergy_kWh || 0) / 1000).toFixed(1);

  const power = inv.activePower_kW || 0;
  let dStr = '🟢 Çalışıyor';
  if (power < 0.5 && inv.runState === 0) dStr = '🔴 Kapalı';
  else if (power < 0.5) dStr = '🟡 Bekleme';
  document.getElementById('im-durum').textContent = dStr;
  document.getElementById('im-sicaklik').textContent = inv.temperature ? inv.temperature.toFixed(1) + ' °C' : '—';

  document.getElementById('im-verim').textContent = inv.efficiency ? (inv.efficiency * 100).toFixed(1) : '—';
  document.getElementById('im-temp').textContent = inv.temperature ? inv.temperature.toFixed(1) : '—';
  document.getElementById('im-freq').textContent = inv.gridFrequency ? inv.gridFrequency.toFixed(2) : '—';
  document.getElementById('im-aktif').textContent = inv.activeHours ? inv.activeHours.toFixed(1) : '—';

  document.getElementById('inv-modal').classList.add('active');
}

function kapatInvModal() { document.getElementById('inv-modal').classList.remove('active'); }

// ====================== İNVERTER SONU ======================

// ====================== ANTMINER SAHA ======================
let antData = null;

// Model bazli verimlilik (J/TH) - nominal degerler
// Guc(W) = Hashrate(TH/s) x J/TH. Tuketim(kWh) = Guc(W) x saat / 1000
const ANTMINER_VERIMLILIK = {
  'S19': 34.5, 'S19 Pro': 29.5, 'S19j': 34.5, 'S19j Pro': 30.5,
  'S19j Pro+': 27.5, 'S19 XP': 21.5, 'S19 XP Hyd': 20.8, 'S19 Pro+ Hyd': 21.0,
  'S19 Hydro': 28.0, 'S19k Pro': 23.0, 'T19': 37.5,
  'S21': 17.5, 'S21 Pro': 15.0, 'S21+': 16.5, 'S21 XP': 13.5, 'S21 Hyd': 16.0, 'S21e XP Hyd': 11.5,
  'T21': 19.0, 'S17': 45.0, 'T17': 55.0
};
// Model adindan J/TH bul (kismi eslesme - en uzun eslesen kazanir)
function antVerimlilik(model) {
  if (!model) return 25.0; // varsayilan (modern karma filo ortalamasi)
  const m = String(model).trim();
  // Tam eslesme
  if (ANTMINER_VERIMLILIK[m]) return ANTMINER_VERIMLILIK[m];
  // Kismi eslesme - model adi icinde gecen en uzun anahtar
  let best = null, bestLen = 0;
  Object.keys(ANTMINER_VERIMLILIK).forEach(k => {
    if (m.toUpperCase().indexOf(k.toUpperCase()) >= 0 && k.length > bestLen) {
      best = k; bestLen = k.length;
    }
  });
  return best ? ANTMINER_VERIMLILIK[best] : 25.0;
}
// Cihaz listesinden toplam anlik guc (kW) - hashrate x model verimliligi
function antToplamGucKW(devices) {
  let toplamW = 0;
  (devices || []).forEach(d => {
    const hr = d.hashrate_TH || 0;
    if (hr <= 0) return;
    const jth = antVerimlilik(d.model);
    toplamW += hr * jth;  // W = TH/s x J/TH
  });
  return toplamW / 1000;  // kW
}

function antYukle() {
  document.getElementById('ant-info-title').textContent = 'Yükleniyor...';
  fetch('/api/antminer').then(r => r.json()).then(d => {
    if (d.hata) {
      document.getElementById('ant-info-title').textContent = 'Veri yok';
      document.getElementById('ant-info-sub').textContent = d.hata;
      return;
    }
    antData = d;
    window.antData = d;
    antRender();
    cmmRender();  // Cihazlarim sekmesini de guncelle
  }).catch(e => {
    document.getElementById('ant-info-title').textContent = 'Bağlantı hatası';
  });
}

function antSec(sec, btn) {
  document.querySelectorAll('#t-antminer .osos-sec-tab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('#t-antminer .osos-sec-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('ant-sec-' + sec).classList.add('active');
}

function antRender() {
  if (!antData) return;
  const s = antData.summary || {};
  const devices = antData.devices || [];

  // Info kart
  let infoTitle = 'Tek Yıldız 2 GES - Saha';
  if (s.f2pool && s.f2pool.enabled) {
    const fmtch = s.f2pool.matched_devices || 0;
    const total = s.total || 0;
    const f2Color = fmtch === total ? '#22c55e' : (fmtch > total * 0.8 ? '#fbbf24' : '#ef4444');
    infoTitle += ` <span style="color:${f2Color}; font-size:12px; margin-left:8px;">⛏️ F2Pool: ${fmtch}/${total} eşleşti</span>`;
  }
  document.getElementById('ant-info-title').innerHTML = infoTitle;

  const modelList = Object.entries(s.models || {}).map(([m,c]) => `${m}×${c}`).join(' · ');
  const tsStr = antData.timestamp ? new Date(antData.timestamp).toLocaleTimeString('tr-TR') : '—';
  document.getElementById('ant-info-sub').textContent = `${modelList} · Son güncel: ${tsStr}`;

  // KPI'lar
  document.getElementById('ant-hash').textContent = Math.round(s.total_hashrate_TH || 0).toLocaleString('tr-TR');
  document.getElementById('ant-hash-sub').textContent = `TH/s (hedef: ${Math.round(s.total_target_TH || 0).toLocaleString('tr-TR')})`;

  const eff = s.efficiency_pct || 0;
  const effColor = eff >= 95 ? '#22c55e' : (eff >= 80 ? '#fbbf24' : '#ef4444');
  document.getElementById('ant-eff').textContent = eff;
  document.getElementById('ant-eff').style.color = effColor;

  document.getElementById('ant-online').textContent = s.online || 0;
  document.getElementById('ant-online-sub').textContent = `/ ${s.total || 0} cihaz`;

  document.getElementById('ant-temp').textContent = (s.avg_temp_C || 0).toFixed(1);
  if (s.avg_water_temp_C > 0) {
    document.getElementById('ant-temp-sub').textContent = `°C · 💧 Su: ${s.avg_water_temp_C}°`;
  } else {
    document.getElementById('ant-temp-sub').textContent = '°C';
  }

  // Kazanc kartlari
  if (s.earnings) {
    document.getElementById('ant-kazanc-grid').style.display = 'grid';
    const e = s.earnings;
    const fmtTRY = (v) => v ? v.toLocaleString('tr-TR', {maximumFractionDigits:0}) + ' ₺' : '— ₺';
    const fmtSub = (usd, btc) => (usd ? '$' + usd.toLocaleString('tr-TR', {maximumFractionDigits:0}) : '$—') + ' · ' + (btc ? btc.toFixed(6) + ' BTC' : '— BTC');

    document.getElementById('ant-earn-today-try').textContent = fmtTRY(e.today_try);
    document.getElementById('ant-earn-today-sub').textContent = fmtSub(e.today_usd, e.today_btc);
    document.getElementById('ant-earn-yesterday-try').textContent = fmtTRY(e.yesterday_try);
    document.getElementById('ant-earn-yesterday-sub').textContent = fmtSub(e.yesterday_usd, e.yesterday_btc);
    document.getElementById('ant-earn-7d-try').textContent = fmtTRY(e.last7days_try);
    document.getElementById('ant-earn-7d-sub').textContent = fmtSub(e.last7days_usd, e.last7days_btc);
    document.getElementById('ant-earn-total-try').textContent = fmtTRY(e.total_try);
    document.getElementById('ant-earn-total-sub').textContent = fmtSub(e.total_usd, e.total_btc);
  }

  // Cihaz listesi
  let html = '';
  devices.forEach(d => {
    const power = d.hashrate_TH || 0;
    const aktif = power > 0.5;
    let cls = '', badge = '', lbl = '';
    if (aktif) { cls = ''; badge = 'badge-on'; lbl = 'Çalışıyor'; }
    else if (d.sleeping) { cls = 'uyuyor'; badge = 'badge-sleep'; lbl = 'Uyuyor'; }
    else if (d.status === 'TIMEOUT') { cls = 'kapali'; badge = 'badge-off'; lbl = 'Timeout'; }
    else if (!d.online) { cls = 'kapali'; badge = 'badge-off'; lbl = 'Offline'; }
    else { cls = 'uyuyor'; badge = 'badge-sleep'; lbl = '0 Hash'; }

    const eff = d.efficiency_pct;
    const effClr = eff >= 95 ? '#22c55e' : (eff >= 80 ? '#fbbf24' : '#ef4444');
    
    // Saha ve Havuz isimleri
    const sahaW = d.saha_worker || '—';
    const havuzW = d.havuz_worker || d.actual_worker || '—';
    
    // F2Pool hashrate karsilastirma
    let diffBadge = '';
    if (d.hashrate_diff_pct != null && Math.abs(d.hashrate_diff_pct) > 5) {
      const diffColor = d.hashrate_diff_pct > 0 ? '#22c55e' : '#f87171';
      diffBadge = ` <span style="color:${diffColor}; font-size:10px; font-weight:700;">(${d.hashrate_diff_pct > 0 ? '+' : ''}${d.hashrate_diff_pct}%)</span>`;
    }
    
    const tempStr = d.temp_max ? d.temp_max + '°' + (d.temp_water ? ' 💧' + d.temp_water + '°' : '') : '—';
    
    // Lokasyon (varsa)
    const locStr = d.physical_location ? ` · 📍 ${d.physical_location}` : '';

    html += '<div class="cihaz-card ' + cls + '" onclick="antDetay(' + d.suffix + ')">'
      + '<div class="cihaz-row1">'
      + '<div class="cihaz-no" style="font-size:13px">' + (d.name || ('Miner-'+d.suffix)) + '</div>'
      + '<div class="cihaz-badge ' + badge + '">' + lbl + '</div>'
      + '</div>'
      + '<div style="font-size:10px; color:#64748b; font-family:monospace; margin-bottom:2px;">' + d.ip + locStr + '</div>'
      + '<div style="font-size:10px; color:#60a5fa; font-family:monospace;">🏭 ' + sahaW + '</div>'
      + '<div style="font-size:10px; color:#22c55e; font-family:monospace; margin-bottom:2px;">⛏️ ' + havuzW + '</div>'
      + '<div class="cihaz-hash" style="color:#fbbf24">' + (power ? power.toFixed(1) : '—') + ' <span style="font-size:11px;color:#64748b">TH/s</span>' + diffBadge + '</div>'
      + '<div class="cihaz-sub">' + (eff != null ? '<span style="color:'+effClr+';font-weight:700">⚡'+eff+'%</span>' : '') + '</div>'
      + '<div class="cihaz-sub">🌡 ' + tempStr + (d.elapsed_hours ? ' · ⏱ ' + d.elapsed_hours.toFixed(1) + 'h' : '') + '</div>'
      + (d.earn_today_try ? '<div class="cihaz-sub" style="color:#4ade80;font-weight:700;margin-top:4px;border-top:1px solid rgba(255,255,255,0.05);padding-top:4px;">💰 ' + Math.round(d.earn_today_try).toLocaleString('tr-TR') + ' ₺/gün</div>' : '')
      + ((d.health_issues && d.health_issues.length > 0) ? '<div class="cihaz-sub" style="color:#f87171;font-weight:700;margin-top:2px;">⚠️ ' + d.health_issues.length + ' sorun</div>' : '')
      + '</div>';
  });
  document.getElementById('ant-grid').innerHTML = html || '<div class="empty-state" style="grid-column:1/-1">Cihaz yok</div>';

  // Modeller
  let modelHtml = '';
  const grouped = {};
  devices.forEach(d => {
    const m = d.model || '?';
    if (!grouped[m]) grouped[m] = { count: 0, hashrate: 0, target: 0, online: 0 };
    grouped[m].count++;
    grouped[m].hashrate += (d.hashrate_TH || 0);
    grouped[m].target += (d.target_hashrate_TH || 0);
    if (d.online && !d.sleeping) grouped[m].online++;
  });
  Object.entries(grouped).forEach(([model, info]) => {
    const eff = info.target > 0 ? (info.hashrate / info.target * 100).toFixed(1) : '—';
    const jth = antVerimlilik(model);
    const gucKW = (info.hashrate * jth) / 1000;  // toplam guc kW
    modelHtml += '<div class="yillik-card">'
      + '<div class="yillik-title">⛏️ ' + model + ' × ' + info.count + ' adet <span style="font-size:10px;color:#94a3b8;font-weight:600;">(' + jth + ' J/TH)</span></div>'
      + '<div class="yillik-grid">'
      + '<div class="yillik-stat"><div class="yillik-lbl">Toplam Hash</div><div class="yillik-val" style="color:#fbbf24">' + Math.round(info.hashrate).toLocaleString('tr-TR') + '</div><div class="yillik-lbl">TH/s</div></div>'
      + '<div class="yillik-stat"><div class="yillik-lbl">Güç</div><div class="yillik-val" style="color:#ef4444">' + gucKW.toFixed(1) + '</div><div class="yillik-lbl">kW</div></div>'
      + '<div class="yillik-stat"><div class="yillik-lbl">Verimlilik</div><div class="yillik-val" style="color:#4ade80">' + eff + '</div><div class="yillik-lbl">%</div></div>'
      + '<div class="yillik-stat"><div class="yillik-lbl">Aktif</div><div class="yillik-val" style="color:#22c55e">' + info.online + '/' + info.count + '</div><div class="yillik-lbl">cihaz</div></div>'
      + '</div></div>';
  });
  document.getElementById('ant-modeller-liste').innerHTML = modelHtml || '<div class="empty-state">Model yok</div>';

  // Sorunlular
  let sorunluHtml = '';
  const problems = devices.filter(d => 
    !d.online || d.status === 'TIMEOUT' || d.status === 'AUTH_FAIL' || 
    (d.online && !d.sleeping && (d.hashrate_TH || 0) < 0.5) ||
    (d.health_issues && d.health_issues.length > 0)
  );
  if (problems.length === 0) {
    sorunluHtml = '<div style="background:rgba(34,197,94,0.1); border:2px solid #22c55e; padding:20px; border-radius:12px; text-align:center;"><div style="font-size:36px;">✅</div><div style="font-size:18px; font-weight:900; color:#22c55e; margin-top:10px;">Tüm cihazlar sağlıklı!</div></div>';
  } else {
    problems.forEach(d => {
      const issueCount = (d.health_issues || []).length;
      const highSev = (d.health_issues || []).filter(i => i.severity === 'high').length;
      const issueColor = highSev > 0 ? '#ef4444' : '#fbbf24';
      
      let html2 = '<div style="background:rgba(255,255,255,0.03); padding:12px; border-radius:10px; margin-bottom:8px; border-left:4px solid ' + issueColor + '; cursor:pointer;" onclick="antDetay(' + d.suffix + ')">';
      html2 += '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">';
      html2 += '<div style="font-weight:900; font-size:13px;">' + (d.name || ('Miner-'+d.suffix)) + ' <span style="color:#64748b; font-size:11px; font-family:monospace;">(' + d.ip + ')</span></div>';
      html2 += '<div style="font-size:10px; color:' + issueColor + '; font-weight:700;">' + issueCount + ' sorun</div>';
      html2 += '</div>';
      
      (d.health_issues || []).forEach(issue => {
        const sevColor = issue.severity === 'high' ? '#ef4444' : (issue.severity === 'medium' ? '#fbbf24' : '#94a3b8');
        html2 += '<div style="background:#0f172a; padding:6px 8px; border-radius:4px; margin-top:4px; border-left:2px solid ' + sevColor + ';">';
        html2 += '<div style="font-size:11px; font-weight:700; color:' + sevColor + ';">' + issue.icon + ' ' + issue.title + '</div>';
        html2 += '<div style="font-size:10px; color:#94a3b8;">' + issue.reason + '</div>';
        html2 += '</div>';
      });
      
      html2 += '<div style="font-size:10px; color:#64748b; margin-top:6px; text-align:center;">Detay ve çözüm önerileri için tıkla →</div>';
      html2 += '</div>';
      sorunluHtml += html2;
    });
  }
  document.getElementById('ant-sorunlu-liste').innerHTML = sorunluHtml;
}

function antDetay(suffix) {
  if (!antData) return;
  const d = antData.devices.find(x => x.suffix === suffix);
  if (!d) return;

  let status = 'Bilinmiyor';
  let statusColor = '#94a3b8';
  if (d.sleeping) { status = 'Uyuyor'; statusColor = '#fbbf24'; }
  else if (d.online && d.hashrate_TH > 0.5) { status = 'Çalışıyor'; statusColor = '#22c55e'; }
  else if (d.status === 'TIMEOUT') { status = 'Timeout'; statusColor = '#fb923c'; }
  else if (!d.online) { status = 'Offline'; statusColor = '#ef4444'; }

  const eff = d.efficiency_pct;
  const effClr = eff >= 95 ? '#22c55e' : (eff >= 80 ? '#fbbf24' : '#ef4444');

  let html = '<div style="font-size:20px; font-weight:900; margin-bottom:4px;">' + (d.name || ('Miner-'+d.suffix)) + '</div>';
  html += '<div style="font-size:11px; color:#64748b; font-family:monospace; margin-bottom:14px;">' + d.ip + ' · <span style="color:' + statusColor + '; font-weight:700;">' + status + '</span></div>';

  // KPI
  html += '<div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:14px;">';
  html += '<div style="background:#0f172a; padding:10px; border-radius:8px;"><div style="font-size:10px; color:#64748b;">Hashrate</div><div style="font-size:22px; font-weight:900; color:#fbbf24;">' + (d.hashrate_TH ? d.hashrate_TH.toFixed(1) : '—') + '</div><div style="font-size:10px; color:#64748b;">TH/s</div></div>';
  html += '<div style="background:#0f172a; padding:10px; border-radius:8px;"><div style="font-size:10px; color:#64748b;">Verimlilik</div><div style="font-size:22px; font-weight:900; color:' + effClr + ';">' + (eff != null ? eff + '%' : '—') + '</div><div style="font-size:10px; color:#64748b;">nominal</div></div>';
  html += '<div style="background:#0f172a; padding:10px; border-radius:8px;"><div style="font-size:10px; color:#64748b;">Sıcaklık</div><div style="font-size:22px; font-weight:900; color:#fb923c;">' + (d.temp_max || '—') + '°</div><div style="font-size:10px; color:#64748b;">' + (d.temp_water ? '💧 ' + d.temp_water + '°' : 'PCB max') + '</div></div>';
  html += '<div style="background:#0f172a; padding:10px; border-radius:8px;"><div style="font-size:10px; color:#64748b;">Çalışma Süresi</div><div style="font-size:22px; font-weight:900; color:#60a5fa;">' + (d.elapsed_hours ? d.elapsed_hours.toFixed(1) : '—') + '</div><div style="font-size:10px; color:#64748b;">saat</div></div>';
  html += '</div>';

  // Kalici kimlik
  html += '<div style="background:rgba(251,191,36,0.1); padding:10px; border-radius:6px; margin-bottom:10px; border-left:3px solid #fbbf24;">';
  html += '<div style="font-weight:900; color:#fbbf24; margin-bottom:6px;">🔑 KALICI KİMLİK</div>';
  if (d.mac) html += '<div>📡 <b>MAC:</b> <code style="background:#0f172a;padding:2px 6px;border-radius:4px;color:#fbbf24;">' + d.mac + '</code></div>';
  if (d.saha_worker) html += '<div>🏭 <b>Saha:</b> <code style="background:#0f172a;padding:2px 6px;border-radius:4px;color:#60a5fa;">' + d.saha_worker + '</code></div>';
  if (d.havuz_worker || d.actual_worker) html += '<div>⛏️ <b>Havuz:</b> <code style="background:#0f172a;padding:2px 6px;border-radius:4px;color:#22c55e;">' + (d.havuz_worker || d.actual_worker) + '</code></div>';
  if (d.model) html += '<div>🔧 <b>Model:</b> ' + d.model + '</div>';
  html += '</div>';

  // Kazanc (cihaz icin)
  if (d.earn_today_try != null || d.earn_today_btc != null) {
    const fmtRow = (lbl, btc, usd, tryV, color) => 
      '<div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05);">' +
      '<span style="font-size:11px; color:#94a3b8;">' + lbl + '</span>' +
      '<span style="font-weight:700; color:' + color + ';">' + 
      (tryV ? Math.round(tryV).toLocaleString('tr-TR') + ' ₺' : '—') +
      ' <span style="font-size:10px; color:#64748b;">($' + (usd ? Math.round(usd) : '—') + ' · ' + (btc ? btc.toFixed(6) : '—') + ')</span>' +
      '</span></div>';
    html += '<div style="background:rgba(34,197,94,0.08); padding:10px; border-radius:6px; margin-bottom:10px; border-left:3px solid #22c55e;">';
    html += '<div style="font-weight:900; color:#4ade80; margin-bottom:6px;">💰 KAZANÇ</div>';
    html += fmtRow('Bugün', d.earn_today_btc, d.earn_today_usd, d.earn_today_try, '#fbbf24');
    html += fmtRow('Dün', d.earn_yesterday_btc, d.earn_yesterday_usd, d.earn_yesterday_try, '#94a3b8');
    html += fmtRow('Son 7 Gün', d.earn_7d_btc, d.earn_7d_usd, d.earn_7d_try, '#60a5fa');
    html += fmtRow('Toplam', d.earn_total_btc, d.earn_total_usd, d.earn_total_try, '#22c55e');
    html += '</div>';
  }

  // Ariza ve cozumler
  if (d.health_issues && d.health_issues.length > 0) {
    html += '<div style="background:rgba(239,68,68,0.08); padding:10px; border-radius:6px; margin-bottom:10px; border-left:3px solid #ef4444;">';
    html += '<div style="font-weight:900; color:#f87171; margin-bottom:8px;">⚠️ TESPİT EDİLEN SORUNLAR (' + d.health_issues.length + ')</div>';
    d.health_issues.forEach(issue => {
      const sevColor = issue.severity === 'high' ? '#ef4444' : (issue.severity === 'medium' ? '#fbbf24' : '#94a3b8');
      html += '<div style="background:#0f172a; padding:8px; border-radius:6px; margin-bottom:6px; border-left:3px solid ' + sevColor + ';">';
      html += '<div style="font-weight:700; color:' + sevColor + '; font-size:12px;">' + issue.icon + ' ' + issue.title + '</div>';
      html += '<div style="font-size:11px; color:#94a3b8; margin:3px 0;">' + issue.reason + '</div>';
      html += '<div style="font-size:10px; color:#cbd5e1; margin-top:4px;"><b>Çözüm:</b></div>';
      html += '<ul style="margin:2px 0 0 16px; padding:0; font-size:10px; color:#94a3b8;">';
      issue.solutions.forEach(s => { html += '<li style="margin:2px 0;">' + s + '</li>'; });
      html += '</ul></div>';
    });
    html += '</div>';
  } else if (d.online && !d.sleeping) {
    html += '<div style="background:rgba(34,197,94,0.08); padding:8px; border-radius:6px; margin-bottom:10px; text-align:center; color:#4ade80; font-size:12px;">✅ Cihazda herhangi bir sorun tespit edilmedi</div>';
  }

  // Kontrol butonlari
  html += '<div style="display:flex; gap:8px; margin-top:14px;">';
  html += '<button onclick="antKomut(\"wake\", [' + d.suffix + '], \"' + (d.name || 'Miner-'+d.suffix) + '\")" style="flex:1; background:linear-gradient(135deg,#22c55e,#16a34a); color:white; border:none; padding:12px; border-radius:10px; font-weight:700; cursor:pointer; font-size:13px;">▶️ Çalıştır</button>';
  html += '<button onclick="antKomut(\"sleep\", [' + d.suffix + '], \"' + (d.name || 'Miner-'+d.suffix) + '\")" style="flex:1; background:linear-gradient(135deg,#f59e0b,#d97706); color:white; border:none; padding:12px; border-radius:10px; font-weight:700; cursor:pointer; font-size:13px;">💤 Uyut</button>';
  html += '</div>';

  document.getElementById('ant-modal-icerik').innerHTML = html;
  document.getElementById('ant-modal').classList.add('active');
}

function kapatAntModal() { document.getElementById('ant-modal').classList.remove('active'); }

function antKomut(action, targets, isim) {
  const aksiyonAd = action === 'sleep' ? 'UYUT' : 'ÇALIŞTIR';
  const onayMesaji = targets === 'all' 
    ? `TÜM CİHAZLARI ${aksiyonAd} işlemini onaylıyor musun?`
    : `${isim} cihazını ${aksiyonAd} işlemini onaylıyor musun?`;
  
  if (!confirm(onayMesaji)) return;

  const statusEl = document.getElementById('ant-cmd-status');
  if (statusEl) statusEl.innerHTML = '<span style="color:#fbbf24">⏳ Komut gönderiliyor...</span>';

  fetch('/api/antminer/command', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ action, targets })
  }).then(r => r.json()).then(d => {
    if (d.hata) {
      alert('Hata: ' + d.hata);
      if (statusEl) statusEl.innerHTML = '<span style="color:#ef4444">❌ Hata: ' + d.hata + '</span>';
    } else {
      const cnt = targets === 'all' ? 'tümü' : targets.length + ' cihaz';
      if (statusEl) statusEl.innerHTML = '<span style="color:#22c55e">✅ Komut gönderildi (' + cnt + ') - 15 sn içinde uygulanacak</span>';
      kapatAntModal();
      // 20 saniye sonra paneli yenile
      setTimeout(() => { antYukle(); if (statusEl) statusEl.innerHTML = ''; }, 20000);
    }
  }).catch(e => {
    alert('Bağlantı hatası: ' + e);
    if (statusEl) statusEl.innerHTML = '';
  });
}

function antBulk(action) {
  antKomut(action, 'all', 'TÜM');
}


// ======================== CIHAZLARIM SEKMESI ========================

function cmmRender() {
  if (!antData) return;
  
  // Bekleyen onaylari yukle (her render'da)
  cmmBekleyenYukle();
  
  const s = antData.summary || {};
  const devices = antData.devices || [];
  const earnings = s.earnings || {};
  
  // Header sub
  const ts = antData.timestamp ? new Date(antData.timestamp).toLocaleTimeString('tr-TR') : '—';
  const modelList = Object.entries(s.models || {}).map(([m,c]) => m+'×'+c).join(' · ');
  document.getElementById('cmm-sub').textContent = modelList + ' · Son güncel: ' + ts;
  
  // Stat
  let stat = (s.total || 0) + ' cihaz';
  if (s.f2pool && s.f2pool.enabled) {
    stat += ' · F2Pool ' + (s.f2pool.matched_devices || 0) + '/' + (s.total || 0) + ' eşleşti';
  }
  document.getElementById('cmm-stat').textContent = stat;
  
  // KPI
  document.getElementById('cmm-hash').textContent = Math.round(s.total_hashrate_TH || 0).toLocaleString('tr-TR');
  document.getElementById('cmm-hash-sub').textContent = 'TH/s (hedef: ' + Math.round(s.total_target_TH || 0).toLocaleString('tr-TR') + ')';
  
  document.getElementById('cmm-online').textContent = s.online || 0;
  document.getElementById('cmm-online-sub').textContent = '/ ' + (s.total || 0) + ' cihaz';
  
  const eff = s.efficiency_pct || 0;
  document.getElementById('cmm-eff').textContent = eff;
  document.getElementById('cmm-eff').style.color = eff >= 95 ? '#22c55e' : (eff >= 80 ? '#fbbf24' : '#ef4444');
  
  // Kazanc
  const fmtTRY = (v) => v ? Math.round(v).toLocaleString('tr-TR') + ' ₺' : '— ₺';
  const fmtBoth = (usd, btc) => '$' + (usd ? Math.round(usd).toLocaleString('tr-TR') : '—') + ' · ' + (btc ? btc.toFixed(6) + ' BTC' : '— BTC');
  
  document.getElementById('cmm-total-earn').textContent = fmtTRY(earnings.total_try);
  document.getElementById('cmm-total-earn-sub').textContent = fmtBoth(earnings.total_usd, earnings.total_btc);
  document.getElementById('cmm-earn-today').textContent = fmtTRY(earnings.today_try);
  document.getElementById('cmm-earn-today-sub').textContent = fmtBoth(earnings.today_usd, earnings.today_btc);
  document.getElementById('cmm-earn-yesterday').textContent = fmtTRY(earnings.yesterday_try);
  document.getElementById('cmm-earn-yesterday-sub').textContent = fmtBoth(earnings.yesterday_usd, earnings.yesterday_btc);
  document.getElementById('cmm-earn-7d').textContent = fmtTRY(earnings.last7days_try);
  document.getElementById('cmm-earn-7d-sub').textContent = fmtBoth(earnings.last7days_usd, earnings.last7days_btc);
  document.getElementById('cmm-earn-total').textContent = fmtTRY(earnings.total_try);
  document.getElementById('cmm-earn-total-sub').textContent = fmtBoth(earnings.total_usd, earnings.total_btc);
  
  // Aylik grafik
  cmmDrawMonthlyChart(antData.monthly_history || []);
  
  // Cihaz grid (premium)
  cmmRenderDevices(devices, earnings);
  
  // Gunluk liste
  cmmRenderDailyList(antData.daily_history || [], earnings);
}


function cmmDrawMonthlyChart(monthly) {
  const container = document.getElementById('cmm-monthly-chart');
  const infoEl = document.getElementById('cmm-monthly-info');
  
  if (!monthly || monthly.length === 0) {
    container.innerHTML = '<div style="width:100%; text-align:center; color:#64748b; font-size:11px; padding:30px 0;">Henüz veri yok — birkaç gün veri biriktikten sonra grafiğin görüneecek</div>';
    infoEl.textContent = '';
    return;
  }
  
  const maxHash = Math.max(...monthly.map(m => m.avg_hash_TH));
  const maxEarn = Math.max(...monthly.map(m => m.earn_btc));
  let totalBtc = monthly.reduce((s,m) => s + m.earn_btc, 0);
  infoEl.textContent = 'Toplam: ' + totalBtc.toFixed(6) + ' BTC';
  
  // Eskiden yeniye sirala
  const sorted = [...monthly].reverse();
  let html = '';
  sorted.forEach(m => {
    const heightPct = maxHash > 0 ? (m.avg_hash_TH / maxHash) * 100 : 0;
    const earnPct = maxEarn > 0 ? (m.earn_btc / maxEarn) * 100 : 0;
    const [year, monthNum] = m.month.split('-');
    const monthName = ['Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara'][parseInt(monthNum)-1] || monthNum;
    html += '<div style="flex:1; min-width:30px; display:flex; flex-direction:column; align-items:center; gap:3px;">';
    html += '<div style="font-size:9px; color:#fbbf24; font-weight:700;">' + (m.avg_hash_TH > 0 ? Math.round(m.avg_hash_TH) : '') + '</div>';
    html += '<div style="width:100%; height:90px; display:flex; flex-direction:column; justify-content:flex-end; gap:2px;">';
    html += '<div style="width:100%; height:' + heightPct + '%; background:linear-gradient(180deg, rgba(251,191,36,0.9), rgba(251,191,36,0.3)); border-radius:3px 3px 0 0; min-height:2px;" title="Hash: ' + m.avg_hash_TH + ' TH/s"></div>';
    html += '</div>';
    html += '<div style="font-size:10px; color:#94a3b8; font-weight:700;">' + monthName + '</div>';
    html += '<div style="font-size:8px; color:#64748b;">' + year.slice(2) + '</div>';
    html += '</div>';
  });
  container.innerHTML = html;
}


function cmmRenderDevices(devices, earnings) {
  let html = '';
  devices.forEach(d => {
    const power = d.hashrate_TH || 0;
    const aktif = power > 0.5;
    let cls = 'cihaz-card', badge = 'badge-on', lbl = 'Çalışıyor', borderColor = '#22c55e';
    if (aktif) { borderColor = '#22c55e'; }
    else if (d.sleeping) { cls += ' uyuyor'; badge = 'badge-sleep'; lbl = 'Uyuyor'; borderColor = '#fbbf24'; }
    else if (d.status === 'TIMEOUT') { cls += ' kapali'; badge = 'badge-off'; lbl = 'Timeout'; borderColor = '#fb923c'; }
    else if (!d.online) { cls += ' kapali'; badge = 'badge-off'; lbl = 'Offline'; borderColor = '#ef4444'; }
    else { cls += ' uyuyor'; badge = 'badge-sleep'; lbl = '0 Hash'; borderColor = '#94a3b8'; }
    
    // Sorun rozetleri
    const issueCount = (d.health_issues || []).length;
    const highSev = (d.health_issues || []).filter(i => i.severity === 'high').length;
    
    const sahaW = d.saha_worker || '—';
    const havuzW = d.havuz_worker || d.actual_worker || '—';
    const eff = d.efficiency_pct;
    const effClr = eff >= 95 ? '#22c55e' : (eff >= 80 ? '#fbbf24' : '#ef4444');
    
    html += '<div class="' + cls + '" style="cursor:pointer; border-left:3px solid ' + borderColor + '; background:linear-gradient(135deg, rgba(255,255,255,0.02), transparent);" onclick="cmmDetay(' + d.suffix + ')">';
    
    // Üst satır
    html += '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">';
    html += '<div style="font-size:13px; font-weight:900;">' + (d.name || ('Miner-'+d.suffix)) + '</div>';
    html += '<div class="cihaz-badge ' + badge + '">' + lbl + '</div>';
    html += '</div>';
    
    // IP + Seri
    html += '<div style="font-size:10px; color:#64748b; font-family:monospace; margin-bottom:4px;">' + d.ip + '</div>';
    if (d.serial) html += '<div style="font-size:9px; color:#fbbf24; font-family:monospace; margin-bottom:4px;">🔖 ' + d.serial + '</div>';
    
    // SAHA & HAVUZ
    html += '<div style="display:flex; gap:6px; margin-bottom:6px;">';
    html += '<div style="flex:1; background:rgba(96,165,250,0.08); border-left:2px solid #60a5fa; padding:4px 6px; border-radius:4px;">';
    html += '<div style="font-size:8px; color:#94a3b8;">🏭 SAHA</div>';
    html += '<div style="font-size:10px; color:#60a5fa; font-family:monospace; font-weight:700;">' + sahaW + '</div>';
    html += '</div>';
    html += '<div style="flex:1; background:rgba(34,197,94,0.08); border-left:2px solid #22c55e; padding:4px 6px; border-radius:4px;">';
    html += '<div style="font-size:8px; color:#94a3b8;">⛏️ HAVUZ</div>';
    html += '<div style="font-size:10px; color:#22c55e; font-family:monospace; font-weight:700;">' + havuzW + '</div>';
    html += '</div>';
    html += '</div>';
    
    // Hashrate buyuk
    html += '<div style="font-size:24px; font-weight:900; color:#fbbf24; margin-bottom:2px;">' + (power ? power.toFixed(1) : '—') + ' <span style="font-size:11px; color:#64748b;">TH/s</span></div>';
    
    // Verim + sicaklik
    const tempStr = d.temp_max ? d.temp_max + '°' + (d.temp_water ? ' 💧' + d.temp_water + '°' : '') : '—';
    html += '<div style="font-size:10px; color:#94a3b8; display:flex; justify-content:space-between; margin-bottom:4px;">';
    html += '<span>' + (eff != null ? '<span style="color:'+effClr+';font-weight:700">⚡'+eff+'%</span>' : '') + '</span>';
    html += '<span>🌡 ' + tempStr + '</span>';
    html += '</div>';
    
    // Kazanc + Sorun
    if (d.earn_today_try) {
      html += '<div style="margin-top:6px; padding-top:6px; border-top:1px solid rgba(255,255,255,0.05); display:flex; justify-content:space-between; align-items:center;">';
      html += '<div style="font-size:11px; color:#4ade80; font-weight:700;">💰 ' + Math.round(d.earn_today_try).toLocaleString('tr-TR') + ' ₺/gün</div>';
      if (issueCount > 0) {
        const color = highSev > 0 ? '#ef4444' : '#fbbf24';
        html += '<div style="font-size:10px; color:' + color + '; font-weight:700;">⚠️ ' + issueCount + '</div>';
      }
      html += '</div>';
    } else if (issueCount > 0) {
      const color = highSev > 0 ? '#ef4444' : '#fbbf24';
      html += '<div style="margin-top:6px; padding-top:6px; border-top:1px solid rgba(255,255,255,0.05); font-size:10px; color:' + color + '; font-weight:700;">⚠️ ' + issueCount + ' sorun</div>';
    }
    
    html += '</div>';
  });
  document.getElementById('cmm-grid').innerHTML = html || '<div class="empty-state" style="grid-column:1/-1">Cihaz yok</div>';
}


function cmmRenderDailyList(daily, earnings) {
  const infoEl = document.getElementById('cmm-daily-info');
  const listEl = document.getElementById('cmm-daily-list');
  
  if (!daily || daily.length === 0) {
    listEl.innerHTML = '<div class="empty-state">Henüz günlük veri yok</div>';
    infoEl.textContent = '';
    return;
  }
  
  const usd_try = earnings.usd_try || 0;
  const btc_usd = earnings.btc_price_usd || 0;
  
  let totalBtc = daily.reduce((s,d) => s + (d.total_earn_btc || 0), 0);
  infoEl.textContent = '30 gün: ' + totalBtc.toFixed(6) + ' BTC';
  
  let html = '<div style="display:grid; grid-template-columns:1fr; gap:4px;">';
  // En yeni en üstte
  const sorted = [...daily].reverse();
  sorted.forEach(d => {
    const dt = new Date(d.date);
    const dateStr = dt.toLocaleDateString('tr-TR', {day:'2-digit', month:'short', weekday:'short'});
    const earnTry = d.total_earn_btc * btc_usd * usd_try;
    html += '<div style="display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:8px; padding:8px 10px; background:rgba(255,255,255,0.02); border-radius:6px; align-items:center;">';
    html += '<div style="font-size:11px; color:#cbd5e1;">' + dateStr + '</div>';
    html += '<div style="font-size:11px; color:#fbbf24; font-weight:700;">' + (d.total_hash_TH ? Math.round(d.total_hash_TH) + ' TH/s' : '—') + '</div>';
    html += '<div style="font-size:11px; color:#22c55e; font-weight:700;">' + (earnTry ? Math.round(earnTry).toLocaleString('tr-TR') + ' ₺' : '—') + '</div>';
    html += '<div style="font-size:10px; color:#64748b; text-align:right;">' + (d.total_earn_btc ? d.total_earn_btc.toFixed(6) + ' BTC' : '—') + '</div>';
    html += '</div>';
  });
  html += '</div>';
  listEl.innerHTML = html;
}


function cmmDetay(suffix) {
  if (!antData) return;
  const d = antData.devices.find(x => x.suffix === suffix);
  if (!d) return;
  
  const power = d.hashrate_TH || 0;
  let status = 'Bilinmiyor', statusColor = '#94a3b8';
  if (d.sleeping) { status = 'Uyuyor'; statusColor = '#fbbf24'; }
  else if (d.online && power > 0.5) { status = 'Çalışıyor'; statusColor = '#22c55e'; }
  else if (d.status === 'TIMEOUT') { status = 'Timeout'; statusColor = '#fb923c'; }
  else if (!d.online) { status = 'Offline'; statusColor = '#ef4444'; }
  
  const eff = d.efficiency_pct;
  const effClr = eff >= 95 ? '#22c55e' : (eff >= 80 ? '#fbbf24' : '#ef4444');
  const fmtTRY = v => v ? Math.round(v).toLocaleString('tr-TR') + ' ₺' : '—';
  
  let html = '';
  
  // Üst Header
  html += '<div style="background:linear-gradient(135deg, rgba(251,191,36,0.15), rgba(34,197,94,0.05)); padding:18px; border-bottom:1px solid rgba(255,255,255,0.08); position:relative;">';
  html += '<div style="font-size:22px; font-weight:900; background:linear-gradient(90deg,#fbbf24,#22c55e); -webkit-background-clip:text; background-clip:text; color:transparent;">' + (d.name || ('Miner-'+d.suffix)) + '</div>';
  html += '<div style="font-size:11px; color:#64748b; font-family:monospace; margin-top:2px;">' + d.ip + ' · <span style="color:' + statusColor + '; font-weight:700;">' + status + '</span></div>';
  if (d.model) html += '<div style="font-size:10px; color:#94a3b8; margin-top:2px;">' + d.model + '</div>';
  html += '</div>';
  
  html += '<div style="padding:16px;">';
  
  // Saha & Havuz YAN YANA
  html += '<div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:14px;">';
  html += '<div style="background:rgba(96,165,250,0.08); border:1px solid rgba(96,165,250,0.25); padding:12px; border-radius:10px;">';
  html += '<div style="font-size:11px; color:#60a5fa; font-weight:900; margin-bottom:8px;">🏭 SAHA</div>';
  html += '<div style="font-size:9px; color:#94a3b8;">Worker:</div>';
  html += '<div style="font-size:13px; color:#60a5fa; font-family:monospace; font-weight:700; margin-bottom:6px;">' + (d.saha_worker || '—') + '</div>';
  html += '<div style="font-size:9px; color:#94a3b8;">MAC:</div>';
  html += '<div style="font-size:10px; color:#fbbf24; font-family:monospace; word-break:break-all; margin-bottom:6px;">' + (d.mac || '—') + '</div>';
  html += '<div style="font-size:9px; color:#94a3b8;">Seri No:</div>';
  html += '<div style="font-size:11px; color:#fb923c; font-family:monospace; font-weight:700; word-break:break-all;">' + (d.serial || '—') + '</div>';
  html += '</div>';
  html += '<div style="background:rgba(34,197,94,0.08); border:1px solid rgba(34,197,94,0.25); padding:12px; border-radius:10px;">';
  html += '<div style="font-size:11px; color:#22c55e; font-weight:900; margin-bottom:8px;">⛏️ HAVUZ</div>';
  html += '<div style="font-size:9px; color:#94a3b8;">Worker:</div>';
  html += '<div style="font-size:13px; color:#22c55e; font-family:monospace; font-weight:700; margin-bottom:6px;">' + (d.havuz_worker || d.actual_worker || '—') + '</div>';
  html += '<div style="font-size:9px; color:#94a3b8;">F2Pool 24h:</div>';
  html += '<div style="font-size:11px; color:#22c55e; font-weight:700;">' + (d.f2pool_h24_TH ? d.f2pool_h24_TH + ' TH/s' : '—') + '</div>';
  html += '</div>';
  html += '</div>';
  
  // KPI mini grid
  html += '<div style="display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:6px; margin-bottom:14px;">';
  html += '<div style="background:#0f172a; padding:8px; border-radius:6px; text-align:center;"><div style="font-size:9px; color:#64748b;">Hashrate</div><div style="font-size:16px; font-weight:900; color:#fbbf24;">' + (power ? power.toFixed(1) : '—') + '</div><div style="font-size:8px; color:#64748b;">TH/s</div></div>';
  html += '<div style="background:#0f172a; padding:8px; border-radius:6px; text-align:center;"><div style="font-size:9px; color:#64748b;">Verim</div><div style="font-size:16px; font-weight:900; color:' + effClr + ';">' + (eff != null ? eff : '—') + '</div><div style="font-size:8px; color:#64748b;">%</div></div>';
  html += '<div style="background:#0f172a; padding:8px; border-radius:6px; text-align:center;"><div style="font-size:9px; color:#64748b;">Sıcaklık</div><div style="font-size:16px; font-weight:900; color:#fb923c;">' + (d.temp_max || '—') + '°</div><div style="font-size:8px; color:#64748b;">' + (d.temp_water ? '💧' + d.temp_water + '°' : '—') + '</div></div>';
  html += '<div style="background:#0f172a; padding:8px; border-radius:6px; text-align:center;"><div style="font-size:9px; color:#64748b;">Süre</div><div style="font-size:16px; font-weight:900; color:#a855f7;">' + (d.elapsed_hours ? d.elapsed_hours.toFixed(0) : '—') + '</div><div style="font-size:8px; color:#64748b;">saat</div></div>';
  html += '</div>';
  
  // Kazanç
  if (d.earn_today_btc != null) {
    html += '<div style="background:rgba(34,197,94,0.06); border:1px solid rgba(34,197,94,0.2); border-radius:10px; padding:12px; margin-bottom:14px;">';
    html += '<div style="font-size:12px; font-weight:900; color:#4ade80; margin-bottom:8px;">💰 KAZANÇ</div>';
    [
      ['Bugün', d.earn_today_btc, d.earn_today_usd, d.earn_today_try, '#fbbf24'],
      ['Dün', d.earn_yesterday_btc, d.earn_yesterday_usd, d.earn_yesterday_try, '#94a3b8'],
      ['Son 7 Gün', d.earn_7d_btc, d.earn_7d_usd, d.earn_7d_try, '#60a5fa'],
      ['Toplam', d.earn_total_btc, d.earn_total_usd, d.earn_total_try, '#22c55e'],
    ].forEach(([lbl, btc, usd, tryV, col]) => {
      html += '<div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid rgba(255,255,255,0.04); font-size:11px;">';
      html += '<span style="color:#94a3b8;">' + lbl + '</span>';
      html += '<span style="color:' + col + '; font-weight:700;">' + fmtTRY(tryV) + ' <span style="font-size:9px; color:#64748b;">($' + (usd ? Math.round(usd) : '—') + ' · ' + (btc ? btc.toFixed(6) : '—') + ')</span></span>';
      html += '</div>';
    });
    html += '</div>';
  }
  
  // Aylik mini grafik
  if (d.monthly_history && d.monthly_history.length > 0) {
    const monthly = d.monthly_history;
    const maxH = Math.max(...monthly.map(m => m.avg_hash_TH));
    html += '<div style="background:rgba(96,165,250,0.05); border:1px solid rgba(96,165,250,0.15); border-radius:10px; padding:12px; margin-bottom:14px;">';
    html += '<div style="font-size:12px; font-weight:900; color:#60a5fa; margin-bottom:10px;">📈 AYLIK ÜRETİM</div>';
    html += '<div style="display:flex; align-items:flex-end; gap:3px; height:80px;">';
    [...monthly].reverse().forEach(m => {
      const hp = maxH > 0 ? (m.avg_hash_TH / maxH) * 100 : 0;
      const [, mn] = m.month.split('-');
      const monthName = ['Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara'][parseInt(mn)-1];
      html += '<div style="flex:1; display:flex; flex-direction:column; align-items:center; gap:2px;">';
      html += '<div style="width:100%; height:50px; display:flex; flex-direction:column; justify-content:flex-end;">';
      html += '<div style="width:100%; height:' + hp + '%; background:linear-gradient(180deg,#60a5fa,rgba(96,165,250,0.3)); border-radius:2px 2px 0 0;"></div>';
      html += '</div>';
      html += '<div style="font-size:8px; color:#94a3b8;">' + monthName + '</div>';
      html += '</div>';
    });
    html += '</div></div>';
  }
  
  // Gunluk liste (mini)
  if (d.daily_history && d.daily_history.length > 0) {
    html += '<div style="background:rgba(34,197,94,0.05); border:1px solid rgba(34,197,94,0.15); border-radius:10px; padding:12px; margin-bottom:14px;">';
    html += '<div style="font-size:12px; font-weight:900; color:#22c55e; margin-bottom:8px;">📅 SON 7 GÜN</div>';
    [...d.daily_history].reverse().slice(0, 7).forEach(day => {
      const dt = new Date(day.date);
      const dateStr = dt.toLocaleDateString('tr-TR', {day:'2-digit', month:'short'});
      html += '<div style="display:flex; justify-content:space-between; padding:4px 0; font-size:10px; border-bottom:1px solid rgba(255,255,255,0.03);">';
      html += '<span style="color:#cbd5e1;">' + dateStr + (day.estimated ? ' <span style="color:#94a3b8; font-size:8px;">(tahmini)</span>' : '') + '</span>';
      html += '<span style="color:#fbbf24; font-weight:700;">' + (day.avg_hash_TH ? day.avg_hash_TH + ' TH/s' : '—') + '</span>';
      html += '<span style="color:#22c55e;">' + (day.uptime_pct ? day.uptime_pct + '%' : '—') + '</span>';
      html += '</div>';
    });
    html += '</div>';
  }
  
  // Ariza
  if (d.health_issues && d.health_issues.length > 0) {
    html += '<div style="background:rgba(239,68,68,0.06); border:1px solid rgba(239,68,68,0.2); border-radius:10px; padding:12px; margin-bottom:14px;">';
    html += '<div style="font-size:12px; font-weight:900; color:#f87171; margin-bottom:8px;">⚠️ TESPİT EDİLEN SORUNLAR (' + d.health_issues.length + ')</div>';
    d.health_issues.forEach(issue => {
      const sevColor = issue.severity === 'high' ? '#ef4444' : (issue.severity === 'medium' ? '#fbbf24' : '#94a3b8');
      html += '<div style="background:#0f172a; padding:8px; border-radius:6px; margin-bottom:6px; border-left:3px solid ' + sevColor + ';">';
      html += '<div style="font-weight:700; color:' + sevColor + '; font-size:11px;">' + issue.icon + ' ' + issue.title + '</div>';
      html += '<div style="font-size:10px; color:#94a3b8; margin:3px 0;">' + issue.reason + '</div>';
      html += '<div style="font-size:9px; color:#cbd5e1; margin-top:4px;"><b>Çözüm:</b></div>';
      html += '<ul style="margin:2px 0 0 14px; padding:0; font-size:9px; color:#94a3b8;">';
      issue.solutions.forEach(s => html += '<li style="margin:1px 0;">' + s + '</li>');
      html += '</ul></div>';
    });
    html += '</div>';
  } else if (d.online && !d.sleeping) {
    html += '<div style="background:rgba(34,197,94,0.06); padding:10px; border-radius:8px; margin-bottom:14px; text-align:center; color:#4ade80; font-size:11px;">✅ Cihaz sağlıklı çalışıyor</div>';
  }
  
  // Kontrol butonları
  const isim = (d.name || ('Miner-'+d.suffix)).replace(/'/g, "\'");
  html += '<div style="display:flex; gap:8px;">';
  html += '<button onclick="antKomut(\"wake\",[' + d.suffix + '],\"' + isim + '\")" style="flex:1; background:linear-gradient(135deg,#22c55e,#16a34a); color:white; border:none; padding:14px; border-radius:10px; font-weight:900; cursor:pointer; font-size:13px;">▶️ Çalıştır</button>';
  html += '<button onclick="antKomut(\"sleep\",[' + d.suffix + '],\"' + isim + '\")" style="flex:1; background:linear-gradient(135deg,#f59e0b,#d97706); color:white; border:none; padding:14px; border-radius:10px; font-weight:900; cursor:pointer; font-size:13px;">💤 Uyut</button>';
  html += '</div>';
  
  html += '</div>'; // padding kapanışı
  
  document.getElementById('cmm-modal-icerik').innerHTML = html;
  document.getElementById('cmm-modal').classList.add('active');
}

function kapatCmmModal() { document.getElementById('cmm-modal').classList.remove('active'); }

function cmmBulk(action) {
  const statusEl = document.getElementById('cmm-cmd-status');
  if (statusEl) statusEl.innerHTML = '<span style="color:#fbbf24">⏳ Komut gönderiliyor...</span>';
  antKomut(action, 'all', 'TÜM');
}

function cmmBekleyenYukle() {
  fetch('/api/bekleyen_onaylar').then(r => r.json()).then(d => {
    const onaylar = (d.onaylar || []).filter(o => o.durum === 'bekliyor');
    const container = document.getElementById('cmm-bekleyen');
    const liste = document.getElementById('cmm-bekleyen-liste');
    
    if (onaylar.length === 0) {
      container.style.display = 'none';
      return;
    }
    
    container.style.display = 'block';
    let html = '';
    onaylar.forEach(o => {
      const eylem = o.eylem === 'wake' ? '▶️ ÇALIŞTIR' : '💤 UYUT';
      const eylemColor = o.eylem === 'wake' ? '#22c55e' : '#f59e0b';
      const saatAd = o.saat_durumu || '';
      
      html += '<div style="background:rgba(0,0,0,0.3); border-left:4px solid ' + eylemColor + '; padding:10px; border-radius:6px; margin-bottom:8px;">';
      html += '<div style="display:flex; justify-content:space-between; align-items:start; margin-bottom:6px;">';
      html += '<div>';
      html += '<div style="font-size:14px; font-weight:900; color:' + eylemColor + ';">' + eylem + ' - Saat ' + String(o.hedef_saat).padStart(2, '0') + ':00</div>';
      html += '<div style="font-size:10px; color:#94a3b8;">' + saatAd + ' saat · Oluşturulma: ' + o.olusturulma + '</div>';
      html += '<div style="font-size:10px; color:#64748b; margin-top:2px;">Şu an: ' + o.mevcut_online + ' açık, ' + o.mevcut_sleeping + ' uyuyor</div>';
      html += '</div>';
      html += '</div>';
      html += '<div style="display:flex; gap:6px; margin-top:8px;">';
      html += '<button onclick="cmmOnayKarar(\"' + o.id + '\",\"onayla\")" style="flex:1; background:linear-gradient(135deg,#22c55e,#16a34a); color:white; border:none; padding:10px; border-radius:8px; font-weight:900; cursor:pointer; font-size:12px;">✅ ONAYLA</button>';
      html += '<button onclick="cmmOnayKarar(\"' + o.id + '\",\"reddet\")" style="flex:1; background:rgba(239,68,68,0.2); color:#f87171; border:1px solid rgba(239,68,68,0.4); padding:10px; border-radius:8px; font-weight:900; cursor:pointer; font-size:12px;">❌ REDDET</button>';
      html += '</div>';
      html += '</div>';
    });
    liste.innerHTML = html;
  }).catch(e => console.error('Onay yukleme hatasi:', e));
}

function cmmOnayKarar(onayId, karar) {
  const onayMsg = karar === 'onayla' 
    ? '✅ Onaylıyorum - Cihazlar 10 sn aralıklı sıralı uygulayacak (~5 dk sürer)'
    : '❌ Reddediyorum - Cihazlar mevcut durumda kalacak';
  if (!confirm(onayMsg)) return;
  
  fetch('/api/bekleyen_onaylar/' + onayId + '/karar', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ karar })
  }).then(r => r.json()).then(d => {
    if (d.hata) {
      alert('Hata: ' + d.hata);
    } else {
      const mesaj = karar === 'onayla' 
        ? '✅ Onaylandı, cihazlara komut gönderildi (~5 dk)'
        : '❌ Reddedildi';
      alert(mesaj);
      cmmBekleyenYukle();
      if (karar === 'onayla') antYukle();
    }
  }).catch(e => alert('Bağlantı hatası: ' + e));
}

function cmmBulkSirali(action) {
  const aksiyon = action === 'sleep' ? 'UYUT' : 'ÇALIŞTIR';
  const siralama = action === 'sleep' ? 'en düşük hashrate önce' : 'en yüksek 24h hashrate önce';
  const tahmini = 29 * 10;
  
  if (!confirm(`🎛️ SIRALI ${aksiyon}\n\n29 cihaz, 10 sn aralıklı (${siralama})\nTahmini süre: ${tahmini} sn (~${Math.round(tahmini/60)} dk)\n\nOnaylıyor musun?`)) return;
  
  const statusEl = document.getElementById('cmm-cmd-status');
  if (statusEl) statusEl.innerHTML = '<span style="color:#fbbf24">⏳ Sıralı komut gönderiliyor... (~' + Math.round(tahmini/60) + ' dk sürecek)</span>';
  
  fetch('/api/antminer/command', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      action,
      targets: 'all',
      delay_sec: 10,
      sort_by: action === 'sleep' ? 'hashrate_asc' : 'hashrate_24h_desc'
    })
  }).then(r => r.json()).then(d => {
    if (d.hata) {
      alert('Hata: ' + d.hata);
      if (statusEl) statusEl.innerHTML = '<span style="color:#ef4444">❌ ' + d.hata + '</span>';
    } else {
      if (statusEl) statusEl.innerHTML = '<span style="color:#22c55e">✅ Sıralı komut gönderildi (~' + Math.round((d.estimated_duration_sec||tahmini)/60) + ' dk)</span>';
      setTimeout(() => { antYukle(); if (statusEl) statusEl.innerHTML = ''; }, (d.estimated_duration_sec||tahmini) * 1000 + 5000);
    }
  }).catch(e => {
    alert('Bağlantı hatası: ' + e);
    if (statusEl) statusEl.innerHTML = '';
  });
}

// ======================== CIHAZLARIM SEKMESI SONU ========================


// ======================== MALIYETLER SEKMESI ========================

let mltChartInstance = null;
let mltData = null;
let mltAcikGun = null;

async function mltDropdownDoldur() {
  const sel = document.getElementById('mlt-ay');
  if (!sel || sel.options.length > 1) return; // zaten dolu
  
  let raw;
  try {
    const r = await fetch('/api/osos_raw');
    raw = await r.json();
  } catch (e) {
    console.error('Mlt dropdown:', e);
    return;
  }
  
  const aylar = new Set();
  Object.values(raw).forEach(abone => {
    Object.keys(abone.veri || {}).forEach(t => aylar.add(t.slice(0,7)));
  });
  const aylarSorted = [...aylar].sort().reverse();
  
  let html = '<option value="2026">2026 Toplam</option>';
  aylarSorted.forEach(ay => {
    const [yil, mAy] = ay.split('-');
    const adi = TR_AYLAR[parseInt(mAy,10)-1] + ' ' + yil;
    html += '<option value="' + ay + '">' + adi + '</option>';
  });
  sel.innerHTML = html;
  if (aylarSorted.length > 0) sel.value = aylarSorted[0]; // en son ay
}

function mltYukle() {
  const ay = document.getElementById('mlt-ay').value;
  const url = '/api/maliyet/aksaray3' + (ay ? '?ay=' + ay : '');
  
  fetch(url).then(r => r.json()).then(d => {
    if (d.hata) {
      document.getElementById('mlt-toplam').textContent = '—';
      document.getElementById('mlt-toplam-sub').textContent = d.hata;
      document.getElementById('mlt-tablo').innerHTML = '<tr><td colspan="6" style="padding:20px;text-align:center;color:#94a3b8;">' + d.hata + '</td></tr>';
      return;
    }
    mltData = d;
    const fmtTRY = v => v ? Math.round(v).toLocaleString('tr-TR') + ' ₺' : '— ₺';
    const fmtNum = v => v ? Math.round(v).toLocaleString('tr-TR') : '—';
    
    document.getElementById('mlt-toplam').textContent = fmtTRY(d.toplam_maliyet_tl);
    document.getElementById('mlt-toplam-sub').textContent = d.gun_sayisi + ' gün · Ort: ' + fmtTRY(d.ort_gunluk_maliyet_tl) + '/gün';
    document.getElementById('mlt-tuketim').textContent = fmtNum(d.toplam_tuketim_kwh);
    document.getElementById('mlt-birim').textContent = d.ort_birim_fiyat_tl_kwh ? d.ort_birim_fiyat_tl_kwh.toFixed(4) : '—';
    document.getElementById('mlt-ortptf').textContent = fmtNum(d.ort_ptf_tl_mwh);
    
    // Son gunu otomatik ac
    const gunlerSorted = [...(d.gunler || [])].reverse();
    if (gunlerSorted.length > 0 && !mltAcikGun) {
      mltAcikGun = gunlerSorted[0].tarih;
    }
    mltTabloRender();
    mltChartRender();
  }).catch(e => {
    console.error('Maliyet yukleme hatasi:', e);
    document.getElementById('mlt-tablo').innerHTML = '<tr><td colspan="6" style="padding:20px;text-align:center;color:#ef4444;">Hata: ' + e + '</td></tr>';
  });
}

function mltTabloRender() {
  if (!mltData) return;
  const fmtTRY = v => v ? Math.round(v).toLocaleString('tr-TR') + ' ₺' : '— ₺';
  const fmtNum = v => v ? Math.round(v).toLocaleString('tr-TR') : '—';
  
  const gunler = [...(mltData.gunler || [])].reverse();
  let tbl = '';
  
  gunler.forEach(g => {
    const acik = (g.tarih === mltAcikGun);
    const dt = new Date(g.tarih);
    const dateStr = dt.toLocaleDateString('tr-TR', {day:'2-digit', month:'short', weekday:'short'});
    const bg = acik ? 'background:#dbeafe;' : '';
    const icon = acik ? '▼' : '▶';
    const iconColor = acik ? '#185fa5' : '#94a3b8';
    
    tbl += '<tr style="border-bottom:1px solid #e2e8f0; cursor:pointer; ' + bg + '" onclick="mltGunAc(\\\'' + g.tarih + '\\\')">';
    tbl += '<td style="padding:11px 8px; text-align:center; color:' + iconColor + '; font-size:11px;">' + icon + '</td>';
    tbl += '<td style="padding:11px 12px; color:#1e293b; font-weight:' + (acik?'600':'400') + ';">' + dateStr + '</td>';
    tbl += '<td style="padding:11px 12px; text-align:right; color:#1e293b;">' + fmtNum(g.toplam_tuketim_kwh) + '</td>';
    tbl += '<td style="padding:11px 12px; text-align:right; color:#64748b;">' + fmtNum(g.ort_ptf_tl_mwh) + '</td>';
    tbl += '<td style="padding:11px 12px; text-align:right; color:#1e293b;">' + g.ort_birim_fiyat_tl_kwh.toFixed(4) + '</td>';
    tbl += '<td style="padding:11px 12px; text-align:right; color:#993c1d; font-weight:600;">' + fmtTRY(g.toplam_maliyet_tl) + '</td>';
    tbl += '</tr>';
    
    if (acik && g.saatler) {
      tbl += '<tr style="background:#dbeafe;"><td colspan="6" style="padding:0 12px 12px 12px;">';
      tbl += '<div style="background:#fff; border:1px solid #cbd5e1; border-radius:6px; overflow:hidden;">';
      tbl += '<table style="width:100%; border-collapse:collapse; font-size:11px;">';
      tbl += '<thead><tr style="background:#f1f5f9;">';
      tbl += '<th style="padding:7px 10px; text-align:left; color:#64748b;">Saat</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#64748b;">Tüketim (kWh)</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#64748b;">PTF (TL/MWh)</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#64748b;">Enerji (₺/kWh)</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#64748b;">Tutar (₺)</th>';
      tbl += '</tr></thead><tbody>';
      
      g.saatler.forEach(s => {
        const enerji = (s.ptf/1000 + 602.51/1000) * 1.035;
        const pahalı = s.ptf > 2000;
        const renkPtf = pahalı ? '#993c1d' : '#64748b';
        const renkTutar = pahalı ? '#993c1d' : '#1e293b';
        tbl += '<tr style="border-top:1px solid #f1f5f9;">';
        tbl += '<td style="padding:5px 10px; color:#64748b;">' + String(s.saat).padStart(2,'0') + ':00</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#1e293b;">' + s.tuketim.toFixed(1) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:' + renkPtf + ';">' + Math.round(s.ptf) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#1e293b;">' + enerji.toFixed(4) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:' + renkTutar + '; font-weight:600;">' + Math.round(s.maliyet).toLocaleString('tr-TR') + '</td>';
        tbl += '</tr>';
      });
      
      tbl += '<tr style="border-top:1px solid #cbd5e1; background:#f8fafc;">';
      tbl += '<td style="padding:7px 10px; font-weight:600; color:#1e293b;">Toplam</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#1e293b;">' + fmtNum(g.toplam_tuketim_kwh) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#64748b;">' + fmtNum(g.ort_ptf_tl_mwh) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#1e293b;">' + g.ort_birim_fiyat_tl_kwh.toFixed(4) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#993c1d;">' + fmtTRY(g.toplam_maliyet_tl) + '</td>';
      tbl += '</tr>';
      tbl += '</tbody></table></div></td></tr>';
    }
  });
  
  // Genel toplam
  tbl += '<tr style="background:#f1f5f9; border-top:2px solid #cbd5e1;">';
  tbl += '<td></td>';
  tbl += '<td style="padding:12px; font-weight:600; color:#1e293b;">TOPLAM (' + mltData.gun_sayisi + ' gün)</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:#1e293b;">' + fmtNum(mltData.toplam_tuketim_kwh) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:#64748b;">' + fmtNum(mltData.ort_ptf_tl_mwh) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:#1e293b;">' + mltData.ort_birim_fiyat_tl_kwh.toFixed(4) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:#993c1d;">' + fmtTRY(mltData.toplam_maliyet_tl) + '</td>';
  tbl += '</tr>';
  
  document.getElementById('mlt-tablo').innerHTML = tbl;
}

function mltGunAc(tarih) {
  mltAcikGun = (mltAcikGun === tarih) ? null : tarih;
  mltTabloRender();
}

function mltChartRender() {
  if (!mltData || !window.Chart) return;
  const gunler = mltData.gunler || [];
  const labels = gunler.map(g => g.tarih.slice(-2));
  const data = gunler.map(g => Math.round(g.toplam_tuketim_kwh));
  
  const ctx = document.getElementById('mlt-chart');
  if (!ctx) return;
  if (mltChartInstance) mltChartInstance.destroy();
  
  mltChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'Tüketim',
        data: data,
        borderColor: OTO_G.cekisK,
        backgroundColor: 'rgba(232,72,85,0.10)',
        borderWidth: 2,
        pointRadius: 2.5,
        pointBackgroundColor: OTO_G.cekisK,
        pointHoverRadius: 5,
        tension: 0.3,
        fill: true
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => 'GÜN ' + items[0].label,
            label: (item) => item.parsed.y.toLocaleString('tr-TR') + ' kWh'
          }
        }
      },
      scales: otoEksen(''),
      interaction: { intersect: false, mode: 'index' }
    }
  });
}


// ======================== URETIM/TUKETIM (TY1+TY2) ========================

let utChartInstance = null;
let utData = null;
let utAcikGun = null;

function utYukle() {
  const ay = (new Date()).toISOString().slice(0, 7);
  const gun = (new Date()).toISOString().slice(0, 10);
  fetch('/api/uretim_tuketim?gun=' + gun + '&ay=' + ay).then(r => r.json()).then(d => {
    if (d.hata) return;
    utData = d;
    
    const a = d.aylik || {};
    const fmtNum = v => (v || v === 0) ? Math.round(v).toLocaleString('tr-TR') : '—';
    
    document.getElementById('ut-ay-uretim').textContent = fmtNum(a.toplam_uretim);
    document.getElementById('ut-ay-tuketim').textContent = fmtNum(a.toplam_tuketim);
    
    const netEl = document.getElementById('ut-ay-net');
    const netSub = document.getElementById('ut-ay-net-sub');
    if ((a.net || 0) >= 0) {
      netEl.textContent = '+' + fmtNum(a.net);
      netEl.style.color = '#0c447c';
      netSub.textContent = 'kWh fazla üretim';
    } else {
      netEl.textContent = fmtNum(a.net);
      netEl.style.color = '#993c1d';
      netSub.textContent = 'kWh eksik üretim';
    }
    
    const aylikGunler = a.gunler || [];
    if (aylikGunler.length > 0 && !utAcikGun) {
      utAcikGun = aylikGunler[aylikGunler.length - 1].tarih;
      utGunDetayYukle(utAcikGun);
    } else {
      utTabloRender();
      utChartRender();
    }
  }).catch(e => console.error('UT hata:', e));
}

function utGunDetayYukle(tarih) {
  fetch('/api/uretim_tuketim?gun=' + tarih + '&ay=' + tarih.slice(0,7)).then(r => r.json()).then(d => {
    if (d.gunluk && d.gunluk.saatlik) {
      const aylikGunler = (utData.aylik && utData.aylik.gunler) || [];
      const idx = aylikGunler.findIndex(g => g.tarih === tarih);
      if (idx >= 0) {
        aylikGunler[idx].saatlik = d.gunluk.saatlik;
      }
    }
    utTabloRender();
    utChartRender();
  });
}

function utGunAc(tarih) {
  if (utAcikGun === tarih) {
    utAcikGun = null;
    utTabloRender();
  } else {
    utAcikGun = tarih;
    const aylikGunler = (utData.aylik && utData.aylik.gunler) || [];
    const gun = aylikGunler.find(g => g.tarih === tarih);
    if (gun && !gun.saatlik) {
      utGunDetayYukle(tarih);
    } else {
      utTabloRender();
    }
  }
}

function utTabloRender() {
  if (!utData) return;
  const fmtNum = v => (v || v === 0) ? Math.round(v).toLocaleString('tr-TR') : '—';
  
  const aylikGunler = (utData.aylik && utData.aylik.gunler) || [];
  const gunler = [...aylikGunler].reverse();
  let tbl = '';
  
  gunler.forEach(g => {
    const acik = (g.tarih === utAcikGun);
    const dt = new Date(g.tarih);
    const dateStr = dt.toLocaleDateString('tr-TR', {day:'2-digit', month:'short', weekday:'short'});
    const bg = acik ? 'background:#dbeafe;' : '';
    const icon = acik ? '▼' : '▶';
    const iconColor = acik ? '#185fa5' : '#94a3b8';
    const netRenk = g.fazla_uretim ? '#0c447c' : '#993c1d';
    const netPrefix = g.fazla_uretim ? '+' : '';
    
    tbl += '<tr style="border-bottom:1px solid #e2e8f0; cursor:pointer; ' + bg + '" onclick="utGunAc(\\\'' + g.tarih + '\\\')">';
    tbl += '<td style="padding:11px 8px; text-align:center; color:' + iconColor + '; font-size:11px;">' + icon + '</td>';
    tbl += '<td style="padding:11px 12px; color:#1e293b; font-weight:' + (acik?'600':'400') + ';">' + dateStr + '</td>';
    tbl += '<td style="padding:11px 12px; text-align:right; color:#185fa5;">' + fmtNum(g.ty1_uretim) + '</td>';
    tbl += '<td style="padding:11px 12px; text-align:right; color:#185fa5;">' + fmtNum(g.ty2_uretim) + '</td>';
    tbl += '<td style="padding:11px 12px; text-align:right; color:#d85a30;">' + fmtNum(g.ty2_tuketim) + '</td>';
    tbl += '<td style="padding:11px 12px; text-align:right; color:' + netRenk + '; font-weight:600;">' + netPrefix + fmtNum(g.net) + '</td>';
    tbl += '</tr>';
    
    if (acik && g.saatlik) {
      tbl += '<tr style="background:#dbeafe;"><td colspan="6" style="padding:0 12px 12px 12px;">';
      tbl += '<div style="background:#fff; border:1px solid #cbd5e1; border-radius:6px; overflow:hidden;">';
      tbl += '<table style="width:100%; border-collapse:collapse; font-size:11px;">';
      tbl += '<thead><tr style="background:#f1f5f9;">';
      tbl += '<th style="padding:7px 10px; text-align:left; color:#64748b;">Saat</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#64748b;">TY1 Üret</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#64748b;">TY2 Üret</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#64748b;">Toplam Ü</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#64748b;">TY2 Tük</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#64748b;">NET</th>';
      tbl += '</tr></thead><tbody>';
      
      g.saatlik.forEach(s => {
        const renk = s.fazla_uretim ? '#0c447c' : '#993c1d';
        const pre = s.fazla_uretim ? '+' : '';
        tbl += '<tr style="border-top:1px solid #f1f5f9;">';
        tbl += '<td style="padding:5px 10px; color:#64748b;">' + String(s.saat).padStart(2,'0') + ':00</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#185fa5;">' + Math.round(s.ty1_uretim) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#185fa5;">' + Math.round(s.ty2_uretim) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#1e293b; font-weight:600;">' + Math.round(s.toplam_uretim) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#d85a30;">' + Math.round(s.ty2_tuketim) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:' + renk + '; font-weight:600;">' + pre + Math.round(s.net) + '</td>';
        tbl += '</tr>';
      });
      
      tbl += '<tr style="border-top:1px solid #cbd5e1; background:#f8fafc;">';
      tbl += '<td style="padding:7px 10px; font-weight:600; color:#1e293b;">Toplam</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#185fa5;">' + fmtNum(g.ty1_uretim) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#185fa5;">' + fmtNum(g.ty2_uretim) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#1e293b;">' + fmtNum(g.toplam_uretim) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#d85a30;">' + fmtNum(g.ty2_tuketim) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:' + netRenk + ';">' + netPrefix + fmtNum(g.net) + '</td>';
      tbl += '</tr>';
      tbl += '</tbody></table></div></td></tr>';
    }
  });
  
  // Genel toplam
  const a = utData.aylik || {};
  const totalNetRenk = (a.net || 0) >= 0 ? '#0c447c' : '#993c1d';
  const totalNetPrefix = (a.net || 0) >= 0 ? '+' : '';
  tbl += '<tr style="background:#f1f5f9; border-top:2px solid #cbd5e1;">';
  tbl += '<td></td>';
  tbl += '<td style="padding:12px; font-weight:600; color:#1e293b;">TOPLAM (' + (a.gun_sayisi || 0) + ' gün)</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:#185fa5;">' + fmtNum(aylikGunler.reduce((s,g)=>s+g.ty1_uretim,0)) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:#185fa5;">' + fmtNum(aylikGunler.reduce((s,g)=>s+g.ty2_uretim,0)) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:#d85a30;">' + fmtNum(a.toplam_tuketim) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:' + totalNetRenk + ';">' + totalNetPrefix + fmtNum(a.net) + '</td>';
  tbl += '</tr>';
  
  document.getElementById('ut-tablo').innerHTML = tbl;
}

function utChartRender() {
  if (!utData || !window.Chart) return;
  const aylikGunler = (utData.aylik && utData.aylik.gunler) || [];
  const labels = aylikGunler.map(g => g.tarih.slice(-2));
  const uretimData = aylikGunler.map(g => Math.round(g.toplam_uretim));
  const tuketimData = aylikGunler.map(g => Math.round(g.ty2_tuketim));
  
  const ctx = document.getElementById('ut-chart');
  if (!ctx) return;
  if (utChartInstance) utChartInstance.destroy();
  
  utChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        { label: 'Üretim', data: uretimData, borderColor: OTO_G.gunesK, backgroundColor: 'rgba(245,185,33,0.08)', borderWidth: 2, pointRadius: 2.5, pointBackgroundColor: OTO_G.gunesK, pointHoverRadius: 5, tension: 0.3, fill: true },
        { label: 'Tüketim', data: tuketimData, borderColor: OTO_G.cekisK, backgroundColor: 'rgba(232,72,85,0.05)', borderWidth: 2, pointRadius: 2.5, pointBackgroundColor: OTO_G.cekisK, pointHoverRadius: 5, tension: 0.3, fill: false }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => 'GÜN ' + items[0].label,
            label: (item) => item.dataset.label + ': ' + item.parsed.y.toLocaleString('tr-TR') + ' kWh'
          }
        }
      },
      scales: otoEksen(''),
      interaction: { intersect: false, mode: 'index' }
    }
  });
}

// ======================== URETIM/TUKETIM SONU ========================


// ======================== VERI SEKMESI (3 ABONE) ========================

const TR_AYLAR = ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'];

let veriChartInstance = null;
let veriData = null;
let veriAcikGun = null;
let veriRaw = null; // GitHub'dan ham JSON

async function veriRawYukle() {
  if (veriRaw) return veriRaw;
  try {
    const r = await fetch('/api/osos_raw');
    veriRaw = await r.json();
    return veriRaw;
  } catch (e) {
    console.error('Veri yuklenemedi:', e);
    return {};
  }
}

async function veriDropdownDoldur() {
  const sel = document.getElementById('veri-ay');
  if (!sel) return;
  const raw = await veriRawYukle();
  
  // Tum aylari topla
  const aylar = new Set();
  Object.values(raw).forEach(abone => {
    Object.keys(abone.veri || {}).forEach(t => aylar.add(t.slice(0,7)));
  });
  const aylarSorted = [...aylar].sort().reverse();
  
  let html = '<option value="2026">2026 Toplam</option>';
  aylarSorted.forEach(ay => {
    const [yil, mAy] = ay.split('-');
    const adi = TR_AYLAR[parseInt(mAy,10)-1] + ' ' + yil;
    html += '<option value="' + ay + '">' + adi + '</option>';
  });
  sel.innerHTML = html;
  // Varsayilan: en son ay
  if (aylarSorted.length > 0) sel.value = aylarSorted[0];
}

async function veriYukle() {
  const sel = document.getElementById('veri-ay');
  const secim = sel ? sel.value : '';
  const raw = await veriRawYukle();
  
  // 3 abone icin gunluk topla
  const gunluk = {};  // tarih -> {ty1u, ty2u, ty2t, aks3t}
  
  Object.entries(raw).forEach(([key, abone]) => {
    const veri = abone.veri || {};
    Object.entries(veri).forEach(([tarih, saatler]) => {
      // Filtre
      if (secim === '2026') {
        if (!tarih.startsWith('2026')) return;
      } else if (secim) {
        if (!tarih.startsWith(secim)) return;
      }
      
      if (!gunluk[tarih]) gunluk[tarih] = { ty1u:0, ty2u:0, ty2t:0, aks3t:0, saatler: {} };
      
      Object.entries(saatler).forEach(([saat, v]) => {
        if (!gunluk[tarih].saatler[saat]) gunluk[tarih].saatler[saat] = { ty1u:0, ty2u:0, ty2t:0, aks3t:0 };
        
        if (key === 'tekyildiz_1') {
          gunluk[tarih].ty1u += v.veris || 0;
          gunluk[tarih].saatler[saat].ty1u += v.veris || 0;
        } else if (key === 'tekyildiz_2') {
          gunluk[tarih].ty2u += v.veris || 0;
          gunluk[tarih].ty2t += v.cekis || 0;
          gunluk[tarih].saatler[saat].ty2u += v.veris || 0;
          gunluk[tarih].saatler[saat].ty2t += v.cekis || 0;
        } else if (key === 'aksaray_3') {
          gunluk[tarih].aks3t += v.cekis || 0;
          gunluk[tarih].saatler[saat].aks3t += v.cekis || 0;
        }
      });
    });
  });
  
  // Toplamlar
  const tarihlerSorted = Object.keys(gunluk).sort();
  let topUretim = 0, topTuketim = 0, topMahsup = 0, topAks3 = 0;
  tarihlerSorted.forEach(t => {
    const g = gunluk[t];
    topUretim += g.ty1u + g.ty2u;
    topTuketim += g.ty2t + g.aks3t;
    topMahsup += (g.ty1u + g.ty2u) - g.ty2t;
    topAks3 += g.aks3t;
  });
  
  veriData = { gunler: tarihlerSorted.map(t => ({tarih:t, ...gunluk[t]})), top: {topUretim, topTuketim, topMahsup, topAks3} };
  
  // KPI
  const fmtNum = v => Math.round(v).toLocaleString('tr-TR');
  document.getElementById('veri-uretim').textContent = fmtNum(topUretim);
  document.getElementById('veri-tuketim').textContent = fmtNum(topTuketim);
  
  const mahsupEl = document.getElementById('veri-mahsup');
  if (topMahsup >= 0) {
    mahsupEl.textContent = '+' + fmtNum(topMahsup);
    mahsupEl.style.color = '#0c447c';
  } else {
    mahsupEl.textContent = fmtNum(topMahsup);
    mahsupEl.style.color = '#993c1d';
  }
  document.getElementById('veri-aks3').textContent = fmtNum(topAks3);
  
  // Son gun otomatik ac
  if (tarihlerSorted.length > 0 && !veriAcikGun) {
    veriAcikGun = tarihlerSorted[tarihlerSorted.length - 1];
  }
  
  veriTabloRender();
  veriChartRender();
}

function veriGunAc(tarih) {
  veriAcikGun = (veriAcikGun === tarih) ? null : tarih;
  veriTabloRender();
}

function veriTabloRender() {
  if (!veriData) return;
  const fmtNum = v => Math.round(v || 0).toLocaleString('tr-TR');
  
  const gunler = [...veriData.gunler].reverse();
  let tbl = '';
  
  gunler.forEach(g => {
    const acik = (g.tarih === veriAcikGun);
    const dt = new Date(g.tarih);
    const dateStr = dt.toLocaleDateString('tr-TR', {day:'2-digit', month:'short', weekday:'short'});
    const bg = acik ? 'background:#dbeafe;' : '';
    const icon = acik ? '▼' : '▶';
    const iconColor = acik ? '#185fa5' : '#94a3b8';
    const mahsup = (g.ty1u + g.ty2u) - g.ty2t;
    const mahsupRenk = mahsup >= 0 ? '#0c447c' : '#993c1d';
    const mahsupPrefix = mahsup >= 0 ? '+' : '';
    
    tbl += '<tr style="border-bottom:1px solid #e2e8f0; cursor:pointer; ' + bg + '" onclick="veriGunAc(\\\'' + g.tarih + '\\\')">';
    tbl += '<td style="padding:11px 8px; text-align:center; color:' + iconColor + '; font-size:11px;">' + icon + '</td>';
    tbl += '<td style="padding:11px 12px; color:#1e293b; font-weight:' + (acik?'600':'400') + ';">' + dateStr + '</td>';
    tbl += '<td style="padding:11px 8px; text-align:right; color:#185fa5;">' + fmtNum(g.ty1u) + '</td>';
    tbl += '<td style="padding:11px 8px; text-align:right; color:#185fa5;">' + fmtNum(g.ty2u) + '</td>';
    tbl += '<td style="padding:11px 8px; text-align:right; color:#d85a30;">' + fmtNum(g.ty2t) + '</td>';
    tbl += '<td style="padding:11px 8px; text-align:right; color:#d85a30;">' + fmtNum(g.aks3t) + '</td>';
    tbl += '<td style="padding:11px 8px; text-align:right; color:' + mahsupRenk + '; font-weight:600;">' + mahsupPrefix + fmtNum(mahsup) + '</td>';
    tbl += '</tr>';
    
    if (acik && g.saatler) {
      tbl += '<tr style="background:#dbeafe;"><td colspan="7" style="padding:0 12px 12px 12px;">';
      tbl += '<div style="background:#fff; border:1px solid #cbd5e1; border-radius:6px; overflow:hidden;">';
      tbl += '<table style="width:100%; border-collapse:collapse; font-size:11px;">';
      tbl += '<thead><tr style="background:#f1f5f9;">';
      tbl += '<th style="padding:7px 10px; text-align:left; color:#64748b;">Saat</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#185fa5;">TY1 Üret</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#185fa5;">TY2 Üret</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#d85a30;">TY2 Tük</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#d85a30;">AKS3 Tük</th>';
      tbl += '<th style="padding:7px 10px; text-align:right; color:#64748b;">Mahsup</th>';
      tbl += '</tr></thead><tbody>';
      
      const saatler = Object.keys(g.saatler).sort((a,b)=>parseInt(a)-parseInt(b));
      saatler.forEach(s => {
        const v = g.saatler[s];
        const m = (v.ty1u + v.ty2u) - v.ty2t;
        const mr = m >= 0 ? '#0c447c' : '#993c1d';
        const mp = m >= 0 ? '+' : '';
        tbl += '<tr style="border-top:1px solid #f1f5f9;">';
        tbl += '<td style="padding:5px 10px; color:#64748b;">' + s + ':00</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#185fa5;">' + Math.round(v.ty1u) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#185fa5;">' + Math.round(v.ty2u) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#d85a30;">' + Math.round(v.ty2t) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#d85a30;">' + Math.round(v.aks3t) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:' + mr + '; font-weight:600;">' + mp + Math.round(m) + '</td>';
        tbl += '</tr>';
      });
      
      tbl += '<tr style="border-top:1px solid #cbd5e1; background:#f8fafc;">';
      tbl += '<td style="padding:7px 10px; font-weight:600; color:#1e293b;">Toplam</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#185fa5;">' + fmtNum(g.ty1u) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#185fa5;">' + fmtNum(g.ty2u) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#d85a30;">' + fmtNum(g.ty2t) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:#d85a30;">' + fmtNum(g.aks3t) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:600; color:' + mahsupRenk + ';">' + mahsupPrefix + fmtNum(mahsup) + '</td>';
      tbl += '</tr>';
      tbl += '</tbody></table></div></td></tr>';
    }
  });
  
  // Genel toplam
  const t = veriData.top;
  const tMahsupRenk = t.topMahsup >= 0 ? '#0c447c' : '#993c1d';
  const tMahsupPrefix = t.topMahsup >= 0 ? '+' : '';
  tbl += '<tr style="background:#f1f5f9; border-top:2px solid #cbd5e1;">';
  tbl += '<td></td>';
  tbl += '<td style="padding:12px; font-weight:600; color:#1e293b;">TOPLAM (' + veriData.gunler.length + ' gün)</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:#185fa5;">' + fmtNum(veriData.gunler.reduce((s,g)=>s+g.ty1u,0)) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:#185fa5;">' + fmtNum(veriData.gunler.reduce((s,g)=>s+g.ty2u,0)) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:#d85a30;">' + fmtNum(veriData.gunler.reduce((s,g)=>s+g.ty2t,0)) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:#d85a30;">' + fmtNum(t.topAks3) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:600; color:' + tMahsupRenk + ';">' + tMahsupPrefix + fmtNum(t.topMahsup) + '</td>';
  tbl += '</tr>';
  
  document.getElementById('veri-tablo').innerHTML = tbl;
}

function veriChartRender() {
  if (!veriData || !window.Chart) return;
  const gunler = veriData.gunler;
  const labels = gunler.map(g => g.tarih.slice(-2));
  const uretim = gunler.map(g => Math.round(g.ty1u + g.ty2u));
  const tuketim = gunler.map(g => Math.round(g.ty2t + g.aks3t));
  
  const ctx = document.getElementById('veri-chart');
  if (!ctx) return;
  if (veriChartInstance) veriChartInstance.destroy();
  
  veriChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        { label: 'Üretim', data: uretim, borderColor: OTO_G.gunesK, backgroundColor: 'rgba(245,185,33,0.08)', borderWidth: 2, pointRadius: 2.5, pointBackgroundColor: OTO_G.gunesK, pointHoverRadius: 5, tension: 0.3, fill: true },
        { label: 'Tüketim', data: tuketim, borderColor: OTO_G.cekisK, backgroundColor: 'rgba(232,72,85,0.05)', borderWidth: 2, pointRadius: 2.5, pointBackgroundColor: OTO_G.cekisK, pointHoverRadius: 5, tension: 0.3, fill: false }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => 'GÜN ' + items[0].label,
            label: (item) => item.dataset.label + ': ' + item.parsed.y.toLocaleString('tr-TR') + ' kWh'
          }
        }
      },
      scales: otoEksen(''),
      interaction: { intersect: false, mode: 'index' }
    }
  });
}

// Veri sekmesi acildiginda yukle
(function() {
  const origSekme = window.sekme;
  window.sekme = function(ad, btn) {
    if (origSekme) origSekme(ad, btn);
    if (ad === 'veri') {
      veriDropdownDoldur().then(() => veriYukle());
    }
  };
})();

// ======================== VERI SEKMESI SONU ========================

// ====================== MAHSUPLAŞMA SEKMESI ======================
// 2025 baz tüketim (bedelli limit hesabı için)
const MHS_2025_DAHIL = {
  TY1: 4549,
  TY2: 0,
  AKS3_HAZ_ARA: 1448407.80
};
const MHS_2025_TOPLAM = MHS_2025_DAHIL.TY1 + MHS_2025_DAHIL.TY2 + MHS_2025_DAHIL.AKS3_HAZ_ARA;
const MHS_BEDELLI_LIMIT = MHS_2025_TOPLAM * 2;

// TY2 üretim varken tüketim (mining - aylık manuel)
const MHS_TY2_MINING_AYLIK = {
  '2026-03': 36038.52,
  '2026-04': 53609.85
};

// Manuel AKS3 mahsuplasma verileri (2026 Ocak-Nisan, aylik mod)
// Bu aylarda mahsuplasma sirasi: AKS3 once -> T2 -> T1 -> Bedelli (basamakli)
// Mahsup_A3 manuel verilen deger, Tuketim_A3 ise mevcut osos verisinden gelir
const MHS_MANUEL_AKS3 = {
  '2026-01': 29373.75,
  '2026-02': 63949.58,
  '2026-03': 89689.95,
  '2026-04': 191206.98
};

const MHS_AY_ISIM = ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'];

let mhsData = null;       // hesaplanmış data
let mhsAcikAy = null;     // hangi ay acik
let mhsAcikGun = null;    // hangi gun acik
let mhsAboneDetay = false;  // T1/T2/A3 detay aç/kapa

function mhsFmt(v) {
  return Math.round(v || 0).toLocaleString('tr-TR');
}

function mhsHesaplaSaatlik(uretim, tuketim) {
  const mahsup = Math.min(uretim, tuketim);
  const bedelli = Math.max(0, uretim - tuketim);
  return { mahsup, bedelli };
}

function mahsupYukle() {
  // Her sekme açılışında veriyi yenile (cache yok)
  return mahsupYukleAsync();
}

async function mahsupYukleAsync() {
  try {
    // Cache busting parametresi ekle
    const r = await fetch('/api/osos_raw?_=' + Date.now());
    if (!r.ok) {
      document.getElementById('mhs-tablo').innerHTML = '<tr><td colspan="6" style="padding:20px; text-align:center; color:#94a3b8;">Veri yok</td></tr>';
      return;
    }
    const raw = await r.json();
    
    // 3 aboneyi ayrı tut - her saatte T1, T2, A3 verileri ayrı
    const aylar = {};
    
    const aboneKisalt = {
      'tekyildiz_1': 'T1',
      'tekyildiz_2': 'T2',
      'aksaray_3': 'A3',
    };
    const aboneTip = {
      'tekyildiz_1': { uretim: true, tuketim: true },
      'tekyildiz_2': { uretim: true, tuketim: true },
      'aksaray_3': { uretim: false, tuketim: true },
    };
    
    function bosVeri() {
      return {
        uretim: { T1: 0, T2: 0, A3: 0, TPL: 0 },
        tuketim: { T1: 0, T2: 0, A3: 0, TPL: 0 },
      };
    }
    
    Object.entries(raw).forEach(([key, abone]) => {
      if (!aboneTip[key] || !abone.veri) return;
      const tipler = aboneTip[key];
      const k = aboneKisalt[key];
      
      Object.entries(abone.veri).forEach(([gun, saatler]) => {
        if (!gun.startsWith('2026')) return;
        const ay = gun.substring(0, 7);
        
        if (!aylar[ay]) aylar[ay] = { ...bosVeri(), gunler: {}, miningAylik: 0 };
        if (!aylar[ay].gunler[gun]) aylar[ay].gunler[gun] = { ...bosVeri(), saatler: {} };
        
        Object.entries(saatler).forEach(([saatRaw, v]) => {
          const saat = saatRaw.substring(0, 2);
          const cekis = (v.cekis !== undefined ? v.cekis : (v.cekis_kwh || 0));
          const veris = (v.veris !== undefined ? v.veris : (v.veris_kwh || 0));
          
          if (!aylar[ay].gunler[gun].saatler[saat]) {
            aylar[ay].gunler[gun].saatler[saat] = bosVeri();
          }
          
          const S = aylar[ay].gunler[gun].saatler[saat];
          if (tipler.uretim) {
            S.uretim[k] += veris;
            S.uretim.TPL += veris;
          }
          if (tipler.tuketim) {
            S.tuketim[k] += cekis;
            S.tuketim.TPL += cekis;
          }
        });
      });
    });
    
    // TY2 Mining manuel (hesaplara KATILMAZ, sadece referans)
    Object.entries(MHS_TY2_MINING_AYLIK).forEach(([ay, v]) => {
      if (!aylar[ay]) aylar[ay] = { ...bosVeri(), gunler: {}, miningAylik: 0 };
      aylar[ay].miningAylik = v;
    });
    
    // MAHSUPLASMA HESAPLA:
    // - Ocak-Nisan 2026 → AYLIK MANTIK
    // - Mayıs 2026+ → SAATLİK MANTIK
    const SAATLIK_BASLANGIC = '2026-05';
    
    // BASAMAKLI MAHSUPLASMA:
    // - Tuketimleri buyukten kucuge sirala
    // - Sirayla uretimden dus
    // - mahsup{T1,T2,A3,TPL} ve sonra{T1,T2,A3,TPL} ve bedelli dondurur
    function basamakliMahsup(tuketim, uretimTpl) {
      // Tuketim siralamasi - buyukten kucuge
      const sira = [
        { abone: 'T1', tuk: tuketim.T1 || 0 },
        { abone: 'T2', tuk: tuketim.T2 || 0 },
        { abone: 'A3', tuk: tuketim.A3 || 0 },
      ];
      sira.sort(function(a, b) { return b.tuk - a.tuk; });

      const mahsup = { T1: 0, T2: 0, A3: 0, TPL: 0 };
      const sonra  = { T1: 0, T2: 0, A3: 0, TPL: 0 };
      let kalanU = uretimTpl || 0;

      sira.forEach(function(item) {
        if (kalanU >= item.tuk) {
          mahsup[item.abone] = item.tuk;
          sonra[item.abone] = 0;
          kalanU -= item.tuk;
        } else {
          mahsup[item.abone] = kalanU;
          sonra[item.abone] = item.tuk - kalanU;
          kalanU = 0;
        }
      });

      mahsup.TPL = mahsup.T1 + mahsup.T2 + mahsup.A3;
      sonra.TPL  = sonra.T1  + sonra.T2  + sonra.A3;
      const bedelli = kalanU;
      return { mahsup: mahsup, sonra: sonra, bedelli: bedelli };
    }

    // KAYNAK TAKIPLI HAVUZ MAHSUBU (bu ay modeli)
    //   Uretimi buyukten kucuge sirala (U1>U2 ise once U1)
    //   Her ureticiden, tuketimleri buyukten kucuge mahsup et
    //   Uretici bitince sonrakine gec. Artan = bedelli
    //   Donen: kaynak matrisi (hangi GES'ten hangi tukeciye + bedelli)
    function havuzMahsupKaynakli(uretim, tuketim) {
      // uretim: {T1, T2} (GES uretimleri), tuketim: {T1, T2, A3}
      // Ureticiler buyukten kucuge
      const ureticiler = [
        { ges: 'T1', kalan: uretim.T1 || 0 },
        { ges: 'T2', kalan: uretim.T2 || 0 },
      ].sort((a, b) => b.kalan - a.kalan);

      // Tuketiciler buyukten kucuge (her seferinde guncel kalan tuketimle)
      const tuk = { T1: tuketim.T1 || 0, T2: tuketim.T2 || 0, A3: tuketim.A3 || 0 };

      // kaynak[ges][tukeci] = mahsup miktari ; kaynak[ges].bedelli = satilan
      const kaynak = {
        T1: { T1: 0, T2: 0, A3: 0, bedelli: 0 },
        T2: { T1: 0, T2: 0, A3: 0, bedelli: 0 },
      };
      // toplam abone bazli mahsup (eski uyumluluk)
      const mahsup = { T1: 0, T2: 0, A3: 0, TPL: 0 };

      ureticiler.forEach(function(u) {
        if (u.kalan <= 0) return;
        // SABIT ONCELIK: once T2 tuketimi, kalan A3, en son T1 (uretim once T2'yi karsilar)
        const sira = [
          { ab: 'T2', tuk: tuk.T2 },
          { ab: 'A3', tuk: tuk.A3 },
          { ab: 'T1', tuk: tuk.T1 },
        ];

        sira.forEach(function(t) {
          if (u.kalan <= 0 || tuk[t.ab] <= 0) return;
          const mhs = Math.min(u.kalan, tuk[t.ab]);
          kaynak[u.ges][t.ab] += mhs;
          mahsup[t.ab] += mhs;
          u.kalan -= mhs;
          tuk[t.ab] -= mhs;
        });
        // Bu ureticiden artan = bedelli
        if (u.kalan > 0) {
          kaynak[u.ges].bedelli += u.kalan;
          u.kalan = 0;
        }
      });

      mahsup.TPL = mahsup.T1 + mahsup.T2 + mahsup.A3;
      const sonra = {
        T1: tuk.T1, T2: tuk.T2, A3: tuk.A3,
        TPL: tuk.T1 + tuk.T2 + tuk.A3
      };
      const bedelli = kaynak.T1.bedelli + kaynak.T2.bedelli;
      return { mahsup: mahsup, sonra: sonra, bedelli: bedelli, kaynak: kaynak };
    }

    // MANUEL OVERRIDE: AKS3 once (manuel deger) -> T2 -> T1 -> Bedelli
    // Mahsup_A3 disardan veriliyor, geri kalan tuketim basamakli inecek
    function manuelAks3Mahsup(tuketim, uretimTpl, manuelMahsupA3) {
      const mahsup = { T1: 0, T2: 0, A3: 0, TPL: 0 };
      const sonra  = { T1: 0, T2: 0, A3: 0, TPL: 0 };
      let kalanU = uretimTpl || 0;

      // 1. AKS3 manuel mahsubu
      mahsup.A3 = Math.min(manuelMahsupA3, tuketim.A3 || 0);
      sonra.A3 = (tuketim.A3 || 0) - mahsup.A3;
      kalanU -= mahsup.A3;

      // 2. T2 (kalan uretim varsa)
      if (kalanU > 0 && (tuketim.T2 || 0) > 0) {
        mahsup.T2 = Math.min(kalanU, tuketim.T2);
        sonra.T2 = tuketim.T2 - mahsup.T2;
        kalanU -= mahsup.T2;
      } else {
        sonra.T2 = tuketim.T2 || 0;
      }

      // 3. T1 (kalan uretim varsa)
      if (kalanU > 0 && (tuketim.T1 || 0) > 0) {
        mahsup.T1 = Math.min(kalanU, tuketim.T1);
        sonra.T1 = tuketim.T1 - mahsup.T1;
        kalanU -= mahsup.T1;
      } else {
        sonra.T1 = tuketim.T1 || 0;
      }

      mahsup.TPL = mahsup.T1 + mahsup.T2 + mahsup.A3;
      sonra.TPL  = sonra.T1  + sonra.T2  + sonra.A3;
      const bedelli = Math.max(0, kalanU);
      return { mahsup: mahsup, sonra: sonra, bedelli: bedelli };
    }
    
    Object.keys(aylar).forEach(ay => {
      const A = aylar[ay];
      const saatlikMod = (ay >= SAATLIK_BASLANGIC);
      
      // Ay toplamları sıfırla
      A.uretim = { T1: 0, T2: 0, A3: 0, TPL: 0 };
      A.tuketim = { T1: 0, T2: 0, A3: 0, TPL: 0 };
      
      Object.keys(A.gunler).forEach(gun => {
        const G = A.gunler[gun];
        
        // Gün toplamları sıfırla
        G.uretim = { T1: 0, T2: 0, A3: 0, TPL: 0 };
        G.tuketim = { T1: 0, T2: 0, A3: 0, TPL: 0 };
        let gM = 0, gB = 0;
        
        Object.keys(G.saatler).forEach(saat => {
          const S = G.saatler[saat];
          
          // Saatte gün toplamına ekle
          ['T1', 'T2', 'A3', 'TPL'].forEach(k => {
            G.uretim[k] += S.uretim[k];
            G.tuketim[k] += S.tuketim[k];
          });
          
          if (saatlikMod) {
            // SAATLİK kaynak takipli havuz mahsubu (bu ay modeli)
            // Uretim once T2 tuketimini karsilar, kalan A3'e, en son T1; artan bedelli
            const r = havuzMahsupKaynakli(S.uretim, S.tuketim);
            S.mahsup_dagilim = r.mahsup;  // {T1,T2,A3,TPL}
            S.sonra = r.sonra;            // {T1,T2,A3,TPL}
            S.mahsup = r.mahsup.TPL;       // tek sayi (eski kullanim icin)
            S.bedelli = r.bedelli;
            S.kaynak = r.kaynak;           // {T1:{T1,T2,A3,bedelli}, T2:{...}}

            gM += S.mahsup;
            gB += S.bedelli;
          } else {
            // Aylık modda saat seviyesinde hesap gösterilmez
            S.mahsup = 0;
            S.bedelli = 0;
            S.sonra = { T1: 0, T2: 0, A3: 0, TPL: 0 };
            S.mahsup_dagilim = { T1: 0, T2: 0, A3: 0, TPL: 0 };
            S.kaynak = { T1:{T1:0,T2:0,A3:0,bedelli:0}, T2:{T1:0,T2:0,A3:0,bedelli:0} };
          }
        });
        
        // Gün toplamlarını ay'a ekle
        ['T1', 'T2', 'A3', 'TPL'].forEach(k => {
          A.uretim[k] += G.uretim[k];
          A.tuketim[k] += G.tuketim[k];
        });
        
        if (saatlikMod) {
          // Saatlik mod: gün = saatlerin toplamı (mahsup ve bedelli)
          G.mahsup = gM;
          G.bedelli = gB;
          // Gun seviyesindeki sonra/mahsup_dagilim icin: saatlerin abone bazinda toplami
          const gMahsupDag = { T1: 0, T2: 0, A3: 0, TPL: 0 };
          const gSonraDag  = { T1: 0, T2: 0, A3: 0, TPL: 0 };
          Object.values(G.saatler).forEach(function(S) {
            ['T1', 'T2', 'A3', 'TPL'].forEach(function(k) {
              gMahsupDag[k] += (S.mahsup_dagilim && S.mahsup_dagilim[k]) || 0;
              gSonraDag[k]  += (S.sonra && S.sonra[k]) || 0;
            });
          });
          G.mahsup_dagilim = gMahsupDag;
          G.sonra = gSonraDag;
        } else {
          // Aylık mod: gün seviyesinde mahsup hesabi yok (sadece ay sonu yapilir)
          G.mahsup_dagilim = { T1: 0, T2: 0, A3: 0, TPL: 0 };
          G.sonra = { T1: 0, T2: 0, A3: 0, TPL: 0 };
          G.mahsup = 0;
          G.bedelli = 0;
        }
      });
      
      if (saatlikMod) {
        // Saatlik mod: ay = günlerin toplamı
        let m = 0, b = 0;
        const aMahsupDag = { T1: 0, T2: 0, A3: 0, TPL: 0 };
        const aSonraDag  = { T1: 0, T2: 0, A3: 0, TPL: 0 };
        Object.values(A.gunler).forEach(function(G) {
          m += G.mahsup;
          b += G.bedelli;
          ['T1', 'T2', 'A3', 'TPL'].forEach(function(k) {
            aMahsupDag[k] += (G.mahsup_dagilim && G.mahsup_dagilim[k]) || 0;
            aSonraDag[k]  += (G.sonra && G.sonra[k]) || 0;
          });
        });
        A.mahsup = m;
        A.bedelli = b;
        A.mahsup_dagilim = aMahsupDag;
        A.sonra = aSonraDag;
      } else {
        // Aylık mod: ay sonu basamakli mantik
        // Manuel AKS3 override var mi kontrol et
        if (MHS_MANUEL_AKS3[ay] !== undefined) {
          const r = manuelAks3Mahsup(A.tuketim, A.uretim.TPL, MHS_MANUEL_AKS3[ay]);
          A.mahsup_dagilim = r.mahsup;
          A.sonra = r.sonra;
          A.mahsup = r.mahsup.TPL;
          A.bedelli = r.bedelli;
        } else {
          const r = basamakliMahsup(A.tuketim, A.uretim.TPL);
          A.mahsup_dagilim = r.mahsup;
          A.sonra = r.sonra;
          A.mahsup = r.mahsup.TPL;
          A.bedelli = r.bedelli;
        }
      }
    });
    
    mhsData = aylar;
    mhsTabloRender();
    mhsKpiGuncelle();
    
  } catch (e) {
    console.error('Mahsuplaşma hatasi:', e);
    document.getElementById('mhs-tablo').innerHTML = '<tr><td colspan="6" style="padding:20px; text-align:center; color:#dc2626;">Hata: ' + e.message + '</td></tr>';
  }
}

function mhsAyAc(ay) {
  mhsAcikAy = (mhsAcikAy === ay) ? null : ay;
  mhsAcikGun = null;  // ay degisirse gun kapansin
  mhsTabloRender();
}

function mhsGunAc(gun) {
  mhsAcikGun = (mhsAcikGun === gun) ? null : gun;
  mhsTabloRender();
}

function mhsAboneToggle() {
  mhsAboneDetay = !mhsAboneDetay;
  mhsTabloRender();
}

function mhsKpiGuncelle() {
  if (!mhsData) return;
  let topU = 0, topT = 0, topM = 0, topB = 0;
  Object.values(mhsData).forEach(ay => {
    topU += ay.uretim.TPL;
    topT += ay.tuketim.TPL;
    topM += ay.mahsup;
    topB += ay.bedelli;
  });
  
  document.getElementById('mhs-uretim').textContent = mhsFmt(topU);
  document.getElementById('mhs-tuketim').textContent = mhsFmt(topT);
  document.getElementById('mhs-mahsup').textContent = mhsFmt(topM);
  document.getElementById('mhs-bedelli').textContent = mhsFmt(topB);
  
  const pct = Math.min(100, (topB / MHS_BEDELLI_LIMIT) * 100);
  document.getElementById('mhs-progress').style.width = pct.toFixed(2) + '%';
  document.getElementById('mhs-bedelli-toplam').textContent = mhsFmt(topB);
  document.getElementById('mhs-limit-toplam').textContent = mhsFmt(MHS_BEDELLI_LIMIT);
  document.getElementById('mhs-limit-deger').textContent = mhsFmt(MHS_BEDELLI_LIMIT);
  document.getElementById('mhs-yuzde').textContent = '%' + pct.toFixed(1);
}

function mhsTabloRender() {
  if (!mhsData) return;
  
  // colspan: 1 (icon) + 1 (ad) + 4 (üretim) + 4 (tüketim) + 1 (mahsup) + 4 (sonra) + 1 (bedelli) + 1 (durum) = 17
  const COLSPAN = 17;
  
  // Hücre üretici fonksiyonlar
  function tdNum(v, color, bg, weight, fontSize) {
    const style = 'padding:6px 6px; text-align:right; color:' + color + 
                  '; background:' + (bg || 'transparent') +
                  '; font-weight:' + (weight || '400') +
                  '; font-size:' + (fontSize || '11px') + ';';
    const val = (v === null || v === undefined || v === 0) ? '—' : Math.round(v).toLocaleString('tr-TR');
    return '<td style="' + style + '">' + val + '</td>';
  }
  
  function tdNumZero(v, color, bg, weight, fontSize) {
    // 0 da gösterir (üretim/tüketim toplamı 0 olabilir ama '—' yazsın)
    const style = 'padding:6px 6px; text-align:right; color:' + color + 
                  '; background:' + (bg || 'transparent') +
                  '; font-weight:' + (weight || '400') +
                  '; font-size:' + (fontSize || '11px') + ';';
    const val = (v === null || v === undefined) ? '—' : (v === 0 ? '—' : Math.round(v).toLocaleString('tr-TR'));
    return '<td style="' + style + '">' + val + '</td>';
  }
  
  function renderSatir(opts) {
    const { 
      uretim, tuketim, mahsup, sonra, bedelli, 
      indent, bg, textColor, weight, fontSize, level,
      ayText, onclick, icon
    } = opts;
    
    const secili = (textColor === '#fff');
    
    const uColor = secili ? '#fff' : '#185fa5';
    const tColor = secili ? '#fff' : '#dc2626';
    const mColor = secili ? '#fff' : '#7c3aed';
    const sColor = secili ? '#fff' : '#ea580c';
    const bColor = secili ? '#fff' : (bedelli > 0 ? '#16a34a' : '#cbd5e1');
    const a3Color = secili ? 'rgba(255,255,255,0.45)' : '#cbd5e1';
    
    const uBgL = secili ? bg : '#f0f9ff';
    const uBgT = secili ? bg : '#dbeafe';
    const tBgL = secili ? bg : '#fef2f2';
    const tBgT = secili ? bg : '#fee2e2';
    const sBgL = secili ? bg : '#fff7ed';
    const sBgT = secili ? bg : '#fed7aa';
    const bdL = 'border-left:1px solid ' + (secili ? 'rgba(255,255,255,0.15)' : '#e2e8f0') + ';';
    const bdLStrong = 'border-left:2px solid ' + (secili ? 'rgba(255,255,255,0.3)' : '#cbd5e1') + ';';
    
    const w = weight || '400';
    const fs = fontSize || '11px';
    const indentPx = indent || 0;
    
    function td(v, color, bgC, weight2, leftBorder) {
      const borderStyle = leftBorder === 'strong' ? bdLStrong : (leftBorder ? bdL : '');
      const style = 'padding:8px 10px; text-align:right; color:' + color + 
                    '; background:' + bgC +
                    '; font-weight:' + (weight2 || w) +
                    '; font-size:' + fs + ';' +
                    borderStyle;
      const val = (v === null || v === undefined || v === 0) ? '<span style="opacity:0.4">—</span>' : Math.round(v).toLocaleString('tr-TR');
      return '<td style="' + style + '">' + val + '</td>';
    }
    
    let s = '<tr style="border-bottom:1px solid #f1f5f9;' + 
            (bg ? 'background:' + bg + ';' : '') + 
            (onclick ? 'cursor:pointer; transition:background 0.15s;' : '') +
            '"' + (onclick ? ' onclick="' + onclick + '"' : '') + 
            (onclick && !secili ? ' onmouseover="this.style.background=\\'#f1f5f9\\'" onmouseout="this.style.background=\\'' + (bg||'') + '\\'"' : '') +
            '>';
    s += '<td style="padding:8px; text-align:center; color:' + (secili ? '#fff' : '#cbd5e1') + '; font-size:' + fs + '; width:24px; position:sticky; left:0; z-index:2; background:' + (bg || '#fff') + ';">' + (icon || '') + '</td>';
    s += '<td style="padding:8px 12px; padding-left:' + (12+indentPx) + 'px; color:' + (textColor || '#0f172a') + '; font-weight:' + w + '; font-size:' + fs + '; position:sticky; left:24px; z-index:2; box-shadow:2px 0 3px -1px rgba(0,0,0,0.08); background:' + (bg || '#fff') + ';">' + ayText + '</td>';
    
    // ÜRETİM
    if (mhsAboneDetay) {
      s += td(uretim.T1, uColor, uBgL, w, 'strong');
      s += td(uretim.T2, uColor, uBgL, w);
      s += td(uretim.A3 || null, a3Color, uBgL, w);
    }
    s += td(uretim.TPL, uColor, uBgT, '600', mhsAboneDetay ? false : 'strong');
    
    // TÜKETİM
    if (mhsAboneDetay) {
      s += td(tuketim.T1, tColor, tBgL, w, 'strong');
      s += td(tuketim.T2, tColor, tBgL, w);
      s += td(tuketim.A3, tColor, tBgL, w);
    }
    s += td(tuketim.TPL, tColor, tBgT, '600', mhsAboneDetay ? false : 'strong');
    
    // Mahsup (abone detayi acik mi?)
    const mDag = opts.mahsupDag || { T1: 0, T2: 0, A3: 0, TPL: (mahsup || 0) };
    if (mhsAboneDetay) {
      // Mor tonları
      const mBgL = bg || '#faf5ff';
      const mBgT = bg || '#f3e8ff';
      s += td(mDag.T1, mColor, mBgL, w, 'strong');
      s += td(mDag.T2, mColor, mBgL, w);
      s += td(mDag.A3, mColor, mBgL, w);
      s += td(mDag.TPL, mColor, mBgT, '600');
    } else {
      s += '<td style="padding:8px 10px; text-align:right; color:' + mColor + '; font-weight:600; font-size:' + fs + ';' + bdLStrong + 'background:' + (bg || 'transparent') + ';">' + (mahsup ? Math.round(mahsup).toLocaleString('tr-TR') : '<span style="opacity:0.4">—</span>') + '</td>';
    }
    
    // MAHSUP SONRASI TÜKETİM
    if (mhsAboneDetay) {
      s += td(sonra.T1, sColor, sBgL, w, 'strong');
      s += td(sonra.T2, sColor, sBgL, w);
      s += td(sonra.A3, sColor, sBgL, w);
    }
    s += td(sonra.TPL, sColor, sBgT, '600', mhsAboneDetay ? false : 'strong');
    
    // Bedelli
    s += '<td style="padding:8px 10px; text-align:right; color:' + bColor + '; font-weight:600; font-size:' + fs + ';' + bdLStrong + 'background:' + (bg || 'transparent') + ';">' + (bedelli ? Math.round(bedelli).toLocaleString('tr-TR') : '<span style="opacity:0.4">—</span>') + '</td>';
    
    s += '</tr>';
    return s;
  }
  
  // THEAD render
  function renderThead() {
    let th = '';
    if (mhsAboneDetay) {
      th += '<tr style="background:#f8fafc; border-bottom:2px solid #cbd5e1;">';
      th += '<th rowspan="2" style="padding:10px; width:24px; position:sticky; left:0; background:#f8fafc; z-index:3;"></th>';
      th += '<th rowspan="2" style="padding:10px 12px; text-align:left; font-weight:600; color:#475569; vertical-align:middle; font-size:12px; position:sticky; left:24px; background:#f8fafc; z-index:3; box-shadow:2px 0 3px -1px rgba(0,0,0,0.08);">Ay / Tarih / Saat</th>';
      th += '<th colspan="4" style="padding:10px; text-align:center; font-weight:600; color:#185fa5; background:#dbeafe; border-left:2px solid #cbd5e1; font-size:12px; letter-spacing:0.5px;">ÜRETİM <span style="font-weight:400; opacity:0.7;">(kWh)</span></th>';
      th += '<th colspan="4" style="padding:10px; text-align:center; font-weight:600; color:#dc2626; background:#fee2e2; border-left:2px solid #cbd5e1; font-size:12px; letter-spacing:0.5px;">TÜKETİM <span style="font-weight:400; opacity:0.7;">(kWh)</span></th>';
      th += '<th colspan="4" style="padding:10px; text-align:center; font-weight:600; color:#7c3aed; background:#e9d5ff; border-left:2px solid #cbd5e1; font-size:12px; letter-spacing:0.5px;">MAHSUP <span style="font-weight:400; opacity:0.7;">(kWh)</span></th>';
      th += '<th colspan="4" style="padding:10px; text-align:center; font-weight:600; color:#ea580c; background:#fed7aa; border-left:2px solid #cbd5e1; font-size:12px; letter-spacing:0.5px;">MAHSUP SONRASI <span style="font-weight:400; opacity:0.7;">(kWh)</span></th>';
      th += '<th rowspan="2" style="padding:10px; text-align:right; font-weight:600; color:#16a34a; vertical-align:middle; border-left:2px solid #cbd5e1; font-size:12px;">Bedelli<br><span style="font-size:10px; font-weight:400; opacity:0.7;">(kWh)</span></th>';
      th += '</tr>';
      th += '<tr style="background:#f1f5f9; border-bottom:1px solid #e2e8f0;">';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#1e40af; background:#eff6ff; border-left:2px solid #cbd5e1; font-size:11px;">T1</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#1e40af; background:#eff6ff; font-size:11px;">T2</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#1e40af; background:#eff6ff; font-size:11px;">A3</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:700; color:#185fa5; background:#bfdbfe; font-size:11px;">TPL</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#991b1b; background:#fef2f2; border-left:2px solid #cbd5e1; font-size:11px;">T1</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#991b1b; background:#fef2f2; font-size:11px;">T2</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#991b1b; background:#fef2f2; font-size:11px;">A3</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:700; color:#dc2626; background:#fecaca; font-size:11px;">TPL</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#6b21a8; background:#f3e8ff; border-left:2px solid #cbd5e1; font-size:11px;">T1</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#6b21a8; background:#f3e8ff; font-size:11px;">T2</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#6b21a8; background:#f3e8ff; font-size:11px;">A3</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:700; color:#7c3aed; background:#ddd6fe; font-size:11px;">TPL</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#9a3412; background:#fff7ed; border-left:2px solid #cbd5e1; font-size:11px;">T1</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#9a3412; background:#fff7ed; font-size:11px;">T2</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:500; color:#9a3412; background:#fff7ed; font-size:11px;">A3</th>';
      th += '<th style="padding:7px 10px; text-align:right; font-weight:700; color:#ea580c; background:#fdba74; font-size:11px;">TPL</th>';
      th += '</tr>';
    } else {
      th += '<tr style="background:#f8fafc; border-bottom:2px solid #cbd5e1;">';
      th += '<th style="padding:12px 10px; width:24px; position:sticky; left:0; background:#f8fafc; z-index:3;"></th>';
      th += '<th style="padding:12px 16px; text-align:left; font-weight:600; color:#475569; font-size:12px; position:sticky; left:24px; background:#f8fafc; z-index:3; box-shadow:2px 0 3px -1px rgba(0,0,0,0.08);">Ay / Tarih / Saat</th>';
      th += '<th style="padding:12px; text-align:right; font-weight:600; color:#185fa5; border-left:2px solid #cbd5e1; font-size:12px; letter-spacing:0.5px;">ÜRETİM <span style="font-weight:400; opacity:0.7; font-size:10px;">(kWh)</span></th>';
      th += '<th style="padding:12px; text-align:right; font-weight:600; color:#dc2626; border-left:2px solid #cbd5e1; font-size:12px; letter-spacing:0.5px;">TÜKETİM <span style="font-weight:400; opacity:0.7; font-size:10px;">(kWh)</span></th>';
      th += '<th style="padding:12px; text-align:right; font-weight:600; color:#7c3aed; border-left:2px solid #cbd5e1; font-size:12px;">MAHSUP <span style="font-weight:400; opacity:0.7; font-size:10px;">(kWh)</span></th>';
      th += '<th style="padding:12px; text-align:right; font-weight:600; color:#ea580c; border-left:2px solid #cbd5e1; font-size:12px; letter-spacing:0.5px;">MAHSUP SONRASI <span style="font-weight:400; opacity:0.7; font-size:10px;">(kWh)</span></th>';
      th += '<th style="padding:12px; text-align:right; font-weight:600; color:#16a34a; border-left:2px solid #cbd5e1; font-size:12px;">BEDELLİ <span style="font-weight:400; opacity:0.7; font-size:10px;">(kWh)</span></th>';
      th += '</tr>';
    }
    document.getElementById('mhs-thead').innerHTML = th;
    
    const btn = document.getElementById('mhs-abone-btn');
    if (btn) btn.innerHTML = mhsAboneDetay ? '✕ Abone Detayı Gizle' : '🔍 Abone Detay (T1/T2/A3) Göster';
  }
  renderThead();
  
  const aylar = Object.keys(mhsData).sort().reverse();
  let tbl = '';
  let topU = { T1:0, T2:0, A3:0, TPL:0 };
  let topT = { T1:0, T2:0, A3:0, TPL:0 };
  let topM = 0, topB = 0;
  let topS = { T1:0, T2:0, A3:0, TPL:0 };
  let topMDag = { T1:0, T2:0, A3:0, TPL:0 };
  
  aylar.forEach(ay => {
    const d = mhsData[ay];
    const ayNo = parseInt(ay.substring(5, 7));
    const ayAd = MHS_AY_ISIM[ayNo - 1] + ' ' + ay.substring(0, 4);
    const ayAcik = (mhsAcikAy === ay);
    
    ['T1','T2','A3','TPL'].forEach(k => {
      topU[k] += d.uretim[k];
      topT[k] += d.tuketim[k];
      topS[k] += d.sonra[k];
      topMDag[k] += (d.mahsup_dagilim && d.mahsup_dagilim[k]) || 0;
    });
    topM += d.mahsup;
    topB += d.bedelli;
    
    // AY satırı - seçilince yumuşak slate-blue
    tbl += renderSatir({
      uretim: d.uretim, tuketim: d.tuketim, mahsup: d.mahsup, 
      mahsupDag: d.mahsup_dagilim,
      sonra: d.sonra, bedelli: d.bedelli,
      indent: 0, 
      bg: ayAcik ? '#475569' : '#f8fafc',
      textColor: ayAcik ? '#fff' : '#0f172a',
      weight: '600', fontSize: '13px',
      level: 'ay', ayText: ayAd, 
      onclick: "mhsAyAc('" + ay + "')",
      icon: ayAcik ? '▼' : '▶'
    });
    
    // AY AÇIKSA günleri göster
    if (ayAcik) {
      const gunler = Object.keys(d.gunler).sort().reverse();
      gunler.forEach(gun => {
        const g = d.gunler[gun];
        const gunAcik = (mhsAcikGun === gun);
        const dt = new Date(gun);
        const gunStr = dt.toLocaleDateString('tr-TR', {day:'2-digit', month:'short', weekday:'short'});
        
        tbl += renderSatir({
          uretim: g.uretim, tuketim: g.tuketim, mahsup: g.mahsup,
          mahsupDag: g.mahsup_dagilim,
          sonra: g.sonra, bedelli: g.bedelli,
          indent: 24, 
          bg: gunAcik ? '#64748b' : '',
          textColor: gunAcik ? '#fff' : '#334155',
          weight: gunAcik ? '600' : '400', fontSize: '12px',
          level: 'gun', ayText: gunStr,
          onclick: "mhsGunAc('" + gun + "')",
          icon: gunAcik ? '▼' : '▶'
        });
        
        // GÜN AÇIKSA saatleri göster
        if (gunAcik && g.saatler) {
          const saatlikMod = (ay >= '2026-05');
          const saatler = Object.keys(g.saatler).sort((a,b)=>parseInt(a)-parseInt(b));
          saatler.forEach(s => {
            const sv = g.saatler[s];
            const sMahsup = saatlikMod ? sv.mahsup : 0;
            const sMahsupDag = saatlikMod ? (sv.mahsup_dagilim || { T1:0, T2:0, A3:0, TPL:0 }) : { T1:0, T2:0, A3:0, TPL:0 };
            const sBedelli = saatlikMod ? sv.bedelli : 0;
            const sSonra = saatlikMod ? sv.sonra : { T1:0, T2:0, A3:0, TPL:0 };
            
            tbl += renderSatir({
              uretim: sv.uretim, tuketim: sv.tuketim, mahsup: sMahsup,
              mahsupDag: sMahsupDag,
              sonra: sSonra, bedelli: sBedelli,
              indent: 48, 
              bg: '#f0f9ff',
              textColor: '#475569',
              weight: '400', fontSize: '11px',
              level: 'saat', ayText: s + ':00',
              icon: ''
            });
          });
        }
      });
    }
  });
  
  // TOPLAM satırı - büyük vurgu
  tbl += renderSatir({
    uretim: topU, tuketim: topT, mahsup: topM,
    mahsupDag: topMDag,
    sonra: topS, bedelli: topB,
    indent: 0, bg: '#fff7ed', textColor: '#9a3412', 
    weight: '700', fontSize: '13px',
    level: 'toplam', ayText: 'TOPLAM (' + aylar.length + ' ay)',
    icon: ''
  });
  
  document.getElementById('mhs-tablo').innerHTML = tbl;
}

// ====================== MAHSUPLAŞMA SEKMESI SONU ======================

// ====================== FATURALANDIRMA SEKMESI ======================
// Aktif abone alt sekmesi (T1/T2/A3) - varsayilan A3
let fatAktifAbone = 'A3';
// YEKDEM aylik bedelleri EPIAS_YEKDEM sozlugunden okunur (EPİAŞ sekmesi).
// Karar mantigi (yekdemHesapla fonksiyonunda):
//  - Gerceklesme varsa -> kesin (yesil)
//  - Sadece ongoru varsa ve onceki ayin sapmasi varsa -> tahmin (sari)
//  - Sadece ongoru varsa, onceki ay yoksa -> ongoru (turuncu)

const FAT_YEKDEM_DEFAULT = 602.51;  // Bilinmeyen aylar icin fallback
const FAT_DAGITIM = 1.035;  // %3,5 dagitim/kayip katsayisi (MEPAŞ faturasi ile dogrulandi)
const FAT_DB_BIRIM = 1.182457;   // OG Tek Terim Sanayi - TL/kWh
const FAT_SANAYI_AKTIF = 2.909687;  // Sanayi Tek Terim Aktif Enerji Bedeli - TL/kWh (AKS3 mahsup indirimi icin)
const FAT_URETIM_SKB = 0.656008;    // Veris yonu Sistem Kullanim Bedeli - TL/kWh (GES uretim faturasi)
const FAT_KDV = 0.20;            // %20
const FAT_AY_ISIM_MAP = {
  '2026-01': 'Ocak 2026',
  '2026-02': 'Şubat 2026',
  '2026-03': 'Mart 2026',
  '2026-04': 'Nisan 2026',
  '2026-05': 'Mayıs 2026',
  '2026-06': 'Haziran 2026',
};
let fatAylikPtf = null;  // aylik_ptf.json - tum aylar

// Bir ay icin YEKDEM bedeli (TL/MWh) - merkezi yekdemHesapla'dan al
function fatYekdemAl(ay) {
  if (!ay) return FAT_YEKDEM_DEFAULT;
  const h = (typeof yekdemHesapla === 'function') ? yekdemHesapla(ay) : null;
  return h ? h.deger : FAT_YEKDEM_DEFAULT;
}

// Bir ay icin YEKDEM durumu - 'kesin' / 'ongoru' / 'tahmin'
function fatYekdemDurum(ay) {
  if (!ay) return 'tahmin';
  const h = (typeof yekdemHesapla === 'function') ? yekdemHesapla(ay) : null;
  return h ? h.durum : 'tahmin';
}

function fatFmt(v, ondalik) {
  if (ondalik === undefined) ondalik = 0;
  if (v === null || v === undefined || isNaN(v)) return '—';
  return Number(v).toLocaleString('tr-TR', {
    minimumFractionDigits: ondalik,
    maximumFractionDigits: ondalik,
  });
}

// Enerji maliyeti formulu: (PTF + YEKDEM) × 1,035 / 1000 -> TL/kWh
// ay parametresi opsiyonel - verilmezse default YEKDEM kullanir
function fatEnerjiMal(ptf_tl_mwh, ay) {
  if (ptf_tl_mwh === null || ptf_tl_mwh === undefined) return null;
  const yekdem = fatYekdemAl(ay);
  return ((ptf_tl_mwh + yekdem) * FAT_DAGITIM) / 1000;
}

async function faturaYukle() {
  // Guncel ay'i ay seciciye yansit (her sekme aciliminda)
  const selEl = document.getElementById('fat-ay-secim');
  if (selEl) {
    const bugun = new Date();
    const gunAy = bugun.getFullYear() + '-' + String(bugun.getMonth() + 1).padStart(2, '0');
    // Eger select icinde guncel ay varsa onu sec
    const opts = Array.from(selEl.options).map(function(o) { return o.value; });
    if (opts.indexOf(gunAy) !== -1) selEl.value = gunAy;
  }
  // 1. Mahsuplaşma verisini hazirla (mhsData global'i mahsupYukleAsync sonunda dolar)
  try {
    if (!mhsData || Object.keys(mhsData).length === 0) {
      await mahsupYukleAsync();
    }
  } catch (e) {
    console.error('Faturalandirma: mahsup verisi alinamadi', e);
  }
  // 2. PTF'yi getir (1 kez yeterli, ay degisiminde yeniden gerekirse cagrilir)
  if (!fatAylikPtf) {
    try {
      const r = await fetch('/api/aylik_ptf?_=' + Date.now());
      if (r.ok) fatAylikPtf = await r.json();
      else fatAylikPtf = {};
      window.fatAylikPtf = fatAylikPtf;
    } catch (e) {
      console.error('Faturalandirma: PTF cekilemedi', e);
      fatAylikPtf = {};
    }
  }
  faturaRender();
}

function faturaRender() {
  const selEl = document.getElementById('fat-ay-secim');
  if (!selEl) return;
  const ay = selEl.value;
  const A = (mhsData || {})[ay];
  const cont = document.getElementById('fat-kartlar');
  if (!cont) return;

  // YEKDEM bilgi bar'ini guncelle
  const yekdemEl = document.getElementById('fat-yekdem-bilgi');
  const yekdemPopup = document.getElementById('fat-yekdem-popup');
  if (yekdemEl) {
    const h = (typeof yekdemHesapla === 'function') ? yekdemHesapla(ay) : null;
    const ayYekdem = h ? h.deger : FAT_YEKDEM_DEFAULT;
    const durum = h ? h.durum : 'tahmin';
    let not = '', popupIcerik = '';
    
    if (durum === 'kesin') {
      not = ' <span style="color:#4ade80;">✓ gerçekleşmiş</span>';
      popupIcerik = '<div class="fat-popup-title">⚡ ' + (FAT_AY_ISIM_MAP[ay] || ay) + ' YEKDEM</div>';
      popupIcerik += '<div class="fat-popup-row"><span>Gerçekleşen</span><span>' + fatFmt(h.gercek, 2) + ' TL/MWh</span></div>';
      if (h.ongoru) {
        const sapma = ((h.gercek / h.ongoru) - 1) * 100;
        const isaret = sapma >= 0 ? '+' : '';
        popupIcerik += '<div class="fat-popup-row"><span>Resmi öngörü</span><span>' + fatFmt(h.ongoru, 2) + '</span></div>';
        popupIcerik += '<div class="fat-popup-row sum"><span>Sapma</span><span>' + isaret + sapma.toFixed(2) + '%</span></div>';
      }
      popupIcerik += '<div class="fat-popup-sonuc"><span>Durum</span><span style="color:#4ade80;">✓ Kesinleşmiş</span></div>';
    } else if (durum === 'tahmin') {
      not = ' <span style="color:#d97706;">⚡ tahmini</span>';
      const fark = (h.kat - 1) * 100;
      const oncekiAyIsmi = h.oncekiAy ? FAT_AY_ISIM_MAP[h.oncekiAy] || h.oncekiAy : 'Önceki ay';
      popupIcerik = '<div class="fat-popup-title" style="color:#d97706;">⚡ ' + (FAT_AY_ISIM_MAP[ay] || ay) + ' Tahmini YEKDEM</div>';
      popupIcerik += '<div style="font-size:10px; color:#94a3b8; margin-bottom:6px; line-height:1.4;">' + oncekiAyIsmi + ' öngörü/gerçek sapması baz alındı.</div>';
      popupIcerik += '<div class="fat-popup-row"><span>' + oncekiAyIsmi + ' öngörü</span><span>' + fatFmt(h.oncekiOngoru, 2) + '</span></div>';
      popupIcerik += '<div class="fat-popup-row"><span>' + oncekiAyIsmi + ' gerçek</span><span>' + fatFmt(h.oncekiGercek, 2) + '</span></div>';
      popupIcerik += '<div class="fat-popup-row sum"><span>Sapma</span><span style="color:#d97706;">+%' + fark.toFixed(2) + ' (' + h.kat.toFixed(4) + '×)</span></div>';
      popupIcerik += '<div class="fat-popup-row"><span>Bu ay öngörü</span><span>' + fatFmt(h.ongoru, 2) + '</span></div>';
      popupIcerik += '<div class="fat-popup-row"><span>× Sapma</span><span>' + h.kat.toFixed(4) + '×</span></div>';
      popupIcerik += '<div class="fat-popup-sonuc" style="color:#d97706; border-top-color:rgba(217,119,6,0.3);"><span>Tahmini YEKDEM</span><span>' + fatFmt(h.deger, 2) + ' TL/MWh</span></div>';
    } else {
      // ongoru durumu (turuncu)
      not = ' <span style="color:#ea580c;">📋 öngörü</span>';
      popupIcerik = '<div class="fat-popup-title" style="color:#ea580c;">📋 ' + (FAT_AY_ISIM_MAP[ay] || ay) + ' Öngörü YEKDEM</div>';
      popupIcerik += '<div class="fat-popup-row"><span>Resmi Öngörü</span><span>' + fatFmt(h.ongoru, 2) + ' TL/MWh</span></div>';
      popupIcerik += '<div class="fat-popup-row"><span>Durum</span><span style="color:#ea580c;">Henüz gerçekleşmedi</span></div>';
      popupIcerik += '<div class="fat-popup-sonuc" style="color:#ea580c;"><span>Kaynak</span><span>EPDK Resmi Açıklama</span></div>';
    }
    
    yekdemEl.innerHTML = fatFmt(ayYekdem, 2) + ' TL/MWh' + not;
    if (yekdemPopup) {
      yekdemPopup.innerHTML = popupIcerik;
      yekdemPopup.classList.remove('sari', 'turuncu');
      if (durum === 'tahmin') yekdemPopup.classList.add('sari');
      else if (durum === 'ongoru') yekdemPopup.classList.add('turuncu');
    }
  }

  if (!A) {
    cont.innerHTML = '<div style="padding:30px; text-align:center; color:#94a3b8; font-size:12px;">' + (FAT_AY_ISIM_MAP[ay] || ay) + ' için veri yok.</div>';
    return;
  }

  const aboneler = [
    { key: 'T1', kls: 'ty1', icon: '☀️', ad: 'TEKYILDIZ 1', sub: 'GES + Tüketim · Çift Yönlü Sayaç', guc: '960 kW' },
    { key: 'T2', kls: 'ty2', icon: '⚡', ad: 'TEKYILDIZ 2', sub: 'GES + Tüketim · Çift Yönlü Sayaç', guc: '960 kW' },
    { key: 'A3', kls: 'aks3', icon: '🏭', ad: 'AKSARAY 3', sub: 'Sadece Tüketim · Tek Yönlü Sayaç', guc: '2.250 kW' },
  ];

  const aktifAb = aboneler.find(function(a){ return a.key === fatAktifAbone; }) || aboneler[2];
  cont.innerHTML = fatKartUret(ay, A, aktifAb);
  ['T1','T2','A3'].forEach(function(k){
    var el = document.getElementById('fst-' + k);
    if (el) el.classList.toggle('aktif', k === fatAktifAbone);
  });
  try { fatGrafikCiz(); } catch(e) { console.error('fatGrafikCiz:', e); }
}

// Gunluk agirlikli birim fiyat grafigi (net vs brut cizgi + net tuketim bar)
window._fatChart = null;
function fatGrafikCiz(){
  const v = window.fatGrafikVeri;
  const cv = document.getElementById('fat-grafik-fiyat');
  if (!v || !cv || !window.Chart || !v.seri || !v.seri.length) return;
  if (window._fatChart) { try { window._fatChart.destroy(); } catch(e){} window._fatChart = null; }

  const etiketler = v.seri.map(d => d.gun);
  const netFiyat  = v.seri.map(d => d.agirlik);
  const brutFiyat = v.seri.map(d => d.brut);
  const netTuk    = v.seri.map(d => d.netTuk);

  window._fatChart = new Chart(cv.getContext('2d'), {
    data: {
      labels: etiketler,
      datasets: [
        { type:'bar', label:'Net Tüketim (kWh)', data: netTuk, yAxisID:'y1',
          backgroundColor:'rgba(148,163,184,0.18)', borderColor:'rgba(148,163,184,0.35)',
          borderWidth:1, borderRadius:3, order:3, barPercentage:0.7 },
        { type:'line', label:'Net Ağırlıklı (TL/kWh)', data: netFiyat, yAxisID:'y',
          borderColor: OTO_G.ptf, backgroundColor:'rgba(52,210,235,0.08)',
          borderWidth:2.5, pointRadius:2.5, pointBackgroundColor:OTO_G.ptf,
          tension:0.3, fill:true, order:1 },
        { type:'line', label:'Brüt (mahsup öncesi)', data: brutFiyat, yAxisID:'y',
          borderColor:'#cbd5e1', borderWidth:1.5, borderDash:[5,4],
          pointRadius:0, tension:0.3, fill:false, order:2 }
      ]
    },
    options: {
      responsive:true, maintainAspectRatio:false,
      interaction:{ mode:'index', intersect:false },
      plugins:{
        legend:{ display:true, position:'top', labels:{ boxWidth:12, font:{size:10}, color:'#64748b' } },
        tooltip:{ callbacks:{
          title: items => 'Gün ' + items[0].label,
          label: it => {
            if (it.dataset.yAxisID === 'y1') return ' ' + it.dataset.label + ': ' + Math.round(it.parsed.y).toLocaleString('tr-TR');
            return ' ' + it.dataset.label + ': ' + (it.parsed.y != null ? it.parsed.y.toFixed(4) : '—');
          }
        }}
      },
      scales:{
        y:{ position:'left', title:{ display:true, text:'TL/kWh', font:{size:9}, color:'#94a3b8' },
            ticks:{ color:'#94a3b8', font:{size:9}, callback:v=>v.toFixed(2) }, grid:{ color:'rgba(148,163,184,0.1)' } },
        y1:{ position:'right', title:{ display:true, text:'kWh', font:{size:9}, color:'#cbd5e1' },
             ticks:{ color:'#cbd5e1', font:{size:9} }, grid:{ display:false } },
        x:{ ticks:{ color:'#94a3b8', font:{size:9} }, grid:{ display:false } }
      }
    }
  });
}

function fatAboneSec(key){
  fatAktifAbone = key;
  faturaRender();
}

// ============================================================
// T2 KIYAS SEKMESI
// Saat saat: A (Bedelli=2.2537) vs B11 (Sebeke maliyet) vs B12 (GES firsat)
// Her saat icin: o ayin o saatindeki ortalama PTF kullanilir
// ============================================================

async function t2KiyasYukle() {
  const tablo = document.getElementById('t2k-tablo');
  const ozet = document.getElementById('t2k-ozet');
  if (!tablo) return;
  tablo.innerHTML = '<div style="padding:30px; text-align:center; color:#64748b; font-size:12px;">Hesaplaniyor...</div>';
  if (ozet) ozet.innerHTML = '';
  
  // PTF verisi
  if (!window.fatAylikPtf) {
    try {
      const r = await fetch('/api/aylik_ptf');
      window.fatAylikPtf = await r.json();
    } catch(e) {
      tablo.innerHTML = '<div style="padding:20px; color:#dc2626; font-size:11px;">PTF verisi alinamadi</div>';
      return;
    }
  }
  
  // Ozet (BTC fiyat, dunku BTC)
  if (!window.lastOzet) {
    try {
      const r = await fetch('/api/ozet');
      window.lastOzet = await r.json();
    } catch(e) {}
  }
  
  // T2 OSOS verisi
  const selEl2 = document.getElementById('t2k-ay-secim');
  const ay = selEl2 ? selEl2.value : '2026-06';
  
  if (!window.t2OsosData || window.t2OsosAy !== ay) {
    try {
      const r = await fetch('/api/osos_raw');
      const osos = await r.json();
      // T2 OSOS (mahsup sonrasi net)
      const t2 = (osos && osos.tekyildiz_2 && osos.tekyildiz_2.veri) || {};
      const t2Ay = {};
      Object.keys(t2).forEach(function(tarih) {
        if (tarih.startsWith(ay)) {
          const gun = tarih.split('-')[2];
          t2Ay[gun] = t2[tarih];
        }
      });
      window.t2OsosData = t2Ay;
      
      // T1 OSOS (saf uretim - mahsup yok)
      const t1 = (osos && osos.tekyildiz_1 && osos.tekyildiz_1.veri) || {};
      const t1Ay = {};
      Object.keys(t1).forEach(function(tarih) {
        if (tarih.startsWith(ay)) {
          const gun = tarih.split('-')[2];
          t1Ay[gun] = t1[tarih];
        }
      });
      window.t1OsosData = t1Ay;
      
      window.t2OsosAy = ay;
    } catch(e) {
      window.t2OsosData = {};
      window.t1OsosData = {};
    }
  }
  
  // F2Pool TUM GUNLER icin paralel cek (saatlik BTC TL gelir verisi)
  window.t2F2PoolCache = window.t2F2PoolCache || {};
  const ptfAy = (window.fatAylikPtf || {})[ay] || {};
  const ayGunleri = Object.keys(ptfAy).sort();
  
  const cekilmeyenGunler = ayGunleri.filter(function(g) {
    return !window.t2F2PoolCache[ay + '-' + g];
  });
  
  if (cekilmeyenGunler.length > 0) {
    tablo.innerHTML = '<div style="padding:30px; text-align:center; color:#64748b; font-size:12px;">F2Pool verileri cekiliyor... (' + cekilmeyenGunler.length + ' gun)</div>';
    
    await Promise.all(cekilmeyenGunler.map(async function(g) {
      const tarih = ay + '-' + g;
      try {
        const r = await fetch('/api/f2pool_saatlik?gun=' + tarih);
        const d = await r.json();
        if (d && d.saatler) {
          window.t2F2PoolCache[tarih] = d;
        } else {
          window.t2F2PoolCache[tarih] = {saatler: []};  // bos cache
        }
      } catch(e) {
        window.t2F2PoolCache[tarih] = {saatler: []};
      }
    }));
  }
  
  t2KiyasRender();
}

function t2KiyasRender() {
  const tablo = document.getElementById('t2k-tablo');
  const ozet = document.getElementById('t2k-ozet');
  const selEl = document.getElementById('t2k-ay-secim');
  if (!tablo || !selEl) return;
  const ay = selEl.value;
  
  // Sabitler
  const BEDELLI = 2.253679;
  const DB = 1.182457;
  const TRT = 1.035;
  const TUKETIM_SAAT = 174;  // kWh - 29 cihaz saatlik
  
  // YEKDEM
  let yekdem = 580.99;
  if (typeof yekdemHesapla === 'function') {
    const h = yekdemHesapla(ay);
    if (h && h.deger) yekdem = h.deger;
  }
  
  // Veriler
  const ptfAy = (window.fatAylikPtf || {})[ay] || {};
  const ososT2 = window.t2OsosData || {};  // T2 OSOS (mahsup sonrasi net)
  const ososT1 = window.t1OsosData || {};  // T1 OSOS (saf uretim - kıyas tablosu uretim kararinda kullanilir)
  const gunler = Object.keys(ptfAy).sort();
  
  if (gunler.length === 0) {
    tablo.innerHTML = '<div style="background:#fef3c7; border:1px solid #f59e0b; padding:14px; border-radius:10px; color:#92400e; font-size:11px;">⚠ ' + ay + ' icin PTF verisi yok</div>';
    return;
  }
  
  // F2Pool cache'den her saatin TL gelirini al (cache: window.t2F2PoolCache)
  // S2 her saat icin gercek deger - asagida saat icindeyken cache'den okunur
  
  // 80bin USD bandi carpani (mevcut BTC USD fiyatina gore)
  let BTC_80BIN_CARPAN = 1.3163;  // varsayilan ~80000/60778
  if (window.lastOzet && window.lastOzet.btc && window.lastOzet.btc.usd) {
    const btcUsdSimdi = parseFloat((window.lastOzet.btc.usd + '').replace(/,/g, ''));
    if (btcUsdSimdi > 0) {
      BTC_80BIN_CARPAN = 80000 / btcUsdSimdi;
    }
  }
  
  // Her gün için topla, kart aç-kapat
  let ozet_s1 = 0, ozet_s2 = 0, ozet_s3 = 0;
  let html = '';
  
  gunler.forEach(function(gun) {
    const dizi = ptfAy[gun];
    if (!Array.isArray(dizi)) return;
    const t2gun = (ososT2[gun] || {});  // T2 mahsup sonrasi
    const t1gun = (ososT1[gun] || {});  // T1 saf uretim
    
    // Gun toplamlari ve saat sayaclari
    let g_s1 = 0, g_s2 = 0, g_s3 = 0;
    let g_sat_saat = 0, g_btc_saat = 0, g_deg_saat = 0, g_kapat_saat = 0;
    let saatTablo = '';
    
    for (let s = 0; s < 24; s++) {
      const ptf = (typeof dizi[s] === 'number') ? dizi[s] : null;
      if (ptf === null) continue;
      
      // OSOS verileri
      const t2saat = t2gun[String(s)];
      const t1saat = t1gun[String(s)];
      const veris = t2saat ? (t2saat.veris || 0) : 0;
      const cekis = t2saat ? (t2saat.cekis || 0) : 0;
      const t1veris = t1saat ? (t1saat.veris || 0) : 0;  // T1 saf uretim
      
      // URETIM KARARI (T1 saf uretim verisinden):
      // - T1 verisi YOKSA: belirsiz, S1 hesaplanmaz
      // - T1 veris > 174 (TUKETIM): uretim VAR → S1 = 392
      // - T1 veris ≤ 174: uretim YOK → S1 = 0
      let uretim;
      if (!t1saat) {
        uretim = null;  // T1 verisi yok, belirsiz
      } else if (t1veris > TUKETIM_SAAT) {
        uretim = TUKETIM_SAAT;
      } else {
        uretim = 0;
      }
      
      const sebeke = (ptf + yekdem) / 1000 * TRT + DB;
      
      // S2: F2Pool cache'den o saatin gercek TL gelirini al
      const f2gun = window.t2F2PoolCache[ay + '-' + gun];
      let s2 = 0;
      if (f2gun && f2gun.saatler) {
        const saatStr = (s < 10 ? '0' + s : '' + s);
        const f2s = f2gun.saatler.find(function(x) { return x.saat === saatStr; });
        if (f2s && typeof f2s.tl === 'number') {
          s2 = f2s.tl;
        }
      }
      
      // Senaryolar
      const s1 = (uretim !== null) ? (uretim * BEDELLI) : null;
      const s3 = -(TUKETIM_SAAT * sebeke);
      
      // Gun toplamlari (referans)
      if (s1 !== null) g_s1 += s1;
      g_s2 += s2; g_s3 += s3;
      
      // 80bin USD bandinda hipotetik S2 (BTC fiyat yukseldiyse ne olurdu)
      const s2_80bin = s2 * BTC_80BIN_CARPAN;
      const s3_mutlak = Math.abs(s3);
      
      // KARAR MANTIGI (SAT / DEG / KAPAT):
      // - Uretim VAR + S1 > S2  → SAT
      // - S2 > |S3|              → DEG (madencilik mevcut fiyatla karli, T2 pahali, baska aboneye gec)
      // - S2_80bin > |S3|        → DEG (80bin USD'de karli olabilir, umut var)
      // - Aksi takdirde          → KAPAT (80bin USD bandinda bile zarar, cihazlari kapat)
      let s_etiket, s_renk;
      if (s1 !== null && s1 > 0 && s1 > s2) {
        s_etiket = 'SAT'; s_renk = '#16a34a'; g_sat_saat++;
      } else if (s2 > s3_mutlak) {
        s_etiket = 'DEG'; s_renk = '#dc2626'; g_deg_saat++;
      } else if (s2_80bin > s3_mutlak) {
        s_etiket = 'DEG'; s_renk = '#dc2626'; g_deg_saat++;
      } else {
        s_etiket = 'KAPAT'; s_renk = '#0f172a'; g_kapat_saat++;
      }
      
      // S1 ve S3 vurgu renkleri (kazanan kolon arka plan + kalin)
      const s1Bg = (s_etiket === 'SAT') ? '#dcfce7' : '#fff';
      const s1Color = (s_etiket === 'SAT') ? '#15803d' : '#1e293b';
      const s1Weight = (s_etiket === 'SAT') ? '800' : '400';
      let s3Bg = '#fff', s3Color = '#1e293b', s3Weight = '400';
      if (s_etiket === 'DEG') { s3Bg = '#fee2e2'; s3Color = '#991b1b'; s3Weight = '800'; }
      else if (s_etiket === 'KAPAT') { s3Bg = '#0f172a'; s3Color = '#fff'; s3Weight = '900'; }
      
      saatTablo += '<tr onclick="t2HucreAc(this)" data-gun="' + gun + '" data-saat="' + s + '" data-ay="' + ay + '" data-ptf="' + ptf + '" data-veris="' + veris + '" data-cekis="' + cekis + '" data-uretim="' + uretim + '" data-sebeke="' + sebeke + '" data-s1="' + s1 + '" data-s2="' + s2 + '" data-s3="' + s3 + '" style="cursor:pointer;">';
      saatTablo += '<td style="padding:5px 6px; text-align:center; font-weight:700; color:#1e293b; background:#f8fafc; border-right:1px solid #e2e8f0;">' + (s<10?'0'+s:s) + '</td>';
      saatTablo += '<td style="padding:5px 6px; text-align:right; color:#475569;">' + (uretim===null?'<span style="color:#cbd5e1;">—</span>':uretim.toFixed(0)) + '</td>';
      saatTablo += '<td style="padding:5px 6px; text-align:right; color:#475569;">' + TUKETIM_SAAT + '</td>';
      saatTablo += '<td style="padding:5px 6px; text-align:right; color:#94a3b8;">' + ptf.toFixed(0) + '</td>';
      saatTablo += '<td style="padding:5px 6px; text-align:right; color:#94a3b8;">' + sebeke.toFixed(2) + '</td>';
      saatTablo += '<td style="padding:5px 6px; text-align:right; color:' + s1Color + '; background:' + s1Bg + '; font-weight:' + s1Weight + ';">' + (s1===null?'<span style="color:#cbd5e1;">—</span>':s1.toFixed(0)) + '</td>';
      saatTablo += '<td style="padding:5px 6px; text-align:right; color:#94a3b8;">' + s2.toFixed(0) + '</td>';
      saatTablo += '<td style="padding:5px 6px; text-align:right; color:' + s3Color + '; background:' + s3Bg + '; font-weight:' + s3Weight + ';">' + s3.toFixed(0) + '</td>';
      saatTablo += '<td style="padding:5px 6px; text-align:center;"><span style="background:' + s_renk + '; color:#fff; padding:3px 9px; border-radius:8px; font-weight:800; font-size:10px;">' + s_etiket + '</span></td>';
      saatTablo += '</tr>';
    }
    
    ozet_s1 += g_s1; ozet_s2 += g_s2; ozet_s3 += g_s3;
    
    // Gun icinde saat dagilimi (kac saat SAT, BTC, DEG)
    // saatTablo render edildiginde s_etiket'i degisken olarak topla
    // Yukarida forEach yapilirken degisken yok, bu yuzden bu sayilari onceden saymak gerek
    // Aslinda zaten s_max hesabini yapiyoruz, sadece sayim ekleyecegiz
    
    const accordionId = 't2k-gun-' + gun;
    
    html += '<div class="t2k-gun-kart" style="background:#fff; border-radius:10px; margin-bottom:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.05);">';
    html += '<div onclick="t2GunAc(' + Number(gun) + ')" style="padding:12px 14px; display:flex; align-items:center; justify-content:space-between; cursor:pointer; gap:8px; background:linear-gradient(135deg,#f8fafc,#f1f5f9);" id="t2k-gun-basligi-' + gun + '">';
    html += '<div style="display:flex; align-items:center; gap:10px;">';
    html += '<span style="font-size:11px; color:#64748b;">▶</span>';
    html += '<span style="font-weight:800; color:#1e293b; font-size:13px;">' + Number(gun) + ' ' + ayAdi(ay) + '</span>';
    html += '</div>';
    html += '<div style="display:flex; align-items:center; gap:6px; font-size:10px;" id="t2k-gun-dagilim-' + gun + '">';
    html += '<span style="background:#dcfce7; color:#15803d; padding:2px 7px; border-radius:8px; font-weight:800;">SAT ' + g_sat_saat + 'h</span>';
    html += '<span style="background:#fee2e2; color:#991b1b; padding:2px 7px; border-radius:8px; font-weight:800;">DEG ' + g_deg_saat + 'h</span>';
    if (g_kapat_saat > 0) html += '<span style="background:#0f172a; color:#fff; padding:2px 7px; border-radius:8px; font-weight:800;">KAPAT ' + g_kapat_saat + 'h</span>';
    html += '</div></div>';
    
    html += '<div id="' + accordionId + '" style="display:none; padding:0; overflow-x:auto; -webkit-overflow-scrolling:touch;">';
    html += '<table style="width:100%; border-collapse:collapse; font-size:10px; min-width:600px;">';
    html += '<thead><tr style="background:#f1f5f9; color:#64748b; font-weight:800;">';
    html += '<th style="padding:6px 6px;">Saat</th>';
    html += '<th style="padding:6px 6px; text-align:right;">Uretim</th>';
    html += '<th style="padding:6px 6px; text-align:right;">Tuketim</th>';
    html += '<th style="padding:6px 6px; text-align:right;">PTF</th>';
    html += '<th style="padding:6px 6px; text-align:right;">Sebeke</th>';
    html += '<th style="padding:6px 6px; text-align:right;">S1</th>';
    html += '<th style="padding:6px 6px; text-align:right;">S2</th>';
    html += '<th style="padding:6px 6px; text-align:right;">S3</th>';
    html += '<th style="padding:6px 6px; text-align:center;">TERCIH</th>';
    html += '</tr></thead><tbody>' + saatTablo + '</tbody></table></div>';
    html += '</div>';
  });
  
  tablo.innerHTML = html;
  
  // Ay ozet karti
  if (ozet) {
    const a_max = Math.max(ozet_s1, ozet_s2, ozet_s3);
    let a_etiket = 'SAT', a_renk = '#16a34a';
    if (a_max === ozet_s2) { a_etiket = 'BTC'; a_renk = '#a855f7'; }
    else if (a_max === ozet_s3) { a_etiket = 'DEGISTIR'; a_renk = '#dc2626'; }
    
    let ozetHtml = '<div style="background:#fff; border-radius:12px; padding:14px; box-shadow:0 1px 3px rgba(0,0,0,0.05);">';
    ozetHtml += '<div style="font-size:11px; color:#64748b; font-weight:700; margin-bottom:8px;">' + ayAdi(ay) + ' TOPLAM</div>';
    ozetHtml += '<div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px;">';
    ozetHtml += '<div style="text-align:center;"><div style="font-size:10px; color:#16a34a; font-weight:700;">S1 SAT</div><div style="font-size:18px; font-weight:900; color:#15803d;">' + ozet_s1.toFixed(0) + '</div><div style="font-size:9px; color:#94a3b8;">TL</div></div>';
    ozetHtml += '<div style="text-align:center;"><div style="font-size:10px; color:#a855f7; font-weight:700;">S2 BTC</div><div style="font-size:18px; font-weight:900; color:#7c3aed;">' + ozet_s2.toFixed(0) + '</div><div style="font-size:9px; color:#94a3b8;">TL</div></div>';
    ozetHtml += '<div style="text-align:center;"><div style="font-size:10px; color:#dc2626; font-weight:700;">S3 DEG</div><div style="font-size:18px; font-weight:900; color:#991b1b;">' + ozet_s3.toFixed(0) + '</div><div style="font-size:9px; color:#94a3b8;">TL</div></div>';
    ozetHtml += '</div>';
    ozetHtml += '<div style="margin-top:10px; padding:8px 12px; background:' + a_renk + '; color:#fff; border-radius:8px; text-align:center; font-weight:800; font-size:13px;">EN AVANTAJLI: ' + a_etiket + '</div>';
    ozetHtml += '</div>';
    
    ozet.innerHTML = ozetHtml;
  }
}

// Yardimci: ay adi
function ayAdi(ay) {
  const aylar = ['Ocak','Subat','Mart','Nisan','Mayis','Haziran','Temmuz','Agustos','Eylul','Ekim','Kasim','Aralik'];
  const ay_no = parseInt((ay || '2026-06').split('-')[1]);
  return aylar[ay_no-1] + ' ' + (ay || '').split('-')[0];
}

// Gun aç/kapat (basit toggle, F2Pool zaten render ediliyor)
function t2GunAc(n) {
  const gunStr = n < 10 ? '0' + n : '' + n;
  const el = document.getElementById('t2k-gun-' + gunStr);
  if (!el) return;
  el.style.display = (el.style.display === 'none') ? 'block' : 'none';
}

function t2HucreAc(el) {
  const gun = el.getAttribute('data-gun');
  const saat = parseInt(el.getAttribute('data-saat'));
  const ay = el.getAttribute('data-ay');
  const ptf = parseFloat(el.getAttribute('data-ptf'));
  const veris = parseFloat(el.getAttribute('data-veris'));
  const cekis = parseFloat(el.getAttribute('data-cekis'));
  const uretim = parseFloat(el.getAttribute('data-uretim'));
  const sebeke = parseFloat(el.getAttribute('data-sebeke'));
  const s1 = parseFloat(el.getAttribute('data-s1'));
  const s2 = parseFloat(el.getAttribute('data-s2'));
  const s3 = parseFloat(el.getAttribute('data-s3'));
  
  const BEDELLI = 2.253679, DB = 1.182457, TRT = 1.035, TUKETIM = 174;
  let yekdem = 580.99;
  if (typeof yekdemHesapla === 'function') {
    const h = yekdemHesapla(ay);
    if (h && h.deger) yekdem = h.deger;
  }
  
  const baslikEl = document.getElementById('t2k-popup-baslik');
  if (baslikEl) baslikEl.textContent = Number(gun) + ' ' + ayAdi(ay) + ', ' + (saat<10?'0'+saat:saat) + ':00';
  
  let html = '';
  
  // VERILER
  html += '<div style="background:#f8fafc; border-radius:10px; padding:10px; margin-bottom:12px;">';
  html += '<div style="font-size:10px; font-weight:800; color:#64748b; margin-bottom:6px;">VERILER</div>';
  html += '<div style="display:grid; grid-template-columns:1fr auto; gap:3px 12px; font-size:11px;">';
  // T1 saf üretim verisi de gösterilsin (üretim kararı için kullanılıyor)
  const t1OsosGun = (window.t1OsosData || {})[gun] || {};
  const t1OsosSaat = t1OsosGun[String(saat)];
  const t1Veris = t1OsosSaat ? (t1OsosSaat.veris || 0) : null;
  html += '<span style="color:#64748b;">T1 uretim (saf)</span><span style="font-weight:700; color:#a855f7;">' + (t1Veris===null?'—':t1Veris.toFixed(0) + ' kWh') + '</span>';
  html += '<span style="color:#64748b;">T2 OSOS veris</span><span style="font-weight:700; color:#1e293b;">' + veris.toFixed(0) + ' kWh</span>';
  html += '<span style="color:#64748b;">T2 OSOS cekis</span><span style="font-weight:700; color:#1e293b;">' + cekis.toFixed(0) + ' kWh</span>';
  html += '<span style="color:#64748b;">Uretim karari</span><span style="font-weight:700; color:#a855f7;">' + (uretim>0?'VAR (' + TUKETIM + ' kWh, T1>174)':uretim===0?'YOK (T1≤174)':'—') + '</span>';
  html += '<span style="color:#64748b;">Tuketim (sabit)</span><span style="font-weight:700; color:#1e293b;">' + TUKETIM + ' kWh</span>';
  html += '<span style="color:#64748b;">PTF</span><span style="font-weight:700; color:#1e293b;">' + ptf.toFixed(2) + ' TL/MWh</span>';
  html += '<span style="color:#64748b;">YEKDEM</span><span style="font-weight:700; color:#1e293b;">' + yekdem.toFixed(2) + ' TL/MWh</span>';
  html += '<span style="color:#64748b;">Sebeke maliyeti</span><span style="font-weight:700; color:#dc2626;">' + sebeke.toFixed(4) + ' TL/kWh</span>';
  html += '<span style="color:#64748b;">Bedelli satis</span><span style="font-weight:700; color:#16a34a;">' + BEDELLI.toFixed(4) + ' TL/kWh</span>';
  html += '</div></div>';
  
  // S1
  html += '<div style="background:#dcfce7; border-left:4px solid #16a34a; padding:10px; border-radius:6px; margin-bottom:8px;">';
  html += '<div style="font-weight:800; color:#15803d; font-size:13px; margin-bottom:4px;">S1) Sadece Satis</div>';
  html += '<div style="font-family:monospace; font-size:10px; color:#166534;">';
  html += uretim.toFixed(0) + ' kWh × ' + BEDELLI.toFixed(4) + ' = <b>' + s1.toFixed(0) + ' TL</b>';
  html += '</div></div>';
  
  // S2
  html += '<div style="background:#f3e8ff; border-left:4px solid #a855f7; padding:10px; border-radius:6px; margin-bottom:8px;">';
  html += '<div style="font-weight:800; color:#7c3aed; font-size:13px; margin-bottom:4px;">S2) BTC Madencilik</div>';
  html += '<div style="font-family:monospace; font-size:10px; color:#6b21a8;">';
  html += 'Saatlik BTC × BTC fiyat = <b>' + s2.toFixed(0) + ' TL</b>';
  html += '</div></div>';
  
  // S3
  html += '<div style="background:#fee2e2; border-left:4px solid #dc2626; padding:10px; border-radius:6px; margin-bottom:12px;">';
  html += '<div style="font-weight:800; color:#991b1b; font-size:13px; margin-bottom:4px;">S3) Sadece Tuketim</div>';
  html += '<div style="font-family:monospace; font-size:10px; color:#7f1d1d;">';
  html += '−(' + TUKETIM + ' × ' + sebeke.toFixed(4) + ') = <b>' + s3.toFixed(0) + ' TL</b>';
  html += '</div></div>';
  
  // KARAR MANTIGI (SAT / DEG / KAPAT)
  let btcUsdSimdi = 60778;
  if (window.lastOzet && window.lastOzet.btc && window.lastOzet.btc.usd) {
    btcUsdSimdi = parseFloat((window.lastOzet.btc.usd + '').replace(/,/g, '')) || 60778;
  }
  const carpan80bin = 80000 / btcUsdSimdi;
  const s2_80bin = s2 * carpan80bin;
  const s3_mutlak = Math.abs(s3);
  
  let etiket, renk, gerekce;
  if (s1 !== null && s1 > 0 && s1 > s2) {
    etiket = 'SAT (Bedelli)'; renk = '#16a34a';
    gerekce = 'S1 (' + s1.toFixed(0) + ') > S2 (' + s2.toFixed(0) + ') - satis daha karli';
  } else if (s2 > s3_mutlak) {
    etiket = 'ABONE DEGISTIR'; renk = '#dc2626';
    gerekce = 'S2 (' + s2.toFixed(0) + ') > |S3| (' + s3_mutlak.toFixed(0) + ') - madencilik mevcut fiyatla karli, T2 pahali, baska aboneye gec';
  } else if (s2_80bin > s3_mutlak) {
    etiket = 'ABONE DEGISTIR'; renk = '#dc2626';
    gerekce = 'BTC 80bin USD bandinda S2 ≈ ' + s2_80bin.toFixed(0) + ' > |S3| (' + s3_mutlak.toFixed(0) + ') - fiyat yukselince karli olur, beklemeyi sec';
  } else {
    etiket = 'SISTEMI KAPAT'; renk = '#0f172a';
    gerekce = 'BTC 80bin USD bandinda bile S2 ≈ ' + s2_80bin.toFixed(0) + ' < |S3| (' + s3_mutlak.toFixed(0) + ') - fiyat artsa da karli degil, cihazlari kapat';
  }
  
  html += '<div style="background:' + renk + '; color:#fff; padding:12px; border-radius:10px; text-align:center;">';
  html += '<div style="font-weight:900; font-size:14px;">EN AVANTAJLI: ' + etiket + '</div>';
  html += '<div style="font-size:10px; margin-top:6px; opacity:0.95; padding:0 8px; line-height:1.4;">' + gerekce + '</div>';
  html += '</div>';
  
  const icerikEl = document.getElementById('t2k-popup-icerik');
  if (icerikEl) icerikEl.innerHTML = html;
  
  const ov = document.getElementById('t2k-hucre-popup');
  if (ov) ov.style.display = 'flex';
}

function t2HucreKapat(e) {
  const ov = document.getElementById('t2k-hucre-popup');
  if (ov) ov.style.display = 'none';
}
function fatKartUret(ay, A, ab) {
  // FATURALANDIRMA
  // Saatlik detay tablosu + Ust kisimda ay toplam fatura karti
  // Mahsup Maliyeti = 2,909687 TL/kWh (3 abone icin de)
  // Dagitim Bedeli birim = 1,182457 TL/kWh (OG Tek Terim Sanayi)
  // KDV = Toplam × %20
  const ayPtf = (fatAylikPtf || {})[ay] || {};
  const gunler = Object.keys(A.gunler || {}).sort();
  const aylar = ['Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara'];
  const fatSeri = [];  // gunluk seri: agirlikli birim fiyat grafigi + karsilastirma icin

  const mhsMal = FAT_SANAYI_AKTIF;  // 2,909687 - tum aboneler icin
  const gesMi = (ab.key === 'T1' || ab.key === 'T2');  // GES aboneleri (uretim kolonu icin)

  // Ay toplamlar (icin gerekli)
  let ayHam = 0, ayMhs = 0, ayTukBed = 0, ayMhsBed = 0, ayHesapVar = false;
  let ayUretim = 0;  // GES uretimi (T1/T2 icin veris kWh)
  let ayUretMhs = 0, ayUretBedelli = 0;  // uretimden mahsup edilen / bedelli (satilan)
  let ayUretMhsBed = 0;  // uretim mahsup faydasi PTF-bazli deger (TL)

  // Her gun icin: gun satiri + (kapali) saatlik detay satiri
  let satirlar = '';

  gunler.forEach(function(g) {
    const G = A.gunler[g];
    const gPtfArr = ayPtf[g.slice(-2)] || [];

    let gHam = 0, gMhs = 0, gTukBed = 0, gMhsBed = 0, gPtfTpl = 0, gPtfCnt = 0, gHesapVar = false;
    let gUret = 0;  // gunluk GES uretimi
    let gUretMhs = 0, gUretBedelli = 0;  // gunluk uretimden mahsup / bedelli
    let saatRows = '';

    for (let s = 0; s < 24; s++) {
      const sk = String(s).padStart(2, '0');
      const S = (G.saatler || {})[sk] || {};
      const tuk = S.tuketim || {};
      const mhsDag = S.mahsup_dagilim || {};
      const sHam = tuk[ab.key] || 0;
      const sMhs = mhsDag[ab.key] || 0;
      const sPtf = (gPtfArr && gPtfArr[s] !== undefined && gPtfArr[s] !== null) ? gPtfArr[s] : null;
      const sMal = sPtf !== null ? fatEnerjiMal(sPtf, ay) : null;

      // Tuketim Bedeli = Ham × Enerji Maliyeti
      const sTukBed = (sMal !== null) ? (sHam * sMal) : null;
      // Mahsup Bedeli = Mahsup × o saatin PTF enerji maliyeti (kacinilan tuketim bedeli)
      const sMhsBed = (sMal !== null) ? (sMhs * sMal) : 0;
      // Toplam Bedel = Tuketim Bedeli - Mahsup Bedeli
      const sToplam = (sTukBed !== null) ? (sTukBed - sMhsBed) : null;

      if (sPtf !== null) { gPtfTpl += sPtf; gPtfCnt++; }
      gHam += sHam; gMhs += sMhs;
      // GES uretimi (bu abonenin o saatteki verisi)
      const sUret = (S.uretim && S.uretim[ab.key]) || 0;
      // Kaynak takipli: bu GES'in uretimi nereye gitti (gercek, oranlama yok)
      const sKaynak = (S.kaynak && S.kaynak[ab.key]) || {T1:0,T2:0,A3:0,bedelli:0};
      const sUretMhs = (sKaynak.T1||0) + (sKaynak.T2||0) + (sKaynak.A3||0);  // bu GES'ten mahsuba giden
      const sUretBedelli = sKaynak.bedelli || 0;  // bu GES'ten satilan
      ayUretim += sUret;
      gUret += sUret;
      ayUretMhs += sUretMhs; gUretMhs += sUretMhs;
      ayUretMhsBed += (sMal !== null) ? (sUretMhs * sMal) : 0;  // PTF-bazli mahsup faydasi
      ayUretBedelli += sUretBedelli; gUretBedelli += sUretBedelli;
      if (sTukBed !== null) { gTukBed += sTukBed; gHesapVar = true; }
      gMhsBed += sMhsBed;

      saatRows += '<tr>';
      saatRows += '<td>' + sk + '</td>';
      if (gesMi) {
        saatRows += '<td style="color:#16a34a;font-weight:700;text-align:right;">' + fatFmt(sUret, 2) + '</td>';
        // Mahsup Edilen (uretimden) - popup: hangi aboneye ne kadar (GERCEK kaynak)
        saatRows += '<td class="fat-hover-cell" style="color:#7c3aed;font-weight:700;text-align:right;">' + fatFmt(sUretMhs, 2);
        saatRows += '<div class="fat-popup mor">';
        saatRows += '<div class="fat-popup-title mor">🔄 Üretimden Mahsup (saat ' + sk + ')</div>';
        saatRows += '<div class="fat-popup-row"><span>' + ab.ad + ' Üretimi</span><span>' + fatFmt(sUret, 2) + ' kWh</span></div>';
        if (sKaynak.T1 > 0) saatRows += '<div class="fat-popup-row"><span>↳ TEKYILDIZ 1 tüketimine</span><span>' + fatFmt(sKaynak.T1, 2) + '</span></div>';
        if (sKaynak.T2 > 0) saatRows += '<div class="fat-popup-row"><span>↳ TEKYILDIZ 2 tüketimine</span><span>' + fatFmt(sKaynak.T2, 2) + '</span></div>';
        if (sKaynak.A3 > 0) saatRows += '<div class="fat-popup-row"><span>↳ AKSARAY 3 tüketimine</span><span>' + fatFmt(sKaynak.A3, 2) + '</span></div>';
        saatRows += '<div class="fat-popup-sonuc mor"><span>Toplam Mahsup</span><span>' + fatFmt(sUretMhs, 2) + ' kWh</span></div>';
        saatRows += '</div></td>';
        // Bedelli - popup
        saatRows += '<td class="fat-hover-cell" style="color:#16a34a;font-weight:700;text-align:right;">' + fatFmt(sUretBedelli, 2);
        saatRows += '<div class="fat-popup">';
        saatRows += '<div class="fat-popup-title">💚 Bedelli Üretim (saat ' + sk + ')</div>';
        saatRows += '<div class="fat-popup-row"><span>' + ab.ad + ' Üretimi</span><span>' + fatFmt(sUret, 2) + ' kWh</span></div>';
        saatRows += '<div class="fat-popup-row"><span>− Mahsup Edilen</span><span style="color:#7c3aed;">' + fatFmt(sUretMhs, 2) + '</span></div>';
        saatRows += '<div class="fat-popup-sonuc"><span>= Bedelli (Satılan)</span><span style="color:#16a34a;">' + fatFmt(sUretBedelli, 2) + ' kWh</span></div>';
        saatRows += '</div></td>';
      }
      saatRows += '<td class="fat-col-ham">' + fatFmt(sHam, 2) + '</td>';
      // Mahsup - hover popup (o saatte hangi GES'ten ne kadar mahsup)
      if (sMhs > 0) {
        const sUretimTpl = (S.uretim && S.uretim.TPL) || 0;
        const sSonraAb = (S.sonra && S.sonra[ab.key] !== undefined) ? S.sonra[ab.key] : (sHam - sMhs);
        const sBedelli = S.bedelli || 0;
        saatRows += '<td class="fat-col-mhs fat-hover-cell">' + fatFmt(sMhs, 2);
        saatRows += '<div class="fat-popup mor">';
        saatRows += '<div class="fat-popup-title mor">🔄 Mahsup Detayı (saat ' + sk + ')</div>';
        saatRows += '<div class="fat-popup-row"><span>GES Üretimi (T1+T2)</span><span>' + fatFmt(sUretimTpl, 2) + '</span></div>';
        saatRows += '<div class="fat-popup-row"><span>' + ab.ad + ' Tüketim</span><span>' + fatFmt(sHam, 2) + '</span></div>';
        saatRows += '<div class="fat-popup-row sum"><span>↳ Mahsup edilen</span><span style="color:#7c3aed;">' + fatFmt(sMhs, 2) + '</span></div>';
        saatRows += '<div class="fat-popup-row"><span>↳ Şebekeden (net)</span><span>' + fatFmt(sSonraAb, 2) + '</span></div>';
        if (sBedelli > 0) {
          saatRows += '<div class="fat-popup-row"><span>Artan üretim (satış)</span><span style="color:#16a34a;">' + fatFmt(sBedelli, 2) + '</span></div>';
        }
        saatRows += '<div class="fat-popup-sonuc mor"><span>Mahsup oranı</span><span>%' + fatFmt(sHam > 0 ? (sMhs/sHam*100) : 0, 1) + '</span></div>';
        saatRows += '</div>';
        saatRows += '</td>';
      } else {
        saatRows += '<td class="fat-col-mhs">' + fatFmt(sMhs, 2) + '</td>';
      }
      // E.Maliyeti - hover'da popup
      if (sMal !== null && sPtf !== null) {
        const ayYekdem = fatYekdemAl(ay);
        const ayDurum = fatYekdemDurum(ay);
        const yekdemEtiket = ayDurum === 'kesin' ? ' <span style="color:#4ade80; font-size:9px;">✓</span>' : ' <span style="color:#fbbf24; font-size:9px;">⚡tahmini</span>';
        const sToplam_ptf_yek = sPtf + ayYekdem;
        const sCarpim = sToplam_ptf_yek * 1.035;
        saatRows += '<td class="fat-col-mal fat-hover-cell">' + fatFmt(sMal, 3);
        saatRows += '<div class="fat-popup">';
        saatRows += '<div class="fat-popup-title">⚡ Enerji Maliyeti</div>';
        saatRows += '<div class="fat-popup-row"><span>PTF (saat ' + sk + ')</span><span>' + fatFmt(sPtf, 2) + '</span></div>';
        saatRows += '<div class="fat-popup-row"><span>+ YEKDEM' + yekdemEtiket + '</span><span>' + fatFmt(ayYekdem, 2) + '</span></div>';
        saatRows += '<div class="fat-popup-row sum"><span>Toplam</span><span>' + fatFmt(sToplam_ptf_yek, 2) + '</span></div>';
        saatRows += '<div class="fat-popup-row"><span>× 1,035 (dağıtım)</span><span>' + fatFmt(sCarpim, 2) + '</span></div>';
        saatRows += '<div class="fat-popup-row"><span>÷ 1000 (MWh→kWh)</span><span></span></div>';
        saatRows += '<div class="fat-popup-sonuc"><span>E.Maliyeti</span><span>' + fatFmt(sMal, 3) + ' TL/kWh</span></div>';
        saatRows += '</div>';
        saatRows += '</td>';
      } else {
        saatRows += '<td class="fat-col-mal">—</td>';
      }
      // M.Maliyeti - hover popup (PTF bazli saatlik)
      saatRows += '<td class="fat-col-mhsmal fat-hover-cell">' + (sMal !== null ? fatFmt(sMal, 3) : '—');
      saatRows += '<div class="fat-popup mor">';
      saatRows += '<div class="fat-popup-title mor">🟣 Mahsup Maliyeti</div>';
      saatRows += '<div class="fat-popup-row"><span>Birim Fiyat (PTF saatlik)</span><span>' + (sMal !== null ? fatFmt(sMal, 3) : '—') + '</span></div>';
      saatRows += '<div class="fat-popup-sonuc mor"><span>Kaynak</span><span style="font-size:10px;">PTF bazlı<br>Enerji Maliyeti</span></div>';
      saatRows += '</div>';
      saatRows += '</td>';
      // Tük.Bedeli - hover popup
      if (sTukBed !== null) {
        saatRows += '<td class="fat-col-tukbed fat-hover-cell">' + fatFmt(sTukBed, 2);
        saatRows += '<div class="fat-popup">';
        saatRows += '<div class="fat-popup-title">💰 Tüketim Bedeli</div>';
        saatRows += '<div class="fat-popup-row"><span>Ham Tüketim</span><span>' + fatFmt(sHam, 2) + ' kWh</span></div>';
        saatRows += '<div class="fat-popup-row"><span>× E.Maliyeti</span><span>' + fatFmt(sMal, 3) + ' TL/kWh</span></div>';
        saatRows += '<div class="fat-popup-sonuc"><span>Tük.Bedeli</span><span>' + fatFmt(sTukBed, 2) + ' TL</span></div>';
        saatRows += '</div>';
        saatRows += '</td>';
      } else {
        saatRows += '<td class="fat-col-tukbed">—</td>';
      }
      // Mhs.Bedeli - hover popup
      saatRows += '<td class="fat-col-mhsbed fat-hover-cell">' + '−' + fatFmt(sMhsBed, 2);
      saatRows += '<div class="fat-popup mor">';
      saatRows += '<div class="fat-popup-title mor">🟣 Mahsup Bedeli</div>';
      saatRows += '<div class="fat-popup-row"><span>Mahsup</span><span>' + fatFmt(sMhs, 2) + ' kWh</span></div>';
      saatRows += '<div class="fat-popup-row"><span>× M.Maliyeti</span><span>' + fatFmt(mhsMal, 3) + ' TL/kWh</span></div>';
      saatRows += '<div class="fat-popup-sonuc mor"><span>Mhs.Bedeli</span><span>−' + fatFmt(sMhsBed, 2) + ' TL</span></div>';
      saatRows += '</div>';
      saatRows += '</td>';
      // Toplam - hover popup
      if (sToplam !== null) {
        saatRows += '<td class="fat-col-toplam fat-hover-cell">' + fatFmt(sToplam, 2);
        saatRows += '<div class="fat-popup sari">';
        saatRows += '<div class="fat-popup-title sari">💵 Toplam Bedel</div>';
        saatRows += '<div class="fat-popup-row"><span>Tük.Bedeli</span><span>+' + fatFmt(sTukBed, 2) + '</span></div>';
        saatRows += '<div class="fat-popup-row"><span>Mhs.Bedeli</span><span>−' + fatFmt(sMhsBed, 2) + '</span></div>';
        saatRows += '<div class="fat-popup-sonuc sari"><span>Toplam</span><span>' + fatFmt(sToplam, 2) + ' TL</span></div>';
        saatRows += '</div>';
        saatRows += '</td>';
      } else {
        saatRows += '<td class="fat-col-toplam">—</td>';
      }
      saatRows += '</tr>';
    }
    // Gun toplam satiri (saatlik detay icinde)
    // E.Mal = gun etkin ortalama (Σ Tük.Bed / Σ Ham) - saatlik toplamla tutarli
    const gOrtMal = (gHesapVar && gHam > 0) ? (gTukBed / gHam) : null;
    const gToplam = gHesapVar ? (gTukBed - gMhsBed) : null;
    // Gunluk agirlikli birim fiyat (net): gun toplam bedeli / net tuketim
    const gNetTuk = gHam - gMhs;
    const gAgirlik = (gToplam !== null && gNetTuk > 0) ? (gToplam / gNetTuk) : null;
    if (gToplam !== null) {
      fatSeri.push({ gun: g.slice(-2), toplam: gToplam, ham: gHam, mhs: gMhs,
                     netTuk: gNetTuk, agirlik: gAgirlik,
                     brut: (gHam > 0 ? gTukBed / gHam : 0) });
    }
    saatRows += '<tr class="gun-tpl">';
    saatRows += '<td>GÜN</td>';
    if (gesMi) {
      saatRows += '<td style="color:#16a34a;">' + fatFmt(gUret, 2) + '</td>';
      saatRows += '<td style="color:#7c3aed;">' + fatFmt(gUretMhs, 2) + '</td>';
      saatRows += '<td style="color:#16a34a;">' + fatFmt(gUretBedelli, 2) + '</td>';
    }
    saatRows += '<td>' + fatFmt(gHam, 2) + '</td>';
    saatRows += '<td>' + fatFmt(gMhs, 2) + '</td>';
    // E.Maliyeti popup (gun)
    if (gOrtMal !== null) {
      saatRows += '<td class="fat-hover-cell">' + fatFmt(gOrtMal, 3);
      saatRows += '<div class="fat-popup">';
      saatRows += '<div class="fat-popup-title">⚡ Etkin Gün E.Maliyeti</div>';
      saatRows += '<div class="fat-popup-row"><span>Σ Tük.Bedeli</span><span>' + fatFmt(gTukBed, 2) + ' TL</span></div>';
      saatRows += '<div class="fat-popup-row"><span>÷ Σ Ham Tüketim</span><span>' + fatFmt(gHam, 2) + ' kWh</span></div>';
      saatRows += '<div class="fat-popup-sonuc"><span>Etkin Birim</span><span>' + fatFmt(gOrtMal, 3) + ' TL/kWh</span></div>';
      saatRows += '</div>';
      saatRows += '</td>';
    } else {
      saatRows += '<td>—</td>';
    }
    // M.Maliyeti popup (gun) - PTF bazli etkin ortalama
    saatRows += '<td class="fat-hover-cell">' + (gMhs > 0 ? fatFmt(gMhsBed/gMhs, 3) : '—');
    saatRows += '<div class="fat-popup mor">';
    saatRows += '<div class="fat-popup-title mor">🟣 Mahsup Maliyeti</div>';
    saatRows += '<div class="fat-popup-row"><span>Birim Fiyat (PTF saatlik ort.)</span><span>' + (gMhs > 0 ? fatFmt(gMhsBed/gMhs, 3) : '—') + '</span></div>';
    saatRows += '<div class="fat-popup-sonuc mor"><span>Kaynak</span><span style="font-size:10px;">PTF bazlı<br>Enerji Maliyeti</span></div>';
    saatRows += '</div>';
    saatRows += '</td>';
    // Tük.Bedeli popup (gun)
    if (gHesapVar) {
      saatRows += '<td class="fat-hover-cell">' + fatFmt(gTukBed, 2);
      saatRows += '<div class="fat-popup">';
      saatRows += '<div class="fat-popup-title">💰 Gün Tüketim Bedeli</div>';
      saatRows += '<div class="fat-popup-row"><span>Ham Tüketim</span><span>' + fatFmt(gHam, 2) + ' kWh</span></div>';
      saatRows += '<div class="fat-popup-row"><span>× Etkin E.Mal</span><span>' + fatFmt(gOrtMal, 3) + ' TL/kWh</span></div>';
      saatRows += '<div class="fat-popup-sonuc"><span>Gün Tük.Bedeli</span><span>' + fatFmt(gTukBed, 2) + ' TL</span></div>';
      saatRows += '</div>';
      saatRows += '</td>';
    } else {
      saatRows += '<td>—</td>';
    }
    // Mhs.Bedeli popup (gun)
    saatRows += '<td class="fat-hover-cell">' + '−' + fatFmt(gMhsBed, 2);
    saatRows += '<div class="fat-popup mor">';
    saatRows += '<div class="fat-popup-title mor">🟣 Gün Mahsup Bedeli</div>';
    saatRows += '<div class="fat-popup-row"><span>Mahsup</span><span>' + fatFmt(gMhs, 2) + ' kWh</span></div>';
    saatRows += '<div class="fat-popup-row"><span>× M.Maliyeti</span><span>' + fatFmt(mhsMal, 3) + '</span></div>';
    saatRows += '<div class="fat-popup-sonuc mor"><span>Gün Mhs.Bedeli</span><span>−' + fatFmt(gMhsBed, 2) + ' TL</span></div>';
    saatRows += '</div>';
    saatRows += '</td>';
    // Toplam popup (gun)
    if (gToplam !== null) {
      saatRows += '<td class="fat-hover-cell">' + fatFmt(gToplam, 2);
      saatRows += '<div class="fat-popup sari">';
      saatRows += '<div class="fat-popup-title sari">💵 Gün Toplam Bedel</div>';
      saatRows += '<div class="fat-popup-row"><span>Tük.Bedeli</span><span>+' + fatFmt(gTukBed, 2) + '</span></div>';
      saatRows += '<div class="fat-popup-row"><span>Mhs.Bedeli</span><span>−' + fatFmt(gMhsBed, 2) + '</span></div>';
      saatRows += '<div class="fat-popup-sonuc sari"><span>Gün Toplam</span><span>' + fatFmt(gToplam, 2) + ' TL</span></div>';
      saatRows += '</div>';
      saatRows += '</td>';
    } else {
      saatRows += '<td>—</td>';
    }
    saatRows += '</tr>';

    // Ay toplamina ekle
    ayHam += gHam; ayMhs += gMhs;
    if (gHesapVar) { ayTukBed += gTukBed; ayHesapVar = true; }
    ayMhsBed += gMhsBed;

    // Gun satiri (tiklayinca saatler acilir)
    const d = new Date(g);
    const tarihLbl = d.getDate() + ' ' + aylar[d.getMonth()];

    satirlar += '<tr class="fat-gun-satir">';
    satirlar += '<td><span class="fat-expand-ico">▶</span>' + tarihLbl + '</td>';
    if (gesMi) {
      satirlar += '<td style="color:#16a34a;font-weight:700;">' + fatFmt(gUret, 2) + '</td>';
      // Mahsup edilen - popup
      satirlar += '<td class="fat-col-mhs fat-hover-cell" style="color:#7c3aed;">' + fatFmt(gUretMhs, 2);
      satirlar += '<div class="fat-popup mor">';
      satirlar += '<div class="fat-popup-title mor">🔄 Üretimden Mahsup (' + tarihLbl + ')</div>';
      satirlar += '<div class="fat-popup-row"><span>' + ab.ad + ' Üretimi</span><span>' + fatFmt(gUret, 2) + ' kWh</span></div>';
      satirlar += '<div class="fat-popup-row sum"><span>↳ Mahsup edilen</span><span style="color:#7c3aed;">' + fatFmt(gUretMhs, 2) + '</span></div>';
      satirlar += '<div class="fat-popup-sonuc mor"><span>Mahsup oranı</span><span>%' + fatFmt(gUret > 0 ? (gUretMhs/gUret*100) : 0, 1) + '</span></div>';
      satirlar += '</div></td>';
      // Bedelli - popup
      satirlar += '<td class="fat-hover-cell" style="color:#16a34a;font-weight:700;">' + fatFmt(gUretBedelli, 2);
      satirlar += '<div class="fat-popup">';
      satirlar += '<div class="fat-popup-title">💚 Bedelli Üretim (' + tarihLbl + ')</div>';
      satirlar += '<div class="fat-popup-row"><span>Üretim</span><span>' + fatFmt(gUret, 2) + ' kWh</span></div>';
      satirlar += '<div class="fat-popup-row"><span>− Mahsup Edilen</span><span style="color:#7c3aed;">' + fatFmt(gUretMhs, 2) + '</span></div>';
      satirlar += '<div class="fat-popup-sonuc"><span>= Bedelli (Satılan)</span><span style="color:#16a34a;">' + fatFmt(gUretBedelli, 2) + ' kWh</span></div>';
      satirlar += '</div></td>';
    }
    satirlar += '<td class="fat-col-ham">' + fatFmt(gHam, 2) + '</td>';
    satirlar += '<td class="fat-col-mhs">' + fatFmt(gMhs, 2) + '</td>';
    // E.Maliyeti popup (ana gun)
    if (gOrtMal !== null) {
      satirlar += '<td class="fat-col-mal fat-hover-cell">' + fatFmt(gOrtMal, 3);
      satirlar += '<div class="fat-popup">';
      satirlar += '<div class="fat-popup-title">⚡ Etkin Gün E.Maliyeti</div>';
      satirlar += '<div class="fat-popup-row"><span>Σ Tük.Bedeli</span><span>' + fatFmt(gTukBed, 2) + ' TL</span></div>';
      satirlar += '<div class="fat-popup-row"><span>÷ Σ Ham</span><span>' + fatFmt(gHam, 2) + ' kWh</span></div>';
      satirlar += '<div class="fat-popup-sonuc"><span>Etkin Birim</span><span>' + fatFmt(gOrtMal, 3) + ' TL/kWh</span></div>';
      satirlar += '</div>';
      satirlar += '</td>';
    } else {
      satirlar += '<td class="fat-col-mal">—</td>';
    }
    // M.Maliyeti popup (ana gun) - PTF bazli etkin ortalama
    satirlar += '<td class="fat-col-mhsmal fat-hover-cell">' + (gMhs > 0 ? fatFmt(gMhsBed/gMhs, 3) : '—');
    satirlar += '<div class="fat-popup mor">';
    satirlar += '<div class="fat-popup-title mor">🟣 Mahsup Maliyeti</div>';
    satirlar += '<div class="fat-popup-row"><span>Birim Fiyat (PTF saatlik ort.)</span><span>' + (gMhs > 0 ? fatFmt(gMhsBed/gMhs, 3) : '—') + '</span></div>';
    satirlar += '<div class="fat-popup-sonuc mor"><span>Kaynak</span><span style="font-size:10px;">PTF bazlı<br>Enerji Maliyeti</span></div>';
    satirlar += '</div>';
    satirlar += '</td>';
    // Tük.Bedeli popup (ana gun)
    if (gHesapVar) {
      satirlar += '<td class="fat-col-tukbed fat-hover-cell">' + fatFmt(gTukBed, 2);
      satirlar += '<div class="fat-popup">';
      satirlar += '<div class="fat-popup-title">💰 Gün Tüketim Bedeli</div>';
      satirlar += '<div class="fat-popup-row"><span>Ham</span><span>' + fatFmt(gHam, 2) + ' kWh</span></div>';
      satirlar += '<div class="fat-popup-row"><span>× Etkin E.Mal</span><span>' + fatFmt(gOrtMal, 3) + '</span></div>';
      satirlar += '<div class="fat-popup-sonuc"><span>Tük.Bedeli</span><span>' + fatFmt(gTukBed, 2) + ' TL</span></div>';
      satirlar += '</div>';
      satirlar += '</td>';
    } else {
      satirlar += '<td class="fat-col-tukbed">—</td>';
    }
    // Mhs.Bedeli popup (ana gun)
    satirlar += '<td class="fat-col-mhsbed fat-hover-cell">' + '−' + fatFmt(gMhsBed, 2);
    satirlar += '<div class="fat-popup mor">';
    satirlar += '<div class="fat-popup-title mor">🟣 Gün Mahsup Bedeli</div>';
    satirlar += '<div class="fat-popup-row"><span>Mahsup</span><span>' + fatFmt(gMhs, 2) + ' kWh</span></div>';
    satirlar += '<div class="fat-popup-row"><span>× M.Maliyeti</span><span>' + fatFmt(mhsMal, 3) + '</span></div>';
    satirlar += '<div class="fat-popup-sonuc mor"><span>Mhs.Bedeli</span><span>−' + fatFmt(gMhsBed, 2) + ' TL</span></div>';
    satirlar += '</div>';
    satirlar += '</td>';
    // Toplam popup (ana gun)
    if (gToplam !== null) {
      satirlar += '<td class="fat-col-toplam fat-hover-cell">' + fatFmt(gToplam, 2);
      satirlar += '<div class="fat-popup sari">';
      satirlar += '<div class="fat-popup-title sari">💵 Gün Toplam Bedel</div>';
      satirlar += '<div class="fat-popup-row"><span>Tük.Bedeli</span><span>+' + fatFmt(gTukBed, 2) + '</span></div>';
      satirlar += '<div class="fat-popup-row"><span>Mhs.Bedeli</span><span>−' + fatFmt(gMhsBed, 2) + '</span></div>';
      satirlar += '<div class="fat-popup-row"><span>Net Tüketim</span><span>' + fatFmt(gNetTuk, 2) + ' kWh</span></div>';
      satirlar += '<div class="fat-popup-sonuc sari"><span>Gün Toplam</span><span>' + fatFmt(gToplam, 2) + ' TL</span></div>';
      if (gAgirlik !== null) satirlar += '<div class="fat-popup-row" style="border-top:1px dashed rgba(148,163,184,0.3);margin-top:3px;padding-top:4px;"><span>⚖️ Günlük Ağırlıklı</span><span><b>' + fatFmt(gAgirlik, 3) + ' TL/kWh</b></span></div>';
      satirlar += '</div>';
      satirlar += '</td>';
    } else {
      satirlar += '<td class="fat-col-toplam">—</td>';
    }
    satirlar += '</tr>';

    // Saatlik detay satiri (kapali baslar)
    satirlar += '<tr class="fat-saatlik-row"><td colspan="' + (gesMi ? 11 : 8) + '"><div class="fat-saatlik-icerik">';
    satirlar += '<table style="width:100%;border-collapse:collapse;font-size:10px;">';
    satirlar += '<thead><tr style="color:#64748b;">';
    satirlar += '<th style="text-align:left;padding:4px 6px;">Saat</th>';
    if (gesMi) {
      satirlar += '<th style="text-align:right;padding:4px 6px;color:#16a34a;">Üretim (kWh)</th>';
      satirlar += '<th style="text-align:right;padding:4px 6px;color:#7c3aed;">Mahsup Edilen</th>';
      satirlar += '<th style="text-align:right;padding:4px 6px;color:#16a34a;">Bedeli</th>';
    }
    satirlar += '<th style="text-align:right;padding:4px 6px;">Ham (kWh)</th>';
    satirlar += '<th style="text-align:right;padding:4px 6px;">Mahsup (kWh)</th>';
    satirlar += '<th style="text-align:right;padding:4px 6px;">E.Maliyeti (TL/kWh)</th>';
    satirlar += '<th style="text-align:right;padding:4px 6px;">M.Maliyeti (TL/kWh)</th>';
    satirlar += '<th style="text-align:right;padding:4px 6px;">Tük.Bedeli (TL)</th>';
    satirlar += '<th style="text-align:right;padding:4px 6px;">Mhs.Bedeli (TL)</th>';
    satirlar += '<th style="text-align:right;padding:4px 6px;">Toplam (TL)</th>';
    satirlar += '</tr></thead><tbody>' + saatRows + '</tbody></table>';
    satirlar += '</div></td></tr>';
  });

  // Ay toplam satiri
  // E.Mal = ay etkin ortalama (Σ Tük.Bed / Σ Ham) - saatlik toplamla tutarli
  const ayOrtMal = (ayHesapVar && ayHam > 0) ? (ayTukBed / ayHam) : null;
  const ayToplam = ayHesapVar ? (ayTukBed - ayMhsBed) : null;

  satirlar += '<tr class="fat-toplam">';
  satirlar += '<td>TOPLAM</td>';
  if (gesMi) {
    satirlar += '<td style="color:#16a34a;">' + fatFmt(ayUretim, 2) + '</td>';
    satirlar += '<td style="color:#7c3aed;">' + fatFmt(ayUretMhs, 2) + '</td>';
    satirlar += '<td style="color:#16a34a;">' + fatFmt(ayUretBedelli, 2) + '</td>';
  }
  satirlar += '<td>' + fatFmt(ayHam, 2) + '</td>';
  satirlar += '<td>' + fatFmt(ayMhs, 2) + '</td>';
  // E.Maliyeti popup (TOPLAM)
  if (ayOrtMal !== null) {
    satirlar += '<td class="fat-hover-cell">' + fatFmt(ayOrtMal, 3);
    satirlar += '<div class="fat-popup">';
    satirlar += '<div class="fat-popup-title">⚡ Etkin Ay E.Maliyeti</div>';
    satirlar += '<div class="fat-popup-row"><span>Σ Tük.Bedeli</span><span>' + fatFmt(ayTukBed, 2) + ' TL</span></div>';
    satirlar += '<div class="fat-popup-row"><span>÷ Σ Ham</span><span>' + fatFmt(ayHam, 2) + ' kWh</span></div>';
    satirlar += '<div class="fat-popup-sonuc"><span>Etkin Birim</span><span>' + fatFmt(ayOrtMal, 3) + ' TL/kWh</span></div>';
    satirlar += '</div>';
    satirlar += '</td>';
  } else {
    satirlar += '<td>—</td>';
  }
  // M.Maliyeti popup (TOPLAM) - PTF bazli etkin ortalama
  satirlar += '<td class="fat-hover-cell">' + (ayMhs > 0 ? fatFmt(ayMhsBed/ayMhs, 3) : '—');
  satirlar += '<div class="fat-popup mor">';
  satirlar += '<div class="fat-popup-title mor">🟣 Mahsup Maliyeti</div>';
  satirlar += '<div class="fat-popup-row"><span>Birim Fiyat (PTF saatlik ort.)</span><span>' + (ayMhs > 0 ? fatFmt(ayMhsBed/ayMhs, 3) : '—') + '</span></div>';
  satirlar += '<div class="fat-popup-sonuc mor"><span>Kaynak</span><span style="font-size:10px;">PTF bazlı<br>Enerji Maliyeti</span></div>';
  satirlar += '</div>';
  satirlar += '</td>';
  // Tük.Bedeli popup (TOPLAM)
  if (ayHesapVar) {
    satirlar += '<td class="fat-hover-cell">' + fatFmt(ayTukBed, 2);
    satirlar += '<div class="fat-popup">';
    satirlar += '<div class="fat-popup-title">💰 Ay Tüketim Bedeli</div>';
    satirlar += '<div class="fat-popup-row"><span>Ham</span><span>' + fatFmt(ayHam, 2) + ' kWh</span></div>';
    satirlar += '<div class="fat-popup-row"><span>× Etkin E.Mal</span><span>' + fatFmt(ayOrtMal, 3) + '</span></div>';
    satirlar += '<div class="fat-popup-sonuc"><span>Tük.Bedeli</span><span>' + fatFmt(ayTukBed, 2) + ' TL</span></div>';
    satirlar += '</div>';
    satirlar += '</td>';
  } else {
    satirlar += '<td>—</td>';
  }
  // Mhs.Bedeli popup (TOPLAM)
  satirlar += '<td class="fat-hover-cell">' + '−' + fatFmt(ayMhsBed, 2);
  satirlar += '<div class="fat-popup mor">';
  satirlar += '<div class="fat-popup-title mor">🟣 Ay Mahsup Bedeli</div>';
  satirlar += '<div class="fat-popup-row"><span>Mahsup</span><span>' + fatFmt(ayMhs, 2) + ' kWh</span></div>';
  satirlar += '<div class="fat-popup-row"><span>× M.Maliyeti</span><span>' + fatFmt(mhsMal, 3) + '</span></div>';
  satirlar += '<div class="fat-popup-sonuc mor"><span>Mhs.Bedeli</span><span>−' + fatFmt(ayMhsBed, 2) + ' TL</span></div>';
  satirlar += '</div>';
  satirlar += '</td>';
  // Toplam popup (TOPLAM)
  if (ayToplam !== null) {
    satirlar += '<td class="fat-hover-cell">' + fatFmt(ayToplam, 2);
    satirlar += '<div class="fat-popup sari">';
    satirlar += '<div class="fat-popup-title sari">💵 Ay Toplam Bedel</div>';
    satirlar += '<div class="fat-popup-row"><span>Tük.Bedeli</span><span>+' + fatFmt(ayTukBed, 2) + '</span></div>';
    satirlar += '<div class="fat-popup-row"><span>Mhs.Bedeli</span><span>−' + fatFmt(ayMhsBed, 2) + '</span></div>';
    satirlar += '<div class="fat-popup-sonuc sari"><span>Ay Toplam</span><span>' + fatFmt(ayToplam, 2) + ' TL</span></div>';
    satirlar += '</div>';
    satirlar += '</td>';
  } else {
    satirlar += '<td>—</td>';
  }
  satirlar += '</tr>';

  // Kart HTML (sade - sadece baslik + tablo)
  // FATURA HESAP KALEMLERİ (ay toplam)
  // Mahsuplasma kWh: abonenin AY TOPLAM mahsup payi (mahsuplasma sekmesi ile uyumlu)
  //   = A.tuketim[ab.key] - A.sonra[ab.key]
  //   AKS3 icin ornek: 120.516 - 51.741 = 68.775 kWh
  const ayHamGercek = (A.tuketim && A.tuketim[ab.key]) || 0;
  const aySnrGercek = (A.sonra && A.sonra[ab.key]) || 0;
  const ayMhsGercek = ayHamGercek - aySnrGercek;  // 68.775 (AKS3 icin)

  const enerjiBedeli = ayHesapVar ? ayTukBed : 0;        // Aktif Enerji Tuketimi (Tuketim Bedeli)
  const mahsuplasma = ayMhsBed;                          // PTF-bazli saatlik mahsup degeri toplami (kacinilan tuketim bedeli)
  const dagitimBedeli = ayHamGercek * FAT_DB_BIRIM;       // Ham (ay toplam) × 1,182457
  const toplam = enerjiBedeli - mahsuplasma + dagitimBedeli;
  const kdv = toplam * FAT_KDV;                           // Toplam × %20
  const odenecek = toplam + kdv;

  // AYLIK AGIRLIKLI BIRIM FIYAT
  const netEnerji = enerjiBedeli - mahsuplasma;           // mahsup sonrasi net enerji bedeli
  const ayAgirlikNet = (aySnrGercek > 0) ? (netEnerji / aySnrGercek) : null;   // net tuketime bolunmus
  const ayAgirlikBrut = (ayHamGercek > 0) ? (enerjiBedeli / ayHamGercek) : null; // brut tuketime bolunmus

  // Kart HTML
  let h = '<div class="fat-abone-kart ' + ab.kls + '">';
  h += '<div class="fat-abone-head"><div class="fat-abone-icon">' + ab.icon + '</div>';
  h += '<div><div class="fat-abone-name">' + ab.ad + '</div><div class="fat-abone-sub">' + ab.sub + '</div></div></div>';

  // ===== URETIM DETAYI (sadece GES aboneleri: T1, T2) =====
  if (gesMi) {
    h += '<div class="fat-uretim-detay">';
    h += '<div class="fat-ud-title">☀️ Üretim Detayı (kWh) — Asıl İş: GES</div>';
    h += '<div class="fat-ud-grid">';
    h += '<div class="fat-ud-row sebeke"><div class="fat-ud-lbl"><b>Toplam Üretim (' + (FAT_AY_ISIM_MAP[ay] || ay) + ')</b></div><div class="fat-ud-val sat"><b>' + fatFmt(ayUretim, 2) + '</b></div></div>';
    h += '<div class="fat-ud-row"><div class="fat-ud-lbl">Günlük Ortalama</div><div class="fat-ud-val uret">' + fatFmt(gunler.length > 0 ? ayUretim/gunler.length : 0, 2) + '</div></div>';
    h += '<div class="fat-ud-row"><div class="fat-ud-lbl">MWh Karşılığı</div><div class="fat-ud-val uret">' + fatFmt(ayUretim/1000, 2) + ' MWh</div></div>';
    h += '</div>';
    h += '</div>';
  }

  // ===== TUKETIM DETAYI (kWh) =====
  h += '<div class="fat-tuketim-detay">';
  h += '<div class="fat-td-title">📊 Tüketim Detayı (kWh)</div>';
  h += '<div class="fat-td-grid">';
  h += '<div class="fat-td-row"><div class="fat-td-lbl">Ham Tüketim</div><div class="fat-td-val ham">' + fatFmt(ayHamGercek, 2) + '</div></div>';
  h += '<div class="fat-td-row"><div class="fat-td-lbl">Mahsup Edilen Enerji</div><div class="fat-td-val mhs">' + fatFmt(ayMhsGercek, 2) + '</div></div>';
  h += '<div class="fat-td-row sonra"><div class="fat-td-lbl"><b>Mahsup Sonrası Tüketim</b></div><div class="fat-td-val snr"><b>' + fatFmt(aySnrGercek, 2) + '</b></div></div>';
  h += '</div>';
  h += '</div>';

  // ===== FATURA OZET KARTI =====
  h += '<div class="fat-fatura-ozet">';
  h += '<div class="fat-fo-title">🧾 ' + (FAT_AY_ISIM_MAP[ay] || ay) + ' Fatura Detayı (TL)</div>';

  // 1) Aktif Enerji Tuketimi (etkin birim fiyat = tutar/ham)
  const etkinBirim = (ayHamGercek > 0 && enerjiBedeli !== null) ? (enerjiBedeli / ayHamGercek) : null;
  h += '<div class="fat-fo-row" style="border-bottom:none;padding-bottom:2px;">';
  h += '<div class="fat-fo-lbl"><span class="fat-fo-no">1)</span> Aktif Enerji Tüketimi</div>';
  h += '<div class="fat-fo-val">' + fatFmt(enerjiBedeli, 2) + ' <span class="fat-fo-tl">TL</span></div>';
  h += '</div>';
  // Alt satir: Ham × Birim
  h += '<div class="fat-fo-altrow">';
  h += '<span class="fat-fo-altlbl">' + fatFmt(ayHamGercek, 2) + ' kWh × ' + (etkinBirim !== null ? fatFmt(etkinBirim, 3) : '—') + ' TL/kWh</span>';
  h += '<span class="fat-fo-altaciklama">Ortalama Saatlik Birim Fiyat</span>';
  h += '</div>';

  // 2) Mahsuplasma
  h += '<div class="fat-fo-row" style="border-bottom:none;padding-bottom:2px;">';
  h += '<div class="fat-fo-lbl"><span class="fat-fo-no">2)</span> Mahsuplaşma (−)</div>';
  h += '<div class="fat-fo-val negatif">−' + fatFmt(mahsuplasma, 2) + ' <span class="fat-fo-tl">TL</span></div>';
  h += '</div>';
  h += '<div class="fat-fo-altrow">';
  h += '<span class="fat-fo-altlbl">' + fatFmt(ayMhsGercek, 2) + ' kWh × ' + (ayMhsGercek > 0 ? fatFmt(mahsuplasma/ayMhsGercek, 3) : '—') + ' TL/kWh</span>';
  h += '<span class="fat-fo-altaciklama">PTF bazlı (saatlik ort.) — kaçınılan enerji bedeli</span>';
  h += '</div>';

  // 3) Dagitim Bedeli
  h += '<div class="fat-fo-row" style="border-bottom:none;padding-bottom:2px;">';
  h += '<div class="fat-fo-lbl"><span class="fat-fo-no">3)</span> Dağıtım Bedeli</div>';
  h += '<div class="fat-fo-val">' + fatFmt(dagitimBedeli, 2) + ' <span class="fat-fo-tl">TL</span></div>';
  h += '</div>';
  h += '<div class="fat-fo-altrow">';
  h += '<span class="fat-fo-altlbl">' + fatFmt(ayHamGercek, 2) + ' kWh × 1,182 TL/kWh</span>';
  h += '<span class="fat-fo-altaciklama">OG Tek Terim Sanayi Dağıtım Bedeli</span>';
  h += '</div>';

  // Toplam (vurgulu)
  h += '<div class="fat-fo-row toplam">';
  h += '<div class="fat-fo-lbl"><b>TOPLAM</b> <span class="fat-fo-aciklama">(1 − 2 + 3)</span></div>';
  h += '<div class="fat-fo-val"><b>' + fatFmt(toplam, 2) + '</b> <span class="fat-fo-tl">TL</span></div>';
  h += '</div>';

  // KDV
  h += '<div class="fat-fo-row">';
  h += '<div class="fat-fo-lbl">KDV (%20) <span class="fat-fo-aciklama">(Toplam × 0,20)</span></div>';
  h += '<div class="fat-fo-val">' + fatFmt(kdv, 2) + ' <span class="fat-fo-tl">TL</span></div>';
  h += '</div>';

  // ODENECEK FATURA
  h += '<div class="fat-fo-odenecek">';
  h += '<div class="fat-fo-od-lbl">💵 ÖDENECEK FATURA TUTARI</div>';
  h += '<div class="fat-fo-od-val">' + fatFmt(odenecek, 2) + ' <span style="font-size:14px;color:#94a3b8;font-weight:700;">TL</span></div>';
  h += '</div>';

  // AYLIK AGIRLIKLI BIRIM FIYAT karti
  h += '<div style="display:flex;gap:8px;margin-top:10px;">';
  h += '<div style="flex:1;background:linear-gradient(135deg,rgba(52,210,235,0.08),rgba(52,210,235,0.02));border:1px solid rgba(52,210,235,0.25);border-radius:10px;padding:10px 12px;text-align:center;">';
  h += '<div style="font-size:9px;color:#0891b2;font-weight:800;text-transform:uppercase;letter-spacing:0.8px;">⚖️ Aylık Ağırlıklı (Net)</div>';
  h += '<div style="font-size:18px;font-weight:900;color:#0e7490;margin-top:3px;">' + (ayAgirlikNet !== null ? fatFmt(ayAgirlikNet, 4) : '—') + '<span style="font-size:10px;color:#94a3b8;"> TL/kWh</span></div>';
  h += '<div style="font-size:9px;color:#94a3b8;margin-top:2px;">' + fatFmt(netEnerji, 0) + ' TL ÷ ' + fatFmt(aySnrGercek, 0) + ' kWh</div>';
  h += '</div>';
  h += '<div style="flex:1;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;text-align:center;">';
  h += '<div style="font-size:9px;color:#64748b;font-weight:800;text-transform:uppercase;letter-spacing:0.8px;">Aylık Brüt</div>';
  h += '<div style="font-size:18px;font-weight:900;color:#475569;margin-top:3px;">' + (ayAgirlikBrut !== null ? fatFmt(ayAgirlikBrut, 4) : '—') + '<span style="font-size:10px;color:#94a3b8;"> TL/kWh</span></div>';
  h += '<div style="font-size:9px;color:#94a3b8;margin-top:2px;">mahsup öncesi</div>';
  h += '</div>';
  h += '</div>';

  h += '</div>';
  // ===== /FATURA OZET KARTI =====

  // ===== A3: MAHSUP OLMASAYDI (gercek fatura kiyasi) =====
  if (ab.key === 'A3') {
    const mahsupsuzToplam = enerjiBedeli + dagitimBedeli;   // mahsup yok
    const mahsupsuzKdv = mahsupsuzToplam * FAT_KDV;
    const mahsupsuzOdenecek = mahsupsuzToplam + mahsupsuzKdv;
    const mahsupFaydasi = mahsupsuzOdenecek - odenecek;     // tasarruf (KDV dahil)
    h += '<div class="fat-fatura-ozet" style="border-color:rgba(220,38,38,0.25);background:linear-gradient(135deg,rgba(220,38,38,0.03),rgba(248,113,113,0.02));">';
    h += '<div class="fat-fo-title" style="color:#b91c1c;">⚠️ Mahsup Olmasaydı (Gerçek Fatura Kıyası)</div>';
    h += '<div class="fat-fo-row" style="border-bottom:none;padding-bottom:2px;">';
    h += '<div class="fat-fo-lbl">Aktif Enerji <span class="fat-fo-aciklama">(mahsupsuz, tüm tüketim)</span></div>';
    h += '<div class="fat-fo-val">' + fatFmt(enerjiBedeli, 2) + ' <span class="fat-fo-tl">TL</span></div>';
    h += '</div>';
    h += '<div class="fat-fo-row" style="border-bottom:none;padding-bottom:2px;">';
    h += '<div class="fat-fo-lbl">Dağıtım Bedeli</div>';
    h += '<div class="fat-fo-val">' + fatFmt(dagitimBedeli, 2) + ' <span class="fat-fo-tl">TL</span></div>';
    h += '</div>';
    h += '<div class="fat-fo-row" style="border-bottom:none;padding-bottom:2px;">';
    h += '<div class="fat-fo-lbl">KDV (%20)</div>';
    h += '<div class="fat-fo-val">' + fatFmt(mahsupsuzKdv, 2) + ' <span class="fat-fo-tl">TL</span></div>';
    h += '</div>';
    h += '<div class="fat-fo-row toplam" style="border-color:rgba(220,38,38,0.3);">';
    h += '<div class="fat-fo-lbl"><b>MAHSUPSUZ ÖDENECEK</b></div>';
    h += '<div class="fat-fo-val"><b style="color:#dc2626;">' + fatFmt(mahsupsuzOdenecek, 2) + '</b> <span class="fat-fo-tl">TL</span></div>';
    h += '</div>';
    h += '<div class="fat-fo-odenecek" style="background:linear-gradient(135deg,#16a34a,#22c55e);">';
    h += '<div class="fat-fo-od-lbl">💚 MAHSUP FAYDASI (Tasarruf)</div>';
    h += '<div class="fat-fo-od-val">' + fatFmt(mahsupFaydasi, 2) + ' <span style="font-size:14px;color:#dcfce7;font-weight:700;">TL</span></div>';
    h += '</div>';
    h += '<div style="font-size:10px;color:#94a3b8;margin-top:8px;text-align:center;font-weight:600;">Mahsuplu fatura: ' + fatFmt(odenecek, 2) + ' TL &nbsp;·&nbsp; Mahsupsuz: ' + fatFmt(mahsupsuzOdenecek, 2) + ' TL</div>';
    h += '</div>';
  }
  // ===== /A3 MAHSUPSUZ =====

  // ===== GORSEL: GUNLUK AGIRLIKLI BIRIM FIYAT GRAFIGI =====
  window.fatGrafikVeri = {
    seri: fatSeri,
    abone: ab.key,
    ad: ab.ad,
    ayAgirlikNet: ayAgirlikNet,
    odenecek: odenecek,
    mahsupsuz: (ab.key === 'A3') ? (enerjiBedeli + dagitimBedeli) * (1 + FAT_KDV) : null
  };
  if (fatSeri.length > 0) {
    h += '<div class="fat-chart-card" style="margin-top:14px;">';
    h += '<div class="fat-chart-head"><div class="fat-chart-baslik">⚖️ Günlük Ağırlıklı Birim Fiyat (TL/kWh)</div>';
    h += '<div style="font-size:10px;color:#94a3b8;font-weight:700;">Net vs Brüt · gün bazlı</div></div>';
    h += '<div style="position:relative;height:220px;width:100%;"><canvas id="fat-grafik-fiyat"></canvas></div>';
    h += '</div>';
  }
  // ===== /GORSEL =====

  // ===== URETIM FATURASI (sadece GES: T1, T2) =====
  if (gesMi) {
    const uretimGeliri = ayUretBedelli * FAT_SANAYI_AKTIF;        // bedelli × 2,909687
    const skbKesinti = ayUretim * FAT_URETIM_SKB;                 // toplam uretim × 0,656008
    const netUretim = uretimGeliri - skbKesinti;
    h += '<div class="fat-uretim-fatura">';
    h += '<div class="fat-uf-baslik">☀️ ÜRETİM FATURASI</div>';
    // 1) Uretim geliri
    h += '<div class="fat-fo-row">';
    h += '<div class="fat-fo-lbl"><span class="fat-fo-no">1)</span> Üretim Geliri <span class="fat-fo-aciklama">(Bedelli × 2,909687)</span></div>';
    h += '<div class="fat-fo-val" style="color:#16a34a;">' + fatFmt(uretimGeliri, 2) + ' <span class="fat-fo-tl">TL</span></div>';
    h += '</div>';
    h += '<div class="fat-fo-altrow"><div class="fat-fo-altlbl">' + fatFmt(ayUretBedelli, 2) + ' kWh × 2,909687</div></div>';
    // 2) SKB kesinti
    h += '<div class="fat-fo-row">';
    h += '<div class="fat-fo-lbl"><span class="fat-fo-no">2)</span> Sistem Kullanım Bedeli (−) <span class="fat-fo-aciklama">(Toplam Üretim × 0,656008)</span></div>';
    h += '<div class="fat-fo-val" style="color:#dc2626;">−' + fatFmt(skbKesinti, 2) + ' <span class="fat-fo-tl">TL</span></div>';
    h += '</div>';
    h += '<div class="fat-fo-altrow"><div class="fat-fo-altlbl">' + fatFmt(ayUretim, 2) + ' kWh × 0,656008</div><div class="fat-fo-altaciklama">mahsup + bedelli toplamı</div></div>';
    // Net
    h += '<div class="fat-uf-net">';
    h += '<div class="fat-uf-net-lbl">💰 NET ÜRETİM GELİRİ <span style="font-size:9px;color:#94a3b8;">(1 − 2)</span></div>';
    h += '<div class="fat-uf-net-val" style="color:' + (netUretim >= 0 ? '#16a34a' : '#dc2626') + ';">' + fatFmt(netUretim, 2) + ' <span style="font-size:14px;color:#94a3b8;font-weight:700;">TL</span></div>';
    h += '</div>';
    h += '</div>';
  }
  // ===== /URETIM FATURASI =====

  // ===== FAYDA ANALIZI (sadece GES: T1, T2) =====
  if (gesMi) {
    const mahsupFayda = ayUretMhsBed;                     // PTF-bazli (kacinilan tuketim bedeli)
    const bedelliGelir = ayUretBedelli * FAT_SANAYI_AKTIF; // bedelli × 2,909687 (satis - degismedi)
    const skbTop = ayUretim * FAT_URETIM_SKB;              // (mahsup+bedelli) × 0,656008
    const toplamFayda = mahsupFayda + bedelliGelir - skbTop;
    h += '<div class="fat-fayda">';
    h += '<div class="fat-fayda-baslik">📊 FAYDA ANALİZİ</div>';
    // 1) Mahsup faydasi
    h += '<div class="fat-fayda-row fat-hover-cell">';
    h += '<div class="fat-fayda-lbl"><span class="fat-fo-no">+</span> Mahsup Faydası</div>';
    h += '<div class="fat-fayda-val" style="color:#7c3aed;">' + fatFmt(mahsupFayda, 2) + ' <span style="font-size:10px;color:#94a3b8;">TL</span></div>';
    h += '<div class="fat-popup mor">';
    h += '<div class="fat-popup-title mor">🔄 Mahsup Faydası</div>';
    h += '<div class="fat-popup-row"><span>Mahsup Edilen Üretim</span><span>' + fatFmt(ayUretMhs, 2) + ' kWh</span></div>';
    h += '<div class="fat-popup-row"><span>Birim Fiyat (PTF saatlik ort.)</span><span>' + (ayUretMhs > 0 ? fatFmt(mahsupFayda/ayUretMhs, 3) : '—') + '</span></div>';
    h += '<div class="fat-popup-sonuc mor"><span>= Mahsup Faydası</span><span>' + fatFmt(mahsupFayda, 2) + ' TL</span></div>';
    h += '<div class="fat-popup-aciklama">Mahsup sayesinde ödenmeyen tüketim bedeli</div>';
    h += '</div></div>';
    // 2) Bedelli geliri
    h += '<div class="fat-fayda-row fat-hover-cell">';
    h += '<div class="fat-fayda-lbl"><span class="fat-fo-no">+</span> Bedelli Geliri (Satış)</div>';
    h += '<div class="fat-fayda-val" style="color:#16a34a;">' + fatFmt(bedelliGelir, 2) + ' <span style="font-size:10px;color:#94a3b8;">TL</span></div>';
    h += '<div class="fat-popup">';
    h += '<div class="fat-popup-title">💚 Bedelli Geliri</div>';
    h += '<div class="fat-popup-row"><span>Bedelli (Satılan) Üretim</span><span>' + fatFmt(ayUretBedelli, 2) + ' kWh</span></div>';
    h += '<div class="fat-popup-row"><span>Birim Fiyat (OG aktif)</span><span>2,909687</span></div>';
    h += '<div class="fat-popup-sonuc"><span>= Bedelli Geliri</span><span>' + fatFmt(bedelliGelir, 2) + ' TL</span></div>';
    h += '<div class="fat-popup-aciklama">Şebekeye satılan üretimden gelen</div>';
    h += '</div></div>';
    // 3) SKB kesinti
    h += '<div class="fat-fayda-row fat-hover-cell">';
    h += '<div class="fat-fayda-lbl"><span class="fat-fo-no">−</span> Sistem Kullanım Bedeli</div>';
    h += '<div class="fat-fayda-val" style="color:#dc2626;">−' + fatFmt(skbTop, 2) + ' <span style="font-size:10px;color:#94a3b8;">TL</span></div>';
    h += '<div class="fat-popup kirmizi">';
    h += '<div class="fat-popup-title" style="color:#dc2626;">⚡ Sistem Kullanım Bedeli</div>';
    h += '<div class="fat-popup-row"><span>Toplam Üretim</span><span>' + fatFmt(ayUretim, 2) + ' kWh</span></div>';
    h += '<div class="fat-popup-row"><span>↳ Mahsup edilen</span><span>' + fatFmt(ayUretMhs, 2) + '</span></div>';
    h += '<div class="fat-popup-row"><span>↳ Bedelli</span><span>' + fatFmt(ayUretBedelli, 2) + '</span></div>';
    h += '<div class="fat-popup-row"><span>SKB Birim</span><span>0,656008</span></div>';
    h += '<div class="fat-popup-sonuc" style="background:rgba(220,38,38,0.1);"><span>= SKB Kesintisi</span><span style="color:#dc2626;">' + fatFmt(skbTop, 2) + ' TL</span></div>';
    h += '<div class="fat-popup-aciklama">Tüm üretim için sistem kullanım bedeli</div>';
    h += '</div></div>';
    // Toplam fayda
    h += '<div class="fat-fayda-toplam">';
    h += '<div class="fat-fayda-top-lbl">🎯 TOPLAM FAYDA <span style="font-size:9px;color:#94a3b8;">(Mahsup + Bedelli − SKB)</span></div>';
    h += '<div class="fat-fayda-top-val" style="color:' + (toplamFayda >= 0 ? '#16a34a' : '#dc2626') + ';">' + fatFmt(toplamFayda, 2) + ' <span style="font-size:14px;color:#94a3b8;font-weight:700;">TL</span></div>';
    h += '</div>';
    h += '</div>';
  }
  // ===== /FAYDA ANALIZI =====

  // Detay tablo basligi
  h += '<div class="fat-detay-lbl">📋 Aylık Detay Tablosu</div>';
  h += '<div class="fat-tablo-wrap"><table class="fat-table">';
  h += '<thead><tr>';
  h += '<th>Tarih</th>';
  if (gesMi) {
    h += '<th style="color:#16a34a;">Üretim (kWh)</th>';
    h += '<th style="color:#7c3aed;">Mahsup Edilen</th>';
    h += '<th style="color:#16a34a;">Bedeli</th>';
  }
  h += '<th>Ham Tük. (kWh)</th>';
  h += '<th>Mahsup (kWh)</th>';
  h += '<th>E.Maliyeti (TL/kWh)</th>';
  h += '<th>M.Maliyeti (TL/kWh)</th>';
  h += '<th>Tük.Bedeli (TL)</th>';
  h += '<th>Mhs.Bedeli (TL)</th>';
  h += '<th>Toplam Bedel (TL)</th>';
  h += '</tr></thead><tbody>' + satirlar + '</tbody></table></div>';
  h += '</div>';
  return h;
}

// Event delegation - gun satirina tiklayinca saatlik detay
if (!window.fatDelegated) {
  document.addEventListener('click', function(e) {
    const tr = e.target.closest('tr.fat-gun-satir');
    if (!tr) return;
    tr.classList.toggle('acik');
    const sonraki = tr.nextElementSibling;
    if (sonraki && sonraki.classList.contains('fat-saatlik-row')) {
      sonraki.classList.toggle('acik');
    }
  });
  window.fatDelegated = true;
}

// Akilli popup konumlama - hover olunca ust/alt yer durumuna gore yon belirle
if (!window.fatPopupDelegated) {
  document.addEventListener('mouseover', function(e) {
    const cell = e.target.closest('.fat-hover-cell');
    if (!cell) return;
    const popup = cell.querySelector('.fat-popup');
    if (!popup) return;
    // Hucrenin ekrandaki konumu
    const rect = cell.getBoundingClientRect();
    // Popup yuksekligini tahmin et (gorunur degilse olc)
    const popupYukseklik = popup.offsetHeight || 160;
    const ustBosluk = rect.top;            // hucre ustunde kalan alan
    const altBosluk = window.innerHeight - rect.bottom;  // hucre altinda kalan alan
    // Eger ustte yeterli yer varsa YUKARI ac, yoksa ASAGI ac
    if (ustBosluk > popupYukseklik + 20) {
      popup.classList.add('yukari');
      popup.classList.remove('asagi');
    } else {
      popup.classList.add('asagi');
      popup.classList.remove('yukari');
    }
  });
  window.fatPopupDelegated = true;
}
// ====================== FATURALANDIRMA SEKMESI SONU ======================

// ====================== ANTMINER SONU ======================

// Service worker DEVRE DISI - cache sorunlarini onlemek icin
// if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js'); }
// Mevcut SW kaydini kaldir
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations().then(function(regs) {
    regs.forEach(function(r) { r.unregister(); });
  });
}
</script>
</body></html>"""

@app.route("/manifest.json")
def manifest():
    return Response(MANIFEST, mimetype="application/manifest+json")

@app.route("/icon.svg")
def icon():
    return Response(ICON_SVG, mimetype="image/svg+xml")

@app.route("/sw.js")
def sw():
    return Response("self.addEventListener('fetch', function(e) {});", mimetype="application/javascript")

@app.route("/")
def index():
    if "kullanici" not in session:
        return redirect("/giris")
    return render_template_string(PANEL_HTML, kullanici=session["kullanici"], rol=session["rol"], panel_versiyon=PANEL_VERSIYON, panel_versiyon_tarih=PANEL_VERSIYON_TARIH, sistem_durum=sistem_durum_hesapla())

@app.route("/giris", methods=["GET","POST"])
def giris():
    if request.method == "POST":
        k = request.form.get("kullanici","")
        s = hashlib.sha256(request.form.get("sifre","").encode()).hexdigest()
        if k in KULLANICILAR and KULLANICILAR[k]["sifre"] == s:
            session["kullanici"] = k
            session["rol"] = KULLANICILAR[k]["rol"]
            return redirect("/")
        return render_template_string(LOGIN_HTML, hata="Kullanıcı adı veya şifre hatalı!")
    return render_template_string(LOGIN_HTML, hata=None)

@app.route("/cikis")
def cikis():
    session.clear()
    return redirect("/giris")

@app.route("/api/osos")
def osos():
    if "kullanici" not in session:
        return jsonify({"hata":"yetkisiz"}), 401
    data = github_oku("2026_osos_endeks.json")
    if not data:
        return jsonify({})
    aysonu = github_oku("osos_aysonu.json") or {}
    for key, abone in data.items():
        aylar = {}
        for gun, saatler in abone.get('veri', {}).items():
            ay = gun[:7]
            if ay not in aylar:
                aylar[ay] = {"cekis": 0, "veris": 0, "gun_sayisi": 0}
            for s, v in saatler.items():
                aylar[ay]['cekis'] += v.get('cekis', 0)
                aylar[ay]['veris'] += v.get('veris', 0)
            aylar[ay]['gun_sayisi'] += 1
        aysonu_abone = aysonu.get(key, {})
        for ay, veri in aylar.items():
            endeks = aysonu_abone.get(ay, {})
            endeks_cekis = endeks.get('cekis_kwh', 0)
            endeks_veris = endeks.get('veris_kwh', 0)
            fark_c = abs(veri['cekis'] - endeks_cekis) if endeks_cekis > 0 else None
            fark_v = abs(veri['veris'] - endeks_veris) if endeks_veris > 0 else None
            cekis_ok = fark_c is None or fark_c < DOGRULAMA_TOLERANS
            veris_ok = fark_v is None or fark_v < DOGRULAMA_TOLERANS
            if (endeks_cekis > 0 or endeks_veris > 0) and cekis_ok and veris_ok:
                veri['dogrulama'] = "ok"
            elif (endeks_cekis > 0 or endeks_veris > 0) and not (cekis_ok and veris_ok):
                veri['dogrulama'] = "hata"
                veri['endeks_cekis'] = endeks_cekis
                veri['endeks_veris'] = endeks_veris
            else:
                veri['dogrulama'] = "bekliyor"
        abone['aylar'] = aylar
    return jsonify(data)

@app.route("/api/osos_raw")
def osos_raw():
    """3 abone icin ham saatlik veri - Veri sekmesi kullanir."""
    if "kullanici" not in session:
        return jsonify({"hata":"yetkisiz"}), 401
    data = github_oku("2026_osos_endeks.json")
    if not data:
        return jsonify({})
    return jsonify(data)

@app.route("/api/aylik_ptf")
def aylik_ptf_endpoint():
    """Faturalandirma sekmesi icin aylik_ptf.json'u dondur."""
    if "kullanici" not in session:
        return jsonify({"hata":"yetkisiz"}), 401
    data = github_oku("aylik_ptf.json")
    if not data:
        return jsonify({})
    return jsonify(data)


# ============================================================
# RAPOR ENDPOINT - GitHub commits + saglik kontrolu
# ============================================================
_RAPOR_CACHE = {"ts": 0, "veri": None}
_RAPOR_TTL = 120  # 2 dk

_DOSYA_TIPLERI = {
    "ofis_panel.py":         ("PANEL",    "Panel surumu"),
    "main.py":               ("PANEL",    "EPIAS cron kodu"),
    "arsiv_kaydet.py":       ("PANEL",    "Arsiv kodu"),
    "aylik_ptf.json":        ("PTF",      "EPIAS Piyasa Takas Fiyati"),
    "2026_osos_endeks.json": ("OSOS",     "Sayac okumalari"),
    "antminer_panel.json":   ("ANTMINER", "Pi saha verisi"),
    "sinyal.json":           ("SINYAL",   "Yarinki sinyal"),
    "gunluk_arsiv.json":     ("KARLILIK", "Gunluk karlilik arsivi"),
    "son_gonderim.json":     ("WHATSAPP", "Mesaj takibi"),
    "bekleyen_onaylar.json": ("ONAY",     "Bekleyen onaylar"),
}

def _dosya_etiketi(d):
    if d.startswith("arsiv_f2pool_"):  return ("ARSIV", "havuz saatlik")
    if d.startswith("arsiv_cihaz_"):   return ("ARSIV", "cihaz saatlik")
    if d.startswith("arsiv_antminer_"):return ("ARSIV", "Pi snapshot")
    if d.startswith("aylik_2026"):     return ("OZET",  "ay birikim")
    return _DOSYA_TIPLERI.get(d, ("DOSYA", d))

def _utc_to_tr(iso_utc):
    try:
        tarih = iso_utc.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(tarih)
        tr = dt + datetime.timedelta(hours=3)
        return tr.strftime("%Y-%m-%d %H:%M")
    except:
        return iso_utc

@app.route("/api/rapor")
def rapor_endpoint():
    if "kullanici" not in session:
        return jsonify({"hata":"yetkisiz"}), 401

    simdi = datetime.datetime.now().timestamp()
    if _RAPOR_CACHE["veri"] and simdi - _RAPOR_CACHE["ts"] < _RAPOR_TTL:
        return jsonify(_RAPOR_CACHE["veri"])

    olaylar_gun = {}
    debug_hata = None
    debug_commit_say = 0
    try:
        if not GH_TOKEN:
            debug_hata = "GH_TOKEN tanımlı değil (Railway ortam değişkeni)"
            raise RuntimeError(debug_hata)
        url = f"https://api.github.com/repos/{GITHUB_REPO}/commits?per_page=50"
        commits = None
        # Hem Bearer hem token formatini dene (PAT tipine gore farkli kabul edilir)
        for auth_prefix in ("Bearer", "token"):
            try:
                req = urllib.request.Request(url, headers={
                    "Authorization": f"{auth_prefix} {GH_TOKEN}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "otocoin-panel"
                })
                with urllib.request.urlopen(req, timeout=15) as r:
                    commits = json.loads(r.read())
                    debug_commit_say = len(commits) if isinstance(commits, list) else 0
                debug_hata = None
                break  # Basarili, dongu sonlandir
            except urllib.error.HTTPError as he:
                debug_hata = f"GitHub API hatası ({auth_prefix}): {he.code} {he.reason}"
                continue  # Diger formati dene
            except Exception as ge:
                debug_hata = f"GitHub bağlantı hatası: {str(ge)[:100]}"
                break

        if commits is None:
            raise RuntimeError(debug_hata or "Bilinmeyen hata")

        for c in commits:
            try:
                ci = c.get("commit", {})
                author_date = ci.get("author", {}).get("date") or ci.get("committer", {}).get("date")
                mesaj = ci.get("message", "").strip()
                tr_zaman = _utc_to_tr(author_date)
                if not tr_zaman:
                    continue
                gun = tr_zaman[:10]
                saat = tr_zaman[11:16]

                dosya_adi = ""
                if mesaj.startswith("arsiv ") and ".json" in mesaj:
                    parts = mesaj.split()
                    if len(parts) >= 2:
                        dosya_adi = parts[1]
                elif "aylik_ptf.json" in mesaj:
                    dosya_adi = "aylik_ptf.json"
                elif "son_gonderim" in mesaj:
                    dosya_adi = "son_gonderim.json"
                elif "sinyal" in mesaj.lower():
                    dosya_adi = "sinyal.json"

                if dosya_adi:
                    etiket, _ = _dosya_etiketi(dosya_adi)
                else:
                    etiket = "GUNCELLEME"
                ozet = mesaj.split("\n")[0][:80]

                author = "?"
                if c.get("author"):
                    author = c["author"].get("login", "?")

                kayit = {
                    "saat": saat,
                    "ikon": "•",
                    "etiket": etiket,
                    "dosya": dosya_adi,
                    "mesaj": ozet,
                    "author": author,
                }
                olaylar_gun.setdefault(gun, []).append(kayit)
            except Exception as e:
                print(f"commit parse hata: {e}")
                continue
    except Exception as e:
        print(f"rapor_endpoint hata: {e}")

    olaylar_liste = []
    for gun in sorted(olaylar_gun.keys(), reverse=True):
        kayitlar = sorted(olaylar_gun[gun], key=lambda x: x["saat"], reverse=True)
        olaylar_liste.append({"gun": gun, "kayitlar": kayitlar})

    tr_simdi = (datetime.datetime.utcnow() + datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")

    # Saglik
    OTOMASYON = {
        "EPIAS PTF (main.py)": ["sinyal.json", "son_gonderim.json", "aylik_ptf.json", "gunluk_arsiv.json"],
        "Arsiv (arsiv_kaydet.py)": ["arsiv_cihaz_", "arsiv_f2pool_", "arsiv_antminer_"],
    }
    saglik = {}
    simdi_dt = datetime.datetime.utcnow() + datetime.timedelta(hours=3)

    for ad, dosyalar in OTOMASYON.items():
        son_tarih = None
        son_dosya = None
        for grup in olaylar_liste:
            for k in grup["kayitlar"]:
                if k.get("author") not in ("github-actions[bot]", "github-actions"):
                    continue
                d = k.get("dosya", "") or ""
                m = k.get("mesaj", "") or ""
                ilgili = False
                for h in dosyalar:
                    if h in d or h in m:
                        ilgili = True
                        break
                if not ilgili:
                    continue
                try:
                    dt = datetime.datetime.strptime(grup["gun"] + " " + k["saat"], "%Y-%m-%d %H:%M")
                    if son_tarih is None or dt > son_tarih:
                        son_tarih = dt
                        son_dosya = d or m[:40]
                except:
                    continue

        if son_tarih:
            fark = (simdi_dt - son_tarih).total_seconds() / 3600
            if fark < 2:
                durum = "ok"
            elif fark < 26:
                durum = "yavas"
            else:
                durum = "calismiyor"
            saglik[ad] = {
                "durum": durum,
                "son_calisma": son_tarih.strftime("%Y-%m-%d %H:%M"),
                "saat_once": round(fark, 1),
                "son_dosya": son_dosya,
            }
        else:
            saglik[ad] = {"durum":"bilinmiyor","son_calisma":None,"saat_once":None,"son_dosya":None}

    # Token tip bilgisi (sadece ilk birkac karakter - guvenlik icin tamami degil)
    token_tip = "?"
    token_onek = ""
    if GH_TOKEN:
        if GH_TOKEN.startswith("ghp_"):
            token_tip = "Classic PAT"
            token_onek = "ghp_..."
        elif GH_TOKEN.startswith("github_pat_"):
            token_tip = "Fine-grained PAT"
            token_onek = "github_pat_..."
        elif GH_TOKEN.startswith("ghs_"):
            token_tip = "GitHub App"
            token_onek = "ghs_..."
        else:
            token_tip = "Bilinmiyor"
            token_onek = GH_TOKEN[:6] + "..."

    sonuc = {
        "sistem_saati": tr_simdi,
        "olaylar": olaylar_liste,
        "kayit_sayisi": sum(len(o["kayitlar"]) for o in olaylar_liste),
        "saglik": saglik,
        "debug": {
            "commit_say": debug_commit_say,
            "hata": debug_hata,
            "token_var_mi": bool(GH_TOKEN),
            "token_tip": token_tip,
            "token_onek": token_onek,
            "repo": GITHUB_REPO,
        }
    }
    _RAPOR_CACHE["ts"] = simdi
    _RAPOR_CACHE["veri"] = sonuc
    return jsonify(sonuc)

@app.route("/api/cihaz/<name>")
def cihaz_detay(name):
    if "kullanici" not in session:
        return jsonify({"hata":"yetkisiz"}), 401
    workers = f2pool_workers()
    worker = next((w for w in workers if w["hash_rate_info"]["name"] == name), None)
    if not worker:
        return jsonify({"hata":"bulunamadi"}), 404
    info = worker["hash_rate_info"]
    anlik = info.get("hash_rate", 0) / 1e12
    h1    = info.get("h1_hash_rate", 0) / 1e12
    h24   = info.get("h24_hash_rate", 0) / 1e12
    durum = cihaz_durum(info)
    legacy = f2pool_legacy(f"bitcoin/{F2POOL_USER}/{name}")
    history = legacy.get("hashrate_history", {}) if legacy else {}
    bugun_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    bugun_count = 0
    h24_count = 0
    for ts, hr in history.items():
        if hr > 0:
            h24_count += 1
            if ts.startswith(bugun_str):
                bugun_count += 1
    bugun_saat = bugun_count / 6
    h24_saat   = h24_count / 6
    hash_info = f2pool_hashrate()
    bugun_tahmini = f2pool_bugun_tahmini()
    toplam_h24 = hash_info["h24"]
    cihaz_oran = h24 / toplam_h24 if toplam_h24 > 0 else 0
    cihaz_btc  = bugun_tahmini * cihaz_oran
    sinyal = github_oku("sinyal.json")
    btc_try, btc_usd = _btc_kur_uygula(sinyal)
    return jsonify({
        "name": name, "anlik": anlik, "h1": h1, "h24": h24, "durum": durum,
        "last_share": datetime.datetime.fromtimestamp(worker["last_share_at"]).strftime("%d.%m %H:%M") if worker.get("last_share_at") else "—",
        "history": history, "bugun_saat": bugun_saat, "h24_saat": h24_saat,
        "gunluk_btc": cihaz_btc, "gunluk_tl": cihaz_btc * btc_try, "gunluk_usd": cihaz_btc * btc_usd
    })

def _arsiv_saatlik_kaynak(gun, btc_try):
    """Belirli bir gun icin saatlik veri - SADECE ARSIVDEN.
    arsiv_cihaz_YYYY-MM.json + arsiv_f2pool_YYYY-MM.json dosyalarindan okur.
    Cihaz kodlari (027) panel name'lerine (S19e XP Hyd-100) cevirilir.
    Donus: {veri_var, gun_btc, gun_hash_ort, saatler:[{saat, hash, btc, tl, cihaz_sayisi, cihazlar}]}
    """
    ay = gun[:7]  # 2026-05
    cihaz_ay = _gecmis_oku(f"arsiv_cihaz_{ay}.json") if "_gecmis_oku" in globals() else (github_oku(f"arsiv_cihaz_{ay}.json") or {})
    f2_ay = _gecmis_oku(f"arsiv_f2pool_{ay}.json") if "_gecmis_oku" in globals() else (github_oku(f"arsiv_f2pool_{ay}.json") or {})
    cihaz_ay = cihaz_ay or {}
    f2_ay = f2_ay or {}

    # Cihaz kodlari -> isim eslestirmesi (mehmetas.027 vs sadece "027")
    saatlik = {f"{h:02d}": {"hash_top": 0.0, "cihaz_sayisi": 0, "cihazlar": {}} for h in range(24)}

    # arsiv_cihaz: cihaz bazli hashrate'leri saate gore topla
    for anahtar, cihaz_kayit in cihaz_ay.items():
        if not anahtar.startswith(gun):
            continue
        try:
            saat = anahtar[11:13]
        except:
            continue
        if saat not in saatlik:
            continue
        s = saatlik[saat]
        for kod, deg in (cihaz_kayit or {}).items():
            h = (deg or {}).get("h", 0) if isinstance(deg, dict) else (deg or 0)
            if not h or h <= 0:
                continue
            # Ayni saatte birden fazla snapshot olabilir, son degeri kullan
            s["cihazlar"][kod] = round(h, 2)

    # Havuz toplamlari
    for h in range(24):
        sk = f"{h:02d}"
        s = saatlik[sk]
        s["hash_top"] = round(sum(s["cihazlar"].values()), 1)
        s["cihaz_sayisi"] = len(s["cihazlar"])

    # Gunun toplam BTC'si - arsiv_f2pool'dan son kayit (estimated_today)
    gun_btc = 0
    for anahtar in sorted(f2_ay.keys()):
        if anahtar.startswith(gun):
            kayit = f2_ay[anahtar]
            if isinstance(kayit, dict):
                gun_btc = kayit.get("btc", 0) or gun_btc

    saatli_hashlar = [saatlik[f"{h:02d}"]["hash_top"] for h in range(24)]
    gun_hash_toplam = sum(saatli_hashlar)

    sonuc_saatler = []
    for h in range(24):
        sk = f"{h:02d}"
        s = saatlik[sk]
        oran = (s["hash_top"] / gun_hash_toplam) if gun_hash_toplam > 0 else 0
        saat_btc = gun_btc * oran
        sonuc_saatler.append({
            "saat": sk,
            "hash": s["hash_top"],
            "cihaz_sayisi": s["cihaz_sayisi"],
            "btc": round(saat_btc, 8),
            "tl": round(saat_btc * btc_try, 2),
            "cihazlar": s["cihazlar"]
        })
    veri_var = gun_hash_toplam > 0
    return {
        "veri_var": veri_var,
        "gun_btc": gun_btc,
        "gun_hash_ort": round(gun_hash_toplam / 24, 1) if veri_var else 0,
        "saatler": sonuc_saatler,
    }


@app.route("/api/f2pool_saatlik")
def f2pool_saatlik():
    """Belirli bir gun icin saatlik hashrate + cihaz dagilimi.
    KAYNAK: Arsiv (arsiv_cihaz_*.json + arsiv_f2pool_*.json).
    Arsiv her saat F2Pool'dan toplanir (arsiv_kaydet.py), panel sadece arsivi okur.
    Boylece F2Pool 48 saat limiti asilir, tum gecmis gunler gorulebilir.
    Query: ?gun=YYYY-MM-DD
    """
    if "kullanici" not in session:
        return jsonify({"hata":"yetkisiz"}), 401
    gun = request.args.get("gun", "")
    if not gun:
        return jsonify({"hata":"gun parametresi gerekli"}), 400
    sinyal = github_oku("sinyal.json")
    btc_try, _ = _btc_kur_uygula(sinyal)
    veri = _arsiv_saatlik_kaynak(gun, btc_try)
    return jsonify({
        "gun": gun,
        "btc_kur": btc_try,
        **veri,
    })


@app.route("/api/ozet")
def ozet():
    if "kullanici" not in session:
        return jsonify({"hata":"yetkisiz"}), 401
    sonuc = {}
    sinyal = github_oku("sinyal.json")
    btc_try, btc_usd = _btc_kur_uygula(sinyal)
    if sinyal:
        su_an = (datetime.datetime.utcnow() + datetime.timedelta(hours=3)).strftime("%H")
        karli = su_an in sinyal.get("karli_saatler", [])
        sonuc["sinyal"] = {"veri_var": True, "karli": karli,
            "mesaj": f"Saat {su_an}:00 — {'karlı' if karli else 'zararlı'} | {sinyal.get('tarih','')}"}
        sonuc["btc"] = {"tl": f"{btc_try:,.0f}", "usd": f"{btc_usd:,.0f}"}
    else:
        sonuc["sinyal"] = {"veri_var": False, "karli": False, "mesaj": ""}
        sonuc["btc"] = {"tl": "—", "usd": "—"}
    transactions = f2pool_son_gunler(30)
    dun_btc = 0
    if transactions:
        en_son = max(transactions, key=lambda t: t["mining_extra"]["mining_date"])
        dun_btc = en_son["changed_balance"]
    bugun_tahmini = f2pool_bugun_tahmini()
    hash_info = f2pool_hashrate()
    sonuc["f2pool"] = {
        "bugun_btc": f"{bugun_tahmini:.5f}",
        "bugun_tl":  f"{bugun_tahmini * btc_try:,.0f}",
        "dun_btc":   f"{dun_btc:.5f}",
        "dun_tl":    f"{dun_btc * btc_try:,.0f}",
        "hash":      f"{hash_info['h24']:,.0f}"
    }
    ay_baslangic = datetime.date.today().replace(day=1)
    aylik_toplam_btc = 0
    aylik_gun_sayisi = 0
    for t in transactions:
        tarih = datetime.datetime.fromtimestamp(t["mining_extra"]["mining_date"], tz=datetime.timezone.utc).date()
        if tarih >= ay_baslangic:
            aylik_toplam_btc += t["changed_balance"]
            aylik_gun_sayisi += 1
    ay_key = datetime.date.today().strftime("%Y-%m")
    ay_dosya = github_oku(f"aylik_{ay_key}.json")
    aylik_maliyet = ay_dosya.get("toplam_maliyet_tl", 0) if ay_dosya else 0
    aylik_gelir = aylik_toplam_btc * btc_try
    aylik_kar = aylik_gelir - aylik_maliyet
    sonuc["aylik"] = {
        "ay": ay_key, "gun": aylik_gun_sayisi,
        "btc": f"{aylik_toplam_btc:.5f}",
        "tl":  f"{aylik_gelir:,.0f}",
        "kar": f"{aylik_kar:,.0f}"
    }
    aylik_ptf = github_oku("aylik_ptf.json")
    if aylik_ptf:
        sonuc["aylik_ptf"] = aylik_ptf.get(ay_key, {})
    gunluk = []
    sorted_tx = sorted(transactions, key=lambda t: t["mining_extra"]["mining_date"], reverse=True)
    for t in sorted_tx[:31]:
        tarih = datetime.datetime.fromtimestamp(t["mining_extra"]["mining_date"], tz=datetime.timezone.utc).strftime("%d.%m.%Y")
        btc = t["changed_balance"]
        ths = t["mining_extra"]["hash_rate"] / 1e12
        gunluk.append({"tarih": tarih, "btc": f"{btc:.5f}", "hash": f"{ths:,.0f}", "tl": f"{btc * btc_try:,.0f}"})
    sonuc["gunluk_liste"] = gunluk
    # Ham gunluk veri dizisi (grafik + haftalik/aylik gruplama icin)
    # ISO tarih + ham sayisal degerler (formatlanmamis)
    gunluk_ham = []
    for t in sorted(transactions, key=lambda t: t["mining_extra"]["mining_date"]):
        dt = datetime.datetime.fromtimestamp(t["mining_extra"]["mining_date"], tz=datetime.timezone.utc)
        gunluk_ham.append({
            "iso": dt.strftime("%Y-%m-%d"),
            "btc": t["changed_balance"],
            "hash": t["mining_extra"]["hash_rate"] / 1e12,
            "tl": t["changed_balance"] * btc_try
        })
    sonuc["gunluk_ham"] = gunluk_ham
    sonuc["btc_kur"] = btc_try
    workers = f2pool_workers()
    worker_list = []
    for w in workers:
        info = w["hash_rate_info"]
        worker_list.append({
            "name":  info["name"],
            "anlik": info.get("hash_rate", 0) / 1e12,
            "h1":    info.get("h1_hash_rate", 0) / 1e12,
            "h24":   info.get("h24_hash_rate", 0) / 1e12,
            "durum": cihaz_durum(info),
            "last_share": datetime.datetime.fromtimestamp(w["last_share_at"]).strftime("%d.%m %H:%M") if w.get("last_share_at") else "—"
        })
    sonuc["workers"] = worker_list
    return jsonify(sonuc)


@app.route("/api/inverter")
def inverter():
    """Huawei FusionSolar inverter verisi - Raspberry Pi'den gelen fusion_data.json okur."""
    if "kullanici" not in session:
        return jsonify({"hata": "yetkisiz"}), 401
    data = github_oku("fusion_data.json")
    if not data:
        return jsonify({"hata": "Veri yok - Raspberry Pi henuz baglanmadi"}), 200
    return jsonify(data)


@app.route("/api/antminer")
def antminer():
    """Antminer saha verisi - sahadaki PC'den gelen antminer_panel.json okur."""
    if "kullanici" not in session:
        return jsonify({"hata": "yetkisiz"}), 401
    data = github_oku("antminer_panel.json")
    if not data:
        return jsonify({"hata": "Veri yok - Saha PC'sinden henuz veri gelmedi"}), 200
    # Sonuc bilgisini de ekle
    results = github_oku("antminer_command_results.json")
    if results:
        data["command_results"] = results.get("results", [])[-10:]  # Son 10 sonuc
    return jsonify(data)


@app.route("/api/antminer/command", methods=["POST"])
def antminer_command():
    """Otocoin'den sahaya komut gonder (uyut/calistir)."""
    if "kullanici" not in session:
        return jsonify({"hata": "yetkisiz"}), 401
    if KULLANICILAR.get(session["kullanici"], {}).get("rol") != "yonetici":
        return jsonify({"hata": "Yetki yok (sadece yoneticiler komut verebilir)"}), 403

    data = request.get_json()
    action = data.get("action")  # "sleep" | "wake"
    targets = data.get("targets")  # IP suffix listesi veya "all"
    delay_sec = data.get("delay_sec", 0)  # 0=anlik, 10=sirali
    sort_by = data.get("sort_by")  # "hashrate_asc" | "hashrate_24h_desc"

    if action not in ("sleep", "wake"):
        return jsonify({"hata": "action sleep veya wake olmali"}), 400

    if not targets or (targets != "all" and not isinstance(targets, list)):
        return jsonify({"hata": "targets bos veya gecersiz"}), 400

    # Mevcut komut dosyasini oku
    existing = github_oku("antminer_commands.json") or {"commands": []}
    commands = existing.get("commands", [])

    # Yeni komut ekle
    import uuid
    cmd_id = str(uuid.uuid4())[:8]
    new_cmd = {
        "id": cmd_id,
        "action": action,
        "targets": targets,
        "delay_sec": delay_sec,
        "sort_by": sort_by,
        "issued_at": datetime.datetime.now().isoformat(),
        "issued_by": session["kullanici"],
    }

    # Son 50 komutu tut (eskileri unutalim)
    commands.append(new_cmd)
    commands = commands[-50:]

    payload = {
        "updated_at": datetime.datetime.now().isoformat(),
        "commands": commands,
    }

    ok = github_yaz("antminer_commands.json", payload)
    if not ok:
        return jsonify({"hata": "GitHub'a yazilamadi"}), 500

    # Tahmini sure
    n = 29 if targets == "all" else len(targets)
    est_sec = n * delay_sec if delay_sec > 0 else 0
    return jsonify({
        "ok": True,
        "command_id": cmd_id,
        "action": action,
        "targets": targets if targets == "all" else len(targets),
        "issued_at": new_cmd["issued_at"],
        "estimated_duration_sec": est_sec,
        "message": f"Komut gonderildi. Tahmini sure: {est_sec} saniye.",
    })


@app.route("/api/bekleyen_onaylar")
def api_bekleyen_onaylar():
    """Bekleyen saat onaylarini getir."""
    if "kullanici" not in session:
        return jsonify({"hata": "yetkisiz"}), 401
    data = github_oku("bekleyen_onaylar.json") or {"onaylar": []}
    # Sadece bekleyen veya son 24 saat icinde olusturulanlar
    onaylar = data.get("onaylar", [])
    now = datetime.datetime.now()
    cutoff = (now - datetime.timedelta(hours=24)).date().isoformat()
    aktif = [o for o in onaylar if o.get("tarih", "") >= cutoff]
    return jsonify({"onaylar": aktif, "count": len(aktif)})


@app.route("/api/bekleyen_onaylar/<onay_id>/karar", methods=["POST"])
def api_onay_karar(onay_id):
    """Bir onay icin karar ver: onayla veya reddet."""
    if "kullanici" not in session:
        return jsonify({"hata": "yetkisiz"}), 401
    if KULLANICILAR.get(session["kullanici"], {}).get("rol") != "yonetici":
        return jsonify({"hata": "Yetki yok"}), 403

    karar = request.get_json().get("karar")  # "onayla" | "reddet"
    if karar not in ("onayla", "reddet"):
        return jsonify({"hata": "karar 'onayla' veya 'reddet' olmali"}), 400

    data = github_oku("bekleyen_onaylar.json") or {"onaylar": []}
    onay = None
    for o in data.get("onaylar", []):
        if o.get("id") == onay_id:
            onay = o
            break

    if not onay:
        return jsonify({"hata": "Onay bulunamadi"}), 404

    if onay.get("durum") != "bekliyor":
        return jsonify({"hata": f"Onay zaten {onay.get('durum')}"}), 400

    # Karar uygula
    if karar == "reddet":
        onay["durum"] = "reddedildi"
        onay["karar_veren"] = session["kullanici"]
        onay["karar_zamani"] = datetime.datetime.now().isoformat()
        github_yaz("bekleyen_onaylar.json", data)
        return jsonify({"ok": True, "durum": "reddedildi"})

    # Onayla -> antminer komutu olustur
    onay["durum"] = "onaylandi"
    onay["karar_veren"] = session["kullanici"]
    onay["karar_zamani"] = datetime.datetime.now().isoformat()

    # Komut olustur (sirali, 10 sn aralikli)
    import uuid
    cmd_id = str(uuid.uuid4())[:8]
    eylem = onay.get("eylem")  # wake | sleep
    sort_by = "hashrate_24h_desc" if eylem == "wake" else "hashrate_asc"

    cmd_data = github_oku("antminer_commands.json") or {"commands": []}
    cmd_data.setdefault("commands", []).append({
        "id": cmd_id,
        "action": eylem,
        "targets": "all",
        "delay_sec": 10,
        "sort_by": sort_by,
        "issued_at": datetime.datetime.now().isoformat(),
        "issued_by": session["kullanici"],
        "onay_id": onay_id,
    })
    cmd_data["commands"] = cmd_data["commands"][-50:]
    cmd_data["updated_at"] = datetime.datetime.now().isoformat()
    github_yaz("antminer_commands.json", cmd_data)

    onay["command_id"] = cmd_id
    github_yaz("bekleyen_onaylar.json", data)

    return jsonify({
        "ok": True,
        "durum": "onaylandi",
        "command_id": cmd_id,
        "estimated_duration_sec": 290,
    })


@app.route("/onay/<onay_id>")
def onay_sayfa(onay_id):
    """WhatsApp linkinden gelen onay sayfasi."""
    if "kullanici" not in session:
        return redirect("/?next=/onay/" + onay_id)
    return redirect("/?tab=cihazlarim&onay=" + onay_id)


@app.route("/api/maliyet/aksaray3")
def api_maliyet_aksaray3():
    """Aksaray 3 saatlik elektrik maliyet hesabi.
    
    Formul: (PTF[saat]/1000 + YEKDEM/1000) * 1.035 * tuketim[saat]
    PTF: TL/MWh -> TL/kWh icin /1000
    YEKDEM: 602.51 kr/MWh -> TL/kWh icin /1000
    """
    if "kullanici" not in session:
        return jsonify({"hata": "yetkisiz"}), 401
    
    YEKDEM_KR_MWH = 602.51
    DAGITIM_KATSAYI = 1.035  # %3,5 dagitim/kayip (MEPAŞ faturasi ile dogrulandi)
    
    ay = request.args.get("ay")  # "2026-05" - bos ise mevcut ay, "2026" tum yil
    if not ay:
        ay = datetime.datetime.now().strftime("%Y-%m")
    
    yil_mod = (len(ay) == 4)  # "2026" -> tum yil
    
    # 1. PTF verisi (aylik_ptf.json)
    ayptf = github_oku("aylik_ptf.json") or {}
    ay_ptf = ayptf.get(ay, {}) if not yil_mod else {}
    if yil_mod:
        # Tum aylarin PTF'sini topla
        for k, v in ayptf.items():
            if k.startswith(ay):
                ay_ptf.update(v)
    
    # 2. OSOS verisi (saatlik tuketim)
    osos = github_oku("2026_osos_endeks.json") or {}
    aksaray3 = osos.get("aksaray_3", {}).get("veri", {})
    
    if not aksaray3:
        return jsonify({"hata": "Aksaray 3 OSOS verisi yok"}), 200
    
    # 3. Gun gun hesapla
    gunler = []
    ay_toplam_maliyet = 0
    ay_toplam_tuketim = 0
    ay_toplam_ptf_kr = 0
    ay_gun_sayisi = 0
    
    for gun_str in sorted(aksaray3.keys()):
        # Filtre: yil_mod ise tum 2026, degilse sadece bu ay
        if yil_mod:
            if not gun_str.startswith(ay):
                continue
        else:
            if not gun_str.startswith(ay):
                continue
        
        gun_no = gun_str[8:10]
        # PTF okumasi: yil_mod'da o ayin PTF'sini bul
        if yil_mod:
            ay_str = gun_str[:7]
            ay_ptf_local = ayptf.get(ay_str, {})
            gun_ptf = ay_ptf_local.get(gun_no)
        else:
            gun_ptf = ay_ptf.get(gun_no)
        if not gun_ptf or len(gun_ptf) != 24:
            continue  # PTF yoksa gun atlaniyor
        
        saatler_data = aksaray3[gun_str]
        
        gun_maliyet = 0
        gun_tuketim = 0
        gun_ptf_toplam = 0
        gun_saatler = []
        
        for saat_int in range(24):
            saat_key = f"{saat_int:02d}"
            saat_veri = saatler_data.get(saat_key) or saatler_data.get(str(saat_int)) or {}
            tuketim_kwh = float(saat_veri.get("cekis", 0))
            ptf_tl_mwh = float(gun_ptf[saat_int])
            
            ptf_tl_kwh = ptf_tl_mwh / 1000
            yekdem_tl_kwh = YEKDEM_KR_MWH / 1000
            maliyet = (ptf_tl_kwh + yekdem_tl_kwh) * DAGITIM_KATSAYI * tuketim_kwh
            
            gun_maliyet += maliyet
            gun_tuketim += tuketim_kwh
            gun_ptf_toplam += ptf_tl_mwh
            
            gun_saatler.append({
                "saat": saat_int,
                "ptf": round(ptf_tl_mwh, 2),
                "tuketim": round(tuketim_kwh, 2),
                "maliyet": round(maliyet, 2),
            })
        
        ort_ptf = gun_ptf_toplam / 24
        ort_birim_fiyat = gun_maliyet / gun_tuketim if gun_tuketim > 0 else 0
        
        gunler.append({
            "tarih": gun_str,
            "gun_no": gun_no,
            "toplam_tuketim_kwh": round(gun_tuketim, 2),
            "toplam_maliyet_tl": round(gun_maliyet, 2),
            "ort_ptf_tl_mwh": round(ort_ptf, 2),
            "ort_birim_fiyat_tl_kwh": round(ort_birim_fiyat, 4),
            "saatler": gun_saatler,
        })
        
        ay_toplam_maliyet += gun_maliyet
        ay_toplam_tuketim += gun_tuketim
        ay_toplam_ptf_kr += gun_ptf_toplam
        ay_gun_sayisi += 1
    
    return jsonify({
        "ay": ay,
        "abone": "Aksaray 3",
        "yekdem_kr_mwh": YEKDEM_KR_MWH,
        "dagitim_katsayi": DAGITIM_KATSAYI,
        "gun_sayisi": ay_gun_sayisi,
        "toplam_tuketim_kwh": round(ay_toplam_tuketim, 2),
        "toplam_maliyet_tl": round(ay_toplam_maliyet, 2),
        "ort_birim_fiyat_tl_kwh": round(ay_toplam_maliyet / ay_toplam_tuketim, 4) if ay_toplam_tuketim > 0 else 0,
        "ort_gunluk_maliyet_tl": round(ay_toplam_maliyet / ay_gun_sayisi, 2) if ay_gun_sayisi > 0 else 0,
        "ort_gunluk_tuketim_kwh": round(ay_toplam_tuketim / ay_gun_sayisi, 2) if ay_gun_sayisi > 0 else 0,
        "ort_ptf_tl_mwh": round(ay_toplam_ptf_kr / (ay_gun_sayisi * 24), 2) if ay_gun_sayisi > 0 else 0,
        "gunler": gunler,
    })


@app.route("/api/uretim_tuketim")
def api_uretim_tuketim():
    """Tek Yildiz 1+2 uretim/tuketim mahsuplasmasi.
    
    - tekyildiz_1: sadece uretim
    - tekyildiz_2: uretim + mining tuketimi (Sera 2)
    
    Veri kaynagi:
    1. fusion_data.json (canli, Pi gelince) - oncelikli
    2. osos_gecmis.json (gecikmeli, mevcut)
    """
    if "kullanici" not in session:
        return jsonify({"hata": "yetkisiz"}), 401
    
    gun = request.args.get("gun")  # YYYY-MM-DD
    ay = request.args.get("ay")    # YYYY-MM
    if not ay:
        ay = datetime.datetime.now().strftime("%Y-%m")
    if not gun:
        gun = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # Veri kaynaklarini hazirla
    fusion = github_oku("fusion_data.json") or {}
    osos = github_oku("2026_osos_endeks.json") or {}
    
    ty1 = osos.get("tekyildiz_1", {}).get("veri", {})
    ty2 = osos.get("tekyildiz_2", {}).get("veri", {})
    
    # Saatlik veri olusturma yardimcisi
    def get_saatlik(abone_veri, gun_str, alan):
        """abone_veri[gun_str][saat][cekis|veris] -> saatlik liste. Hem '05' hem '5' anahtarini destekler."""
        saatler_data = abone_veri.get(gun_str, {})
        def oku(h):
            d = saatler_data.get(f"{h:02d}") or saatler_data.get(str(h)) or {}
            return float(d.get(alan, 0))
        return [oku(h) for h in range(24)]
    
    # ===== GUNLUK DETAY (saatlik tablo icin) =====
    ty1_uretim = get_saatlik(ty1, gun, "veris")
    ty2_uretim = get_saatlik(ty2, gun, "veris")
    ty2_tuketim = get_saatlik(ty2, gun, "cekis")
    
    saatlik = []
    for h in range(24):
        uretim_toplam = ty1_uretim[h] + ty2_uretim[h]
        net = uretim_toplam - ty2_tuketim[h]
        saatlik.append({
            "saat": h,
            "ty1_uretim": round(ty1_uretim[h], 2),
            "ty2_uretim": round(ty2_uretim[h], 2),
            "toplam_uretim": round(uretim_toplam, 2),
            "ty2_tuketim": round(ty2_tuketim[h], 2),
            "net": round(net, 2),
            "fazla_uretim": net > 0,
        })
    
    gun_ty1 = sum(ty1_uretim)
    gun_ty2_u = sum(ty2_uretim)
    gun_ty2_t = sum(ty2_tuketim)
    gun_uretim = gun_ty1 + gun_ty2_u
    gun_net = gun_uretim - gun_ty2_t
    
    # ===== AYLIK OZET (her gun icin toplam) =====
    aylik_gunler = []
    ay_uretim_top = 0
    ay_tuketim_top = 0
    
    # Tum tarihleri birlestir
    tum_gunler = set(ty1.keys()) | set(ty2.keys())
    for gun_str in sorted(tum_gunler):
        if not gun_str.startswith(ay):
            continue
        g_ty1 = sum(get_saatlik(ty1, gun_str, "veris"))
        g_ty2_u = sum(get_saatlik(ty2, gun_str, "veris"))
        g_ty2_t = sum(get_saatlik(ty2, gun_str, "cekis"))
        g_uretim = g_ty1 + g_ty2_u
        g_net = g_uretim - g_ty2_t
        aylik_gunler.append({
            "tarih": gun_str,
            "ty1_uretim": round(g_ty1, 2),
            "ty2_uretim": round(g_ty2_u, 2),
            "toplam_uretim": round(g_uretim, 2),
            "ty2_tuketim": round(g_ty2_t, 2),
            "net": round(g_net, 2),
            "fazla_uretim": g_net > 0,
        })
        ay_uretim_top += g_uretim
        ay_tuketim_top += g_ty2_t
    
    return jsonify({
        "gun": gun,
        "ay": ay,
        "gunluk": {
            "tarih": gun,
            "ty1_uretim": round(gun_ty1, 2),
            "ty2_uretim": round(gun_ty2_u, 2),
            "toplam_uretim": round(gun_uretim, 2),
            "ty2_tuketim": round(gun_ty2_t, 2),
            "net": round(gun_net, 2),
            "fazla_uretim": gun_net > 0,
            "saatlik": saatlik,
        },
        "aylik": {
            "ay": ay,
            "gun_sayisi": len(aylik_gunler),
            "toplam_uretim": round(ay_uretim_top, 2),
            "toplam_tuketim": round(ay_tuketim_top, 2),
            "net": round(ay_uretim_top - ay_tuketim_top, 2),
            "gunler": aylik_gunler,
        },
    })


# ════════════════════════════════════════════════════════════════
# EPIAS PTF — PANEL ICI OTOMATIK CEKIM (cron yerine, Railway 7/24)
# ════════════════════════════════════════════════════════════════
import threading as _threading

EPIAS_KULLANICI = os.environ.get("EPIAS_KULLANICI", "")
EPIAS_SIFRE     = os.environ.get("EPIAS_SIFRE", "")
_ptf_son_log    = {"zaman": "-", "durum": "henuz calismadi"}


def _tr_simdi():
    """Railway UTC olabilir; TR saati icin +3 saat."""
    return datetime.datetime.utcnow() + datetime.timedelta(hours=3)


EPIAS_TGT_URL = "https://giris.epias.com.tr/cas/v1/tickets"
EPIAS_MCP_URL = "https://seffaflik.epias.com.tr/electricity-service/v1/markets/dam/data/mcp"


def _epias_tgt():
    """EPIAS Seffaflik CAS'tan TGT (giris bileti) alir. Ek kutuphane gerekmez."""
    veri = urllib.parse.urlencode({
        "username": EPIAS_KULLANICI, "password": EPIAS_SIFRE,
    }).encode("utf-8")
    req = urllib.request.Request(EPIAS_TGT_URL, data=veri, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/plain",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8").strip()


def epias_ptf_cek(tarih_iso):
    """EPIAS'tan tek gunun saatlik PTF'sini ceker (TL/MWh listesi). Yoksa (None, sebep).
    eptr2'ye gerek yok — sadece urllib (TGT + MCP endpoint)."""
    if not EPIAS_KULLANICI or not EPIAS_SIFRE:
        return None, "EPIAS_KULLANICI/SIFRE tanimli degil"
    try:
        tgt = _epias_tgt()
        govde = json.dumps({
            "startDate": f"{tarih_iso}T00:00:00+03:00",
            "endDate":   f"{tarih_iso}T00:00:00+03:00",
        }).encode("utf-8")
        req = urllib.request.Request(EPIAS_MCP_URL, data=govde, method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "TGT": tgt,
        })
        with urllib.request.urlopen(req, timeout=25) as r:
            sonuc = json.loads(r.read())
        items = sonuc.get("items", [])
        if not items:
            return None, "veri henuz yayinlanmadi"
        return [round(it["price"], 2) for it in items], "ok"
    except urllib.error.HTTPError as e:
        return None, f"http {e.code}"
    except Exception as e:
        return None, f"hata: {str(e)[:80]}"


def ptf_otomatik_guncelle():
    """Yarin (ve eksikse bugun) PTF'sini cekip aylik_ptf.json'a yazar."""
    tr = _tr_simdi()
    hedefler = [
        (tr + datetime.timedelta(days=1)).date().isoformat(),  # yarin (oncelik)
        tr.date().isoformat(),                                  # bugun (eksikse)
    ]
    ayptf = github_oku("aylik_ptf.json") or {}
    degisti = False
    notlar = []
    for tarih in hedefler:
        ay, gun = tarih[:7], tarih[8:10]
        if ay in ayptf and gun in ayptf[ay] and len(ayptf[ay][gun]) >= 24:
            continue  # zaten var
        fiyatlar, durum = epias_ptf_cek(tarih)
        if fiyatlar:
            ayptf.setdefault(ay, {})[gun] = fiyatlar
            degisti = True
            notlar.append(f"{tarih} eklendi ({len(fiyatlar)} saat)")
        else:
            notlar.append(f"{tarih}: {durum}")
    if degisti:
        github_yaz("aylik_ptf.json", ayptf)
        notlar.append("GitHub'a yazildi")
    _ptf_son_log["zaman"] = tr.strftime("%Y-%m-%d %H:%M TR")
    _ptf_son_log["durum"] = " | ".join(notlar) if notlar else "guncel"
    print(f"[PTF] {_ptf_son_log['zaman']} -> {_ptf_son_log['durum']}", flush=True)
    return _ptf_son_log["durum"]


def _ptf_zamanlayici():
    """Arka planda her 2 saatte bir PTF kontrol eder."""
    import time as _time
    _time.sleep(20)  # panel acilisini bekle
    while True:
        try:
            ptf_otomatik_guncelle()
        except Exception as e:
            print(f"[PTF] zamanlayici hata: {e}", flush=True)
        _time.sleep(2 * 3600)  # 2 saat


@app.route("/api/ptf_cek")
def ptf_cek_endpoint():
    """Tarayicidan elle tetikleme: panel.../api/ptf_cek"""
    durum = ptf_otomatik_guncelle()
    return jsonify({"zaman": _ptf_son_log["zaman"], "durum": durum})


@app.route("/api/ptf_durum")
def ptf_durum_endpoint():
    return jsonify(_ptf_son_log)


# Zamanlayiciyi bir kez baslat (gunicorn/python farketmez, daemon)
if os.environ.get("PTF_OTOMATIK", "1") == "1" and not globals().get("_ptf_basladi"):
    _ptf_basladi = True
    _threading.Thread(target=_ptf_zamanlayici, daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
