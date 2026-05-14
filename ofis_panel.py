from flask import Flask, jsonify, session, redirect, render_template_string, request, Response
import hashlib, json, os, urllib.request
import datetime

app = Flask(__name__)
app.secret_key = "otocoin-ofis-2026"

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
    try:
        with urllib.request.urlopen(f"{GITHUB_RAW}/{dosya}", timeout=15) as r:
            return json.loads(r.read())
    except:
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
            with urllib.request.urlopen(req, timeout=10) as r:
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
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except:
        return None

def f2pool_legacy(path):
    try:
        req = urllib.request.Request(f"https://api.f2pool.com/{path}",
            headers={"F2P-API-SECRET":F2POOL_TOKEN})
        with urllib.request.urlopen(req, timeout=10) as r:
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
.aylik-table{width:100%;border-collapse:collapse;font-size:10px;}
.aylik-table th{background:linear-gradient(180deg,#1e293b,#0f172a);color:#94a3b8;font-weight:700;font-size:9px;padding:8px 4px;text-align:center;position:sticky;top:0;z-index:2;}
.aylik-table th.saat-head{background:linear-gradient(180deg,#16a34a,#15803d);color:white;min-width:38px;position:sticky;left:0;z-index:3;}
.aylik-table td{padding:5px 3px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.03);font-weight:700;min-width:38px;background:#050917;}
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
.f2-summary{background:linear-gradient(135deg,rgba(245,158,11,0.15) 0%,rgba(245,158,11,0.05) 100%);border:1px solid rgba(245,158,11,0.25);border-radius:18px;padding:16px;margin-bottom:14px;}
.f2-icon-wrap{display:flex;align-items:center;gap:12px;margin-bottom:12px;}
.f2-icon{width:44px;height:44px;background:linear-gradient(135deg,#f59e0b,#fbbf24);border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:22px;}
.f2-title{font-size:15px;font-weight:800;}
.f2-subtitle{color:#94a3b8;font-size:11px;margin-top:1px;}
.f2-big{font-size:26px;font-weight:900;}
.f2-big span{color:#fbbf24;}
.f2-small{font-size:12px;color:#94a3b8;margin-top:2px;}
.daily-item{display:flex;align-items:center;gap:12px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.05);border-radius:12px;padding:10px 12px;margin-bottom:6px;}
.daily-date{font-size:11px;color:#94a3b8;font-weight:600;min-width:80px;}
.daily-btc{font-size:13px;font-weight:800;}
.daily-hash{font-size:10px;color:#64748b;margin-top:1px;}
.daily-tl{margin-left:auto;text-align:right;}
.daily-tl-val{font-size:13px;font-weight:800;color:#4ade80;}
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
.tab-content.active{display:block;}
.osos-sec-content{display:none;}
.osos-sec-content.active{display:block;}
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
</head><body>
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
<div class="tab" onclick="sekme('osos', this)">🔋 OSOS</div>
<div class="tab" onclick="sekme('inverter', this)">🌞 İnverter</div>
<div class="tab" onclick="sekme('antminer', this)">⛏️ Antminer Saha</div>
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
<div class="section-header">
<div class="section-title">📅 Mayıs 2026 PTF Tablosu</div>
<div style="font-size:10px;color:#64748b">⏸ Kapalı saatler mor</div>
</div>
<div class="aylik-wrap">
<table class="aylik-table" id="aylik-table"><thead id="aylik-thead"></thead><tbody id="aylik-tbody"></tbody></table>
</div>
</div>

<div class="tab-content" id="t-f2pool">
<div class="f2-summary">
<div class="f2-icon-wrap">
<div class="f2-icon">₿</div>
<div><div class="f2-title" id="f2-title">Aylık Toplam</div><div class="f2-subtitle" id="f2-subtitle">—</div></div>
</div>
<div class="f2-big" id="f2-big">—<span> BTC</span></div>
<div class="f2-small" id="f2-small">—</div>
</div>
<div class="section-title">📅 Günlük Üretim</div>
<div id="daily-list" style="margin-top:8px"><div class="empty-state">Yükleniyor...</div></div>
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
<div style="margin-bottom:18px;">
  <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;">
    <div>
      <div style="font-size:20px; font-weight:700; color:#fbbf24;">💸 Aksaray 3 - Elektrik Maliyeti</div>
      <div style="font-size:11px; color:#94a3b8; margin-top:4px;">(PTF + YEKDEM) × 1.05 × Tüketim</div>
    </div>
    <select id="mlt-ay" onchange="mltYukle()" style="background:#0f172a; border:1px solid #334155; color:#e2e8f0; padding:8px 12px; border-radius:8px; font-size:13px;">
      <option value="">Mevcut Ay</option>
    </select>
  </div>
</div>

<!-- KPI sade -->
<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-bottom:18px;">
  <div style="background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:12px 14px;">
    <div style="font-size:11px; color:#94a3b8; margin-bottom:4px;">Toplam Maliyet</div>
    <div id="mlt-toplam" style="font-size:18px; font-weight:700; color:#ef4444;">—</div>
    <div id="mlt-toplam-sub" style="font-size:10px; color:#64748b; margin-top:2px;">— gün</div>
  </div>
  <div style="background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:12px 14px;">
    <div style="font-size:11px; color:#94a3b8; margin-bottom:4px;">Toplam Tüketim</div>
    <div id="mlt-tuketim" style="font-size:18px; font-weight:700; color:#60a5fa;">—</div>
    <div style="font-size:10px; color:#64748b; margin-top:2px;">kWh</div>
  </div>
  <div style="background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:12px 14px;">
    <div style="font-size:11px; color:#94a3b8; margin-bottom:4px;">Birim Maliyet</div>
    <div id="mlt-birim" style="font-size:18px; font-weight:700; color:#fbbf24;">—</div>
    <div style="font-size:10px; color:#64748b; margin-top:2px;">TL/kWh</div>
  </div>
  <div style="background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:12px 14px;">
    <div style="font-size:11px; color:#94a3b8; margin-bottom:4px;">Ort. PTF</div>
    <div id="mlt-ortptf" style="font-size:18px; font-weight:700; color:#a855f7;">—</div>
    <div style="font-size:10px; color:#64748b; margin-top:2px;">TL/MWh</div>
  </div>
</div>

<!-- TABLO -->
<div style="background:rgba(15,23,42,0.4); border:1px solid rgba(255,255,255,0.06); border-radius:12px; overflow:hidden; margin-bottom:18px;">
  <table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
      <tr style="background:rgba(255,255,255,0.04); border-bottom:1px solid rgba(255,255,255,0.06); color:#94a3b8;">
        <th style="padding:10px 8px; text-align:left; width:36px;"></th>
        <th style="padding:10px 12px; text-align:left; font-weight:600;">Tarih</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600;">Tüketim (kWh)</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600;">Ort PTF</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600;">Birim</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600;">Maliyet</th>
      </tr>
    </thead>
    <tbody id="mlt-tablo"></tbody>
  </table>
</div>

<!-- CIZGI GRAFIK - GUNLUK TUKETIM -->
<div style="background:rgba(15,23,42,0.4); border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:14px; margin-bottom:24px;">
  <div style="font-size:13px; font-weight:600; color:#60a5fa; margin-bottom:10px;">📈 Günlük Tüketim (kWh)</div>
  <div style="position:relative; width:100%; height:240px;">
    <canvas id="mlt-chart"></canvas>
  </div>
</div>


<!-- ====== TEK YILDIZ 1+2 BIRLESIK ====== -->
<div style="margin-bottom:18px; padding-top:18px; border-top:1px solid rgba(255,255,255,0.06);">
  <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;">
    <div>
      <div style="font-size:20px; font-weight:700; color:#22c55e;">📊 Tek Yıldız 1+2 - Üretim/Tüketim</div>
      <div style="font-size:11px; color:#94a3b8; margin-top:4px;">Toplam Üretim - TY2 Tüketim = NET (🟢 fazla / 🔴 eksik)</div>
    </div>
  </div>
</div>

<!-- KPI birlesik -->
<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-bottom:18px;">
  <div style="background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:12px 14px;">
    <div style="font-size:11px; color:#94a3b8; margin-bottom:4px;">Toplam Üretim (TY1+TY2)</div>
    <div id="ut-ay-uretim" style="font-size:18px; font-weight:700; color:#60a5fa;">—</div>
    <div style="font-size:10px; color:#64748b; margin-top:2px;">kWh</div>
  </div>
  <div style="background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:12px 14px;">
    <div style="font-size:11px; color:#94a3b8; margin-bottom:4px;">TY2 Tüketim (Sera 2)</div>
    <div id="ut-ay-tuketim" style="font-size:18px; font-weight:700; color:#ef4444;">—</div>
    <div style="font-size:10px; color:#64748b; margin-top:2px;">kWh</div>
  </div>
  <div style="background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:12px 14px;">
    <div style="font-size:11px; color:#94a3b8; margin-bottom:4px;">NET (Üretim − Tüketim)</div>
    <div id="ut-ay-net" style="font-size:18px; font-weight:700; color:#22c55e;">—</div>
    <div id="ut-ay-net-sub" style="font-size:10px; color:#64748b; margin-top:2px;">kWh</div>
  </div>
</div>

<!-- TABLO -->
<div style="background:rgba(15,23,42,0.4); border:1px solid rgba(255,255,255,0.06); border-radius:12px; overflow:hidden; margin-bottom:18px;">
  <table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
      <tr style="background:rgba(255,255,255,0.04); border-bottom:1px solid rgba(255,255,255,0.06); color:#94a3b8;">
        <th style="padding:10px 8px; text-align:left; width:36px;"></th>
        <th style="padding:10px 12px; text-align:left; font-weight:600;">Tarih</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600;">TY1 Üretim</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600;">TY2 Üretim</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600;">TY2 Tüketim</th>
        <th style="padding:10px 12px; text-align:right; font-weight:600;">NET</th>
      </tr>
    </thead>
    <tbody id="ut-tablo"></tbody>
  </table>
</div>

<!-- CIZGI GRAFIK - URETIM/TUKETIM -->
<div style="background:rgba(15,23,42,0.4); border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:14px; margin-bottom:18px;">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
    <div style="font-size:13px; font-weight:600; color:#22c55e;">📈 Günlük Üretim/Tüketim (kWh)</div>
    <div style="font-size:11px; color:#94a3b8;">
      <span style="display:inline-flex; align-items:center; gap:4px; margin-right:12px;"><span style="width:10px; height:10px; border-radius:2px; background:#60a5fa;"></span>Üretim</span>
      <span style="display:inline-flex; align-items:center; gap:4px;"><span style="width:10px; height:10px; border-radius:2px; background:#ef4444;"></span>Tüketim</span>
    </div>
  </div>
  <div style="position:relative; width:100%; height:240px;">
    <canvas id="ut-chart"></canvas>
  </div>
</div>

</div>
<!-- ====================== MALIYETLER SEKMESI SONU ====================== -->

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
  if (ad === 'maliyetler') { mltYukle(); utYukle(); }
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
  let html = '';
  workers.sort((a,b) => a.name.localeCompare(b.name)).forEach(w => {
    const d = durumBilgisi(w.durum);
    html += '<div class="cihaz-card ' + w.durum + '" onclick="cihazDetay(\\'' + w.name + '\\')">'
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
        cizGrafikLine('chart', d.history);
      }
    }
  });
}

function kapatModal() { document.getElementById('modal').classList.remove('active'); }

function cizGrafikLine(canvasId, data) {
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
  
  ctx.strokeStyle = 'rgba(255,255,255,0.05)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = h * i / 4;
    ctx.beginPath(); ctx.moveTo(45, y); ctx.lineTo(w, y); ctx.stroke();
  }
  ctx.fillStyle = '#64748b';
  ctx.font = '9px Inter';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const v = max - (max * i / 4);
    ctx.fillText(Math.round(v).toLocaleString('tr-TR'), 41, h * i / 4 + 4);
  }
  
  const gradient = ctx.createLinearGradient(0, 0, 0, h);
  gradient.addColorStop(0, 'rgba(34,197,94,0.4)');
  gradient.addColorStop(1, 'rgba(34,197,94,0)');
  
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = 45 + (w - 45) * i / (values.length - 1);
    const y = h - (v / max) * h;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.lineTo(w, h); ctx.lineTo(45, h); ctx.closePath();
  ctx.fillStyle = gradient; ctx.fill();
  
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = 45 + (w - 45) * i / (values.length - 1);
    const y = h - (v / max) * h;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#22c55e'; ctx.lineWidth = 2; ctx.stroke();
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
  cizGrafikLine('osos-chart', grafikData);
  
  // Gün listesi (son 14 gün)
  const son14 = gunler.slice(-14).reverse();
  let dayHtml = '';
  son14.forEach(g => {
    const tarih = new Date(g);
    const lbl = tarih.getDate() + '.' + (tarih.getMonth()+1).toString().padStart(2,'0');
    dayHtml += '<button class="osos-day-btn" onclick="ososGunSec(\\'' + g + '\\', this)">' + lbl + '</button>';
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

function yukle() {
  fetch('/api/ozet').then(r => r.json()).then(d => {
    if (d.sinyal) {
      const kart = document.getElementById('status-card');
      const ico = document.getElementById('status-icon');
      kart.className = 'status-card ' + (d.sinyal.veri_var ? (d.sinyal.karli ? '' : 'zarar') : 'gri');
      ico.textContent = d.sinyal.veri_var ? (d.sinyal.karli ? '✓' : '✕') : '⏳';
      document.getElementById('status-title').textContent = d.sinyal.veri_var ? (d.sinyal.karli ? 'ÇALIŞMA VAR' : 'ÇALIŞMA YOK') : 'Veri Bekleniyor';
      document.getElementById('status-sub').textContent = d.sinyal.mesaj || '';
    }
    if (d.btc) {
      document.getElementById('btc-tl').textContent = d.btc.tl;
      document.getElementById('btc-usd').textContent = '$' + d.btc.usd + ' USD';
    }
    if (d.f2pool) {
      document.getElementById('bugun-btc').textContent = d.f2pool.bugun_btc;
      document.getElementById('bugun-tl').textContent = '~' + d.f2pool.bugun_tl + ' TL';
      document.getElementById('dun-btc').textContent = d.f2pool.dun_btc;
      document.getElementById('dun-tl').textContent = '~' + d.f2pool.dun_tl + ' TL';
      document.getElementById('toplam-hash').innerHTML = d.f2pool.hash + ' <span style="font-size:14px;color:#64748b">TH/s</span>';
    }
    if (d.aylik) {
      document.getElementById('ay-kar').textContent = '+' + d.aylik.kar;
      document.getElementById('ay-gun').textContent = 'TL | ' + d.aylik.gun + ' gün';
      document.getElementById('f2-title').textContent = d.aylik.ay + ' Toplam';
      document.getElementById('f2-subtitle').textContent = d.aylik.gun + ' gün üretim';
      document.getElementById('f2-big').innerHTML = d.aylik.btc + '<span> BTC</span>';
      document.getElementById('f2-small').textContent = '~' + d.aylik.tl + ' TL';
    }
    if (d.aylik_ptf) aylikRender(d.aylik_ptf);
    if (d.gunluk_liste) {
      let html = '';
      d.gunluk_liste.forEach(g => {
        html += '<div class="daily-item"><div class="daily-date">' + g.tarih + '</div><div><div class="daily-btc">' + g.btc + ' BTC</div><div class="daily-hash">' + g.hash + ' TH/s</div></div><div class="daily-tl"><div class="daily-tl-val">' + g.tl + ' TL</div></div></div>';
      });
      document.getElementById('daily-list').innerHTML = html || '<div class="empty-state">Veri yok</div>';
    }
    if (d.workers) cihazRender(d.workers);
    document.getElementById('guncelleme').textContent = 'Güncellendi: ' + new Date().toLocaleTimeString('tr-TR');
  });
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
    dayHtml += '<button class="osos-day-btn' + (i === 0 ? ' active' : '') + '" onclick="invGunSec(\\'' + g + '\\', this)">' + lbl + '</button>';
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

    html += '<div class="cihaz-card ' + cls + '" onclick="invDetay(\\'' + inv.devId + '\\')">'
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

function antYukle() {
  document.getElementById('ant-info-title').textContent = 'Yükleniyor...';
  fetch('/api/antminer').then(r => r.json()).then(d => {
    if (d.hata) {
      document.getElementById('ant-info-title').textContent = 'Veri yok';
      document.getElementById('ant-info-sub').textContent = d.hata;
      return;
    }
    antData = d;
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
    modelHtml += '<div class="yillik-card">'
      + '<div class="yillik-title">⛏️ ' + model + ' × ' + info.count + ' adet</div>'
      + '<div class="yillik-grid">'
      + '<div class="yillik-stat"><div class="yillik-lbl">Toplam Hash</div><div class="yillik-val" style="color:#fbbf24">' + Math.round(info.hashrate).toLocaleString('tr-TR') + '</div><div class="yillik-lbl">TH/s</div></div>'
      + '<div class="yillik-stat"><div class="yillik-lbl">Hedef</div><div class="yillik-val" style="color:#60a5fa">' + Math.round(info.target).toLocaleString('tr-TR') + '</div><div class="yillik-lbl">TH/s</div></div>'
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
  html += '<button onclick="antKomut(\\'wake\\', [' + d.suffix + '], \\'' + (d.name || 'Miner-'+d.suffix) + '\\')" style="flex:1; background:linear-gradient(135deg,#22c55e,#16a34a); color:white; border:none; padding:12px; border-radius:10px; font-weight:700; cursor:pointer; font-size:13px;">▶️ Çalıştır</button>';
  html += '<button onclick="antKomut(\\'sleep\\', [' + d.suffix + '], \\'' + (d.name || 'Miner-'+d.suffix) + '\\')" style="flex:1; background:linear-gradient(135deg,#f59e0b,#d97706); color:white; border:none; padding:12px; border-radius:10px; font-weight:700; cursor:pointer; font-size:13px;">💤 Uyut</button>';
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
  const isim = (d.name || ('Miner-'+d.suffix)).replace(/'/g, "\\'");
  html += '<div style="display:flex; gap:8px;">';
  html += '<button onclick="antKomut(\\'wake\\',[' + d.suffix + '],\\'' + isim + '\\')" style="flex:1; background:linear-gradient(135deg,#22c55e,#16a34a); color:white; border:none; padding:14px; border-radius:10px; font-weight:900; cursor:pointer; font-size:13px;">▶️ Çalıştır</button>';
  html += '<button onclick="antKomut(\\'sleep\\',[' + d.suffix + '],\\'' + isim + '\\')" style="flex:1; background:linear-gradient(135deg,#f59e0b,#d97706); color:white; border:none; padding:14px; border-radius:10px; font-weight:900; cursor:pointer; font-size:13px;">💤 Uyut</button>';
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
      html += '<button onclick="cmmOnayKarar(\\'' + o.id + '\\',\\'onayla\\')" style="flex:1; background:linear-gradient(135deg,#22c55e,#16a34a); color:white; border:none; padding:10px; border-radius:8px; font-weight:900; cursor:pointer; font-size:12px;">✅ ONAYLA</button>';
      html += '<button onclick="cmmOnayKarar(\\'' + o.id + '\\',\\'reddet\\')" style="flex:1; background:rgba(239,68,68,0.2); color:#f87171; border:1px solid rgba(239,68,68,0.4); padding:10px; border-radius:8px; font-weight:900; cursor:pointer; font-size:12px;">❌ REDDET</button>';
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
    
    // KPI
    document.getElementById('mlt-toplam').textContent = fmtTRY(d.toplam_maliyet_tl);
    document.getElementById('mlt-toplam-sub').textContent = d.gun_sayisi + ' gün · Ort: ' + fmtTRY(d.ort_gunluk_maliyet_tl) + '/gün';
    document.getElementById('mlt-tuketim').textContent = fmtNum(d.toplam_tuketim_kwh);
    document.getElementById('mlt-birim').textContent = d.ort_birim_fiyat_tl_kwh ? d.ort_birim_fiyat_tl_kwh.toFixed(4) : '—';
    document.getElementById('mlt-ortptf').textContent = fmtNum(d.ort_ptf_tl_mwh);
    
    // Son günü otomatik aç
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
    const bg = acik ? 'background:rgba(96,165,250,0.05);' : '';
    const icon = acik ? '▼' : '▶';
    const iconColor = acik ? '#60a5fa' : '#64748b';
    
    tbl += '<tr style="border-bottom:1px solid rgba(255,255,255,0.04); cursor:pointer; ' + bg + '" onclick="mltGunAc(\'' + g.tarih + '\')">';
    tbl += '<td style="padding:12px 8px; text-align:center; color:' + iconColor + '; font-size:11px;">' + icon + '</td>';
    tbl += '<td style="padding:12px; color:#cbd5e1; font-weight:' + (acik?'700':'400') + ';">' + dateStr + '</td>';
    tbl += '<td style="padding:12px; text-align:right; color:#60a5fa; font-size:14px;">' + fmtNum(g.toplam_tuketim_kwh) + '</td>';
    tbl += '<td style="padding:12px; text-align:right; color:#a855f7;">' + fmtNum(g.ort_ptf_tl_mwh) + '</td>';
    tbl += '<td style="padding:12px; text-align:right; color:#fbbf24;">' + g.ort_birim_fiyat_tl_kwh.toFixed(4) + '</td>';
    tbl += '<td style="padding:12px; text-align:right; color:#ef4444; font-weight:700; font-size:14px;">' + fmtTRY(g.toplam_maliyet_tl) + '</td>';
    tbl += '</tr>';
    
    if (acik && g.saatler) {
      tbl += '<tr style="background:rgba(0,0,0,0.2);"><td colspan="6" style="padding:12px;">';
      tbl += '<div style="background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.04); border-radius:8px; overflow:hidden;">';
      tbl += '<table style="width:100%; border-collapse:collapse; font-size:11px;">';
      tbl += '<thead><tr style="background:rgba(255,255,255,0.02); color:#94a3b8;">';
      tbl += '<th style="padding:6px 10px; text-align:left;">Saat</th>';
      tbl += '<th style="padding:6px 10px; text-align:right;">Tüketim (kWh)</th>';
      tbl += '<th style="padding:6px 10px; text-align:right;">PTF (TL/MWh)</th>';
      tbl += '<th style="padding:6px 10px; text-align:right;">Enerji (TL/kWh)</th>';
      tbl += '<th style="padding:6px 10px; text-align:right;">Tutar (₺)</th>';
      tbl += '</tr></thead><tbody>';
      
      g.saatler.forEach(s => {
        const enerji = (s.ptf/1000 + 602.51/1000) * 1.05;
        const pahalı = s.ptf > 2000;
        const renkTutar = pahalı ? '#ef4444' : '#cbd5e1';
        tbl += '<tr style="border-top:1px solid rgba(255,255,255,0.03);">';
        tbl += '<td style="padding:5px 10px; color:#94a3b8;">' + String(s.saat).padStart(2,'0') + ':00</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#60a5fa;">' + s.tuketim.toFixed(1) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:' + (pahalı?'#ef4444':'#a855f7') + ';">' + Math.round(s.ptf) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#fbbf24;">' + enerji.toFixed(4) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:' + renkTutar + '; font-weight:700;">' + Math.round(s.maliyet).toLocaleString('tr-TR') + '</td>';
        tbl += '</tr>';
      });
      
      tbl += '<tr style="border-top:2px solid rgba(96,165,250,0.3); background:rgba(255,255,255,0.02);">';
      tbl += '<td style="padding:7px 10px; font-weight:700; color:#fff;">Toplam</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:700; color:#60a5fa;">' + fmtNum(g.toplam_tuketim_kwh) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:700; color:#a855f7;">' + fmtNum(g.ort_ptf_tl_mwh) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:700; color:#fbbf24;">' + g.ort_birim_fiyat_tl_kwh.toFixed(4) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:700; color:#ef4444;">' + fmtTRY(g.toplam_maliyet_tl) + '</td>';
      tbl += '</tr>';
      
      tbl += '</tbody></table></div></td></tr>';
    }
  });
  
  // Genel toplam
  tbl += '<tr style="background:rgba(239,68,68,0.08); border-top:2px solid rgba(239,68,68,0.4);">';
  tbl += '<td style="padding:12px 8px;"></td>';
  tbl += '<td style="padding:12px; font-weight:900; color:#fff;">TOPLAM (' + mltData.gun_sayisi + ' gün)</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:900; color:#60a5fa; font-size:14px;">' + fmtNum(mltData.toplam_tuketim_kwh) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:900; color:#a855f7;">' + fmtNum(mltData.ort_ptf_tl_mwh) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:900; color:#fbbf24;">' + mltData.ort_birim_fiyat_tl_kwh.toFixed(4) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:900; color:#ef4444; font-size:16px;">' + fmtTRY(mltData.toplam_maliyet_tl) + '</td>';
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
  const labels = gunler.map(g => g.tarih.slice(-2));  // gun
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
        borderColor: '#60a5fa',
        backgroundColor: 'rgba(96,165,250,0.15)',
        borderWidth: 2,
        pointRadius: 4,
        pointBackgroundColor: '#60a5fa',
        pointBorderColor: '#0f172a',
        pointBorderWidth: 1.5,
        tension: 0.25,
        fill: true
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => 'Gün ' + items[0].label,
            label: (item) => item.parsed.y.toLocaleString('tr-TR') + ' kWh'
          }
        }
      },
      scales: {
        x: {
          title: { display: true, text: 'Gün', color: '#94a3b8', font: { size: 11 } },
          grid: { display: false },
          ticks: { color: '#94a3b8', font: { size: 10 } }
        },
        y: {
          title: { display: true, text: 'Tüketim (kWh)', color: '#94a3b8', font: { size: 11 } },
          beginAtZero: true,
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { color: '#94a3b8', font: { size: 10 }, callback: v => v.toLocaleString('tr-TR') }
        }
      },
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
      netEl.style.color = '#22c55e';
      netSub.textContent = 'kWh fazla üretim';
    } else {
      netEl.textContent = fmtNum(a.net);
      netEl.style.color = '#ef4444';
      netSub.textContent = 'kWh eksik üretim';
    }
    
    // Son gün otomatik aç
    const aylikGunler = a.gunler || [];
    if (aylikGunler.length > 0 && !utAcikGun) {
      utAcikGun = aylikGunler[aylikGunler.length - 1].tarih;
      // Saatlik veriyi yukle
      utGunDetayYukle(utAcikGun);
    } else {
      utTabloRender();
      utChartRender();
    }
  }).catch(e => console.error('UT hata:', e));
}

function utGunDetayYukle(tarih) {
  // Bu gun icin saatlik veriyi cek
  fetch('/api/uretim_tuketim?gun=' + tarih + '&ay=' + tarih.slice(0,7)).then(r => r.json()).then(d => {
    if (d.gunluk && d.gunluk.saatlik) {
      // Aylik veriye ekle
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
    // Saatlik veri yoksa cek
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
    const bg = acik ? 'background:rgba(34,197,94,0.05);' : '';
    const icon = acik ? '▼' : '▶';
    const iconColor = acik ? '#22c55e' : '#64748b';
    const netRenk = g.fazla_uretim ? '#22c55e' : '#ef4444';
    const netIcon = g.fazla_uretim ? '🟢' : '🔴';
    const netPrefix = g.fazla_uretim ? '+' : '';
    
    tbl += '<tr style="border-bottom:1px solid rgba(255,255,255,0.04); cursor:pointer; ' + bg + '" onclick="utGunAc(\'' + g.tarih + '\')">';
    tbl += '<td style="padding:12px 8px; text-align:center; color:' + iconColor + '; font-size:11px;">' + icon + '</td>';
    tbl += '<td style="padding:12px; color:#cbd5e1; font-weight:' + (acik?'700':'400') + ';">' + dateStr + '</td>';
    tbl += '<td style="padding:12px; text-align:right; color:#fbbf24;">' + fmtNum(g.ty1_uretim) + '</td>';
    tbl += '<td style="padding:12px; text-align:right; color:#f59e0b;">' + fmtNum(g.ty2_uretim) + '</td>';
    tbl += '<td style="padding:12px; text-align:right; color:#ef4444;">' + fmtNum(g.ty2_tuketim) + '</td>';
    tbl += '<td style="padding:12px; text-align:right; color:' + netRenk + '; font-weight:700; font-size:14px;">' + netIcon + ' ' + netPrefix + fmtNum(g.net) + '</td>';
    tbl += '</tr>';
    
    if (acik && g.saatlik) {
      tbl += '<tr style="background:rgba(0,0,0,0.2);"><td colspan="6" style="padding:12px;">';
      tbl += '<div style="background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.04); border-radius:8px; overflow:hidden;">';
      tbl += '<table style="width:100%; border-collapse:collapse; font-size:11px;">';
      tbl += '<thead><tr style="background:rgba(255,255,255,0.02); color:#94a3b8;">';
      tbl += '<th style="padding:6px 10px; text-align:left;">Saat</th>';
      tbl += '<th style="padding:6px 10px; text-align:right;">TY1 Üretim</th>';
      tbl += '<th style="padding:6px 10px; text-align:right;">TY2 Üretim</th>';
      tbl += '<th style="padding:6px 10px; text-align:right;">Toplam Ü</th>';
      tbl += '<th style="padding:6px 10px; text-align:right;">TY2 Tüketim</th>';
      tbl += '<th style="padding:6px 10px; text-align:right;">NET</th>';
      tbl += '</tr></thead><tbody>';
      
      g.saatlik.forEach(s => {
        const renk = s.fazla_uretim ? '#22c55e' : '#ef4444';
        const ico = s.fazla_uretim ? '🟢' : '🔴';
        const pre = s.fazla_uretim ? '+' : '';
        tbl += '<tr style="border-top:1px solid rgba(255,255,255,0.03);">';
        tbl += '<td style="padding:5px 10px; color:#94a3b8;">' + String(s.saat).padStart(2,'0') + ':00</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#fbbf24;">' + Math.round(s.ty1_uretim) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#f59e0b;">' + Math.round(s.ty2_uretim) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#60a5fa;">' + Math.round(s.toplam_uretim) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:#ef4444;">' + Math.round(s.ty2_tuketim) + '</td>';
        tbl += '<td style="padding:5px 10px; text-align:right; color:' + renk + '; font-weight:700;">' + ico + ' ' + pre + Math.round(s.net) + '</td>';
        tbl += '</tr>';
      });
      
      tbl += '<tr style="border-top:2px solid rgba(34,197,94,0.3); background:rgba(255,255,255,0.02);">';
      tbl += '<td style="padding:7px 10px; font-weight:700; color:#fff;">Toplam</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:700; color:#fbbf24;">' + fmtNum(g.ty1_uretim) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:700; color:#f59e0b;">' + fmtNum(g.ty2_uretim) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:700; color:#60a5fa;">' + fmtNum(g.toplam_uretim) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:700; color:#ef4444;">' + fmtNum(g.ty2_tuketim) + '</td>';
      tbl += '<td style="padding:7px 10px; text-align:right; font-weight:700; color:' + netRenk + ';">' + netPrefix + fmtNum(g.net) + '</td>';
      tbl += '</tr>';
      
      tbl += '</tbody></table></div></td></tr>';
    }
  });
  
  // Genel toplam
  const a = utData.aylik || {};
  const totalNetRenk = (a.net || 0) >= 0 ? '#22c55e' : '#ef4444';
  const totalNetPrefix = (a.net || 0) >= 0 ? '+' : '';
  tbl += '<tr style="background:rgba(34,197,94,0.08); border-top:2px solid rgba(34,197,94,0.4);">';
  tbl += '<td style="padding:12px 8px;"></td>';
  tbl += '<td style="padding:12px; font-weight:900; color:#fff;">TOPLAM (' + (a.gun_sayisi || 0) + ' gün)</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:900; color:#fbbf24;">' + fmtNum(aylikGunler.reduce((s,g)=>s+g.ty1_uretim,0)) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:900; color:#f59e0b;">' + fmtNum(aylikGunler.reduce((s,g)=>s+g.ty2_uretim,0)) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:900; color:#ef4444;">' + fmtNum(a.toplam_tuketim) + '</td>';
  tbl += '<td style="padding:12px; text-align:right; font-weight:900; color:' + totalNetRenk + '; font-size:14px;">' + totalNetPrefix + fmtNum(a.net) + '</td>';
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
        {
          label: 'Üretim',
          data: uretimData,
          borderColor: '#60a5fa',
          backgroundColor: 'rgba(96,165,250,0.1)',
          borderWidth: 2,
          pointRadius: 3,
          pointBackgroundColor: '#60a5fa',
          tension: 0.25,
          fill: false
        },
        {
          label: 'Tüketim',
          data: tuketimData,
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239,68,68,0.1)',
          borderWidth: 2,
          pointRadius: 3,
          pointBackgroundColor: '#ef4444',
          tension: 0.25,
          fill: false
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => 'Gün ' + items[0].label,
            label: (item) => item.dataset.label + ': ' + item.parsed.y.toLocaleString('tr-TR') + ' kWh'
          }
        }
      },
      scales: {
        x: {
          title: { display: true, text: 'Gün', color: '#94a3b8', font: { size: 11 } },
          grid: { display: false },
          ticks: { color: '#94a3b8', font: { size: 10 } }
        },
        y: {
          title: { display: true, text: 'kWh', color: '#94a3b8', font: { size: 11 } },
          beginAtZero: true,
          grid: { color: 'rgba(255,255,255,0.05)' },
          ticks: { color: '#94a3b8', font: { size: 10 }, callback: v => v.toLocaleString('tr-TR') }
        }
      },
      interaction: { intersect: false, mode: 'index' }
    }
  });
}

