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
</style></head><body>
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
<div class="tab" onclick="sekme('osos', this)">🔋 OSOS</div>
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