// ======================== URETIM/TUKETIM SONU ========================

// ====================== ANTMINER SONU ======================

if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js'); }
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
    return render_template_string(PANEL_HTML, kullanici=session["kullanici"], rol=session["rol"])

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
    data = github_oku("osos_gecmis.json")
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
    btc_try = sinyal.get("btc_try", 0) if sinyal else 0
    btc_usd = sinyal.get("btc_usd", 0) if sinyal else 0
    return jsonify({
        "name": name, "anlik": anlik, "h1": h1, "h24": h24, "durum": durum,
        "last_share": datetime.datetime.fromtimestamp(worker["last_share_at"]).strftime("%d.%m %H:%M") if worker.get("last_share_at") else "—",
        "history": history, "bugun_saat": bugun_saat, "h24_saat": h24_saat,
        "gunluk_btc": cihaz_btc, "gunluk_tl": cihaz_btc * btc_try, "gunluk_usd": cihaz_btc * btc_usd
    })

@app.route("/api/ozet")
def ozet():
    if "kullanici" not in session:
        return jsonify({"hata":"yetkisiz"}), 401
    sonuc = {}
    sinyal = github_oku("sinyal.json")
    btc_try = sinyal.get("btc_try", 0) if sinyal else 0
    btc_usd = sinyal.get("btc_usd", 0) if sinyal else 0
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
    
    Formul: (PTF[saat]/1000 + YEKDEM/1000) * 1.05 * tuketim[saat]
    PTF: TL/MWh -> TL/kWh icin /1000
    YEKDEM: 602.51 kr/MWh -> TL/kWh icin /1000
    """
    if "kullanici" not in session:
        return jsonify({"hata": "yetkisiz"}), 401
    
    YEKDEM_KR_MWH = 602.51
    DAGITIM_KATSAYI = 1.05  # %5 dagitim/kayip
    
    ay = request.args.get("ay")  # "2026-05" - bos ise mevcut ay
    if not ay:
        ay = datetime.datetime.now().strftime("%Y-%m")
    
    # 1. PTF verisi (aylik_ptf.json)
    ayptf = github_oku("aylik_ptf.json") or {}
    ay_ptf = ayptf.get(ay, {})
    
    # 2. OSOS verisi (saatlik tuketim)
    osos = github_oku("osos_gecmis.json") or {}
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
        if not gun_str.startswith(ay):
            continue
        
        gun_no = gun_str[8:10]
        gun_ptf = ay_ptf.get(gun_no)  # 24 saatlik PTF (TL/MWh)
        if not gun_ptf or len(gun_ptf) != 24:
            continue  # PTF yoksa gun atlaniyor
        
        saatler_data = aksaray3[gun_str]
        
        gun_maliyet = 0
        gun_tuketim = 0
        gun_ptf_toplam = 0
        gun_saatler = []
        
        for saat_int in range(24):
            saat_key = f"{saat_int:02d}"
            saat_veri = saatler_data.get(saat_key, {})
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
    osos = github_oku("osos_gecmis.json") or {}
    
    ty1 = osos.get("tekyildiz_1", {}).get("veri", {})
    ty2 = osos.get("tekyildiz_2", {}).get("veri", {})
    
    # Saatlik veri olusturma yardimcisi
    def get_saatlik(abone_veri, gun_str, alan):
        """abone_veri[gun_str][saat][cekis|veris] -> saatlik liste"""
        saatler_data = abone_veri.get(gun_str, {})
        return [float(saatler_data.get(f"{h:02d}", {}).get(alan, 0)) for h in range(24)]
    
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
