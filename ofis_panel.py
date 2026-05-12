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

MANIFEST = json.dumps({
    "name": "Otocoin", "short_name": "Otocoin",
    "description": "Aksaray Enerji Yonetim Paneli",
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
        with urllib.request.urlopen(f"{GITHUB_RAW}/{dosya}", timeout=10) as r:
            return json.loads(r.read())
    except:
        return None

def f2pool_son_gunler(gun=30):
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        bas = int((now - datetime.timedelta(days=gun)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        bit = int(now.timestamp())
        data = json.dumps({"currency": "bitcoin", "mining_user_name": F2POOL_USER,
            "type": "revenue", "start_time": bas, "end_time": bit}).encode()
        req = urllib.request.Request("https://api.f2pool.com/v2/assets/transactions/list",
            data=data, headers={"Content-Type":"application/json", "F2P-API-SECRET":F2POOL_TOKEN}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
        return result.get("transactions", [])
    except:
        return []

def f2pool_bugun_tahmini():
    try:
        data = json.dumps({"currency": "bitcoin", "mining_user_name": F2POOL_USER,
            "calculate_estimated_income": True}).encode()
        req = urllib.request.Request("https://api.f2pool.com/v2/assets/balance",
            data=data, headers={"Content-Type":"application/json", "F2P-API-SECRET":F2POOL_TOKEN}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
        return result.get("balance_info", {}).get("estimated_today_income", 0)
    except:
        return 0

def f2pool_hashrate():
    try:
        data = json.dumps({"currency": "bitcoin", "mining_user_name": F2POOL_USER}).encode()
        req = urllib.request.Request("https://api.f2pool.com/v2/hash_rate/info",
            data=data, headers={"Content-Type":"application/json", "F2P-API-SECRET":F2POOL_TOKEN}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
        info = result.get("info", {})
        return {"anlik": info.get("hash_rate", 0) / 1e12, "h1": info.get("h1_hash_rate", 0) / 1e12,
            "h24": info.get("h24_hash_rate", 0) / 1e12}
    except:
        return {"anlik": 0, "h1": 0, "h24": 0}

LOGIN_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#16a34a">
<link rel="manifest" href="/manifest.json">
<title>Otocoin</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Inter', -apple-system, sans-serif; background: #050917; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
.card { background: linear-gradient(180deg, #0a0e1a 0%, #050917 100%); border: 1px solid #1e293b; border-radius: 28px; padding: 40px 32px; width: 100%; max-width: 380px; }
.logo-wrap { text-align: center; margin-bottom: 28px; }
.logo { width: 80px; height: 80px; background: linear-gradient(135deg, #16a34a, #22c55e, #4ade80); border-radius: 22px; display: inline-flex; align-items: center; justify-content: center; font-size: 42px; margin-bottom: 14px; box-shadow: 0 8px 30px rgba(34,197,94,0.5); }
h1 { font-size: 28px; font-weight: 900; color: white; }
.alt { font-size: 13px; color: #64748b; margin-top: 6px; }
label { font-size: 12px; color: #94a3b8; display: block; margin-bottom: 8px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
input { width: 100%; padding: 14px 16px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; color: white; font-size: 15px; margin-bottom: 18px; outline: none; font-family: inherit; }
input:focus { border-color: #22c55e; }
button { width: 100%; padding: 15px; background: linear-gradient(135deg, #16a34a, #22c55e); color: white; border: none; border-radius: 14px; font-size: 15px; font-weight: 800; cursor: pointer; font-family: inherit; }
.error { background: rgba(220,38,38,0.15); border: 1px solid rgba(220,38,38,0.3); color: #fca5a5; padding: 12px 16px; border-radius: 12px; font-size: 13px; margin-bottom: 18px; text-align: center; }
</style>
</head>
<body>
<div class="card">
  <div class="logo-wrap">
    <div class="logo">⚡</div>
    <h1>Otocoin</h1>
    <div class="alt">Aksaray Enerji Yönetim Sistemi</div>
  </div>
  {% if hata %}<div class="error">{{ hata }}</div>{% endif %}
  <form method="POST" action="/giris">
    <label>Kullanıcı Adı</label>
    <input type="text" name="kullanici" autocomplete="username">
    <label>Şifre</label>
    <input type="password" name="sifre" autocomplete="current-password">
    <button type="submit">Giriş Yap</button>
  </form>
</div>
</body>
</html>"""

PANEL_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#050917">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.json">
<title>Otocoin</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: linear-gradient(180deg, #0a0e1a 0%, #050917 100%); font-family: 'Inter', -apple-system, sans-serif; color: white; min-height: 100vh; padding-bottom: 20px; }
.header { padding: 18px 20px 16px; padding-top: calc(18px + env(safe-area-inset-top)); display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.06); background: rgba(10,14,26,0.9); backdrop-filter: blur(20px); position: sticky; top: 0; z-index: 100; }
.brand { display: flex; align-items: center; gap: 10px; }
.brand-logo { width: 38px; height: 38px; background: linear-gradient(135deg, #16a34a, #22c55e, #4ade80); border-radius: 11px; display: flex; align-items: center; justify-content: center; font-size: 20px; box-shadow: 0 4px 16px rgba(34,197,94,0.4); }
.brand-text { font-size: 18px; font-weight: 900; }
.user-pill { display: flex; align-items: center; gap: 6px; background: rgba(255,255,255,0.05); padding: 6px 10px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.08); }
.user-avatar { width: 22px; height: 22px; background: linear-gradient(135deg, #3b82f6, #6366f1); border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-size: 10px; font-weight: 700; }
.user-name { color: #cbd5e1; font-size: 11px; font-weight: 600; }
.cikis-link { background: none; border: 1px solid rgba(255,255,255,0.1); color: #f87171; padding: 6px 12px; border-radius: 10px; font-size: 11px; cursor: pointer; margin-left: 8px; text-decoration: none; }
.tabs { display: flex; padding: 12px 20px 0; gap: 6px; overflow-x: auto; border-bottom: 1px solid rgba(255,255,255,0.04); background: rgba(10,14,26,0.7); backdrop-filter: blur(20px); position: sticky; top: 73px; z-index: 90; }
.tabs::-webkit-scrollbar { display: none; }
.tab { display: flex; align-items: center; gap: 6px; padding: 10px 14px; font-size: 12px; font-weight: 600; color: #64748b; border-bottom: 2px solid transparent; white-space: nowrap; cursor: pointer; margin-bottom: -1px; }
.tab.active { color: #22c55e; border-bottom-color: #22c55e; }
.content { padding: 16px 16px 24px; }
.status-card { background: linear-gradient(135deg, rgba(22,163,74,0.2) 0%, rgba(22,163,74,0.05) 100%); border: 1px solid rgba(22,163,74,0.3); border-radius: 20px; padding: 18px; margin-bottom: 14px; position: relative; overflow: hidden; }
.status-card.zarar { background: linear-gradient(135deg, rgba(220,38,38,0.2) 0%, rgba(220,38,38,0.05) 100%); border-color: rgba(220,38,38,0.3); }
.status-card.gri { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.06); }
.status-row { display: flex; align-items: center; gap: 14px; }
.status-icon { width: 52px; height: 52px; background: linear-gradient(135deg, #16a34a, #22c55e); border-radius: 16px; display: flex; align-items: center; justify-content: center; font-size: 26px; }
.status-card.zarar .status-icon { background: linear-gradient(135deg, #dc2626, #ef4444); }
.status-card.gri .status-icon { background: rgba(255,255,255,0.1); }
.status-title { font-size: 18px; font-weight: 900; }
.status-sub { color: rgba(255,255,255,0.6); font-size: 11px; margin-top: 2px; }
.status-pulse { width: 10px; height: 10px; background: #22c55e; border-radius: 50%; margin-left: auto; animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(34,197,94,0.7); } 50% { box-shadow: 0 0 0 8px rgba(34,197,94,0); } }
.kpi-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 14px; }
.kpi-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 16px; padding: 14px; }
.kpi-card.highlight { background: linear-gradient(135deg, rgba(59,130,246,0.15) 0%, rgba(59,130,246,0.05) 100%); border-color: rgba(59,130,246,0.25); }
.kpi-label { font-size: 10px; color: #64748b; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.kpi-value { font-size: 22px; font-weight: 900; }
.kpi-sub { font-size: 11px; color: #94a3b8; margin-top: 4px; }
.section-header { display: flex; align-items: center; justify-content: space-between; margin: 14px 0 10px; }
.section-title { font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; }
.day-toggle { display: flex; gap: 4px; background: rgba(255,255,255,0.05); padding: 3px; border-radius: 10px; }
.day-btn { padding: 6px 12px; font-size: 11px; font-weight: 600; color: #64748b; border-radius: 8px; cursor: pointer; border: none; background: transparent; font-family: inherit; }
.day-btn.active { background: linear-gradient(135deg, #16a34a, #22c55e); color: white; }
.ptf-hourly { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.ptf-cell { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 8px 6px; text-align: center; }
.ptf-cell.karli { background: linear-gradient(135deg, rgba(22,163,74,0.2), rgba(22,163,74,0.05)); border-color: rgba(22,163,74,0.3); }
.ptf-cell.kapali { background: linear-gradient(135deg, rgba(124,58,237,0.25), rgba(124,58,237,0.1)); border-color: rgba(168,85,247,0.6); }
.ptf-saat { font-size: 11px; font-weight: 700; color: #cbd5e1; }
.ptf-price { font-size: 13px; font-weight: 800; margin-top: 2px; }
.ptf-cell.karli .ptf-price { color: #4ade80; }
.ptf-cell.kapali .ptf-price { color: #c4b5fd; }

/* AYLIK TABLO */
.aylik-wrap { overflow-x: auto; margin-top: 8px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.06); background: rgba(255,255,255,0.02); }
.aylik-table { width: 100%; border-collapse: collapse; font-size: 10px; }
.aylik-table th { background: linear-gradient(180deg, #1e293b, #0f172a); color: #94a3b8; font-weight: 700; font-size: 9px; padding: 8px 4px; text-align: center; position: sticky; top: 0; }
.aylik-table th.saat-head { background: linear-gradient(180deg, #16a34a, #15803d); color: white; min-width: 38px; position: sticky; left: 0; z-index: 3; }
.aylik-table td { padding: 5px 3px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.03); font-weight: 700; min-width: 38px; }
.aylik-table td.saat-cell { background: rgba(22,163,74,0.1); font-weight: 800; color: #4ade80; position: sticky; left: 0; z-index: 1; }
.aylik-table tr:nth-child(odd) td { background: rgba(255,255,255,0.01); }
.aylik-table tr:nth-child(odd) td.saat-cell { background: rgba(22,163,74,0.13); }
.l0 { color: #4ade80; }
.l1 { color: #86efac; }
.l2 { color: #fbbf24; }
.l3 { color: #fb923c; }
.l4 { color: #f87171; }
.l5 { color: #dc2626; font-weight: 900; }
.aylik-table td.kapali-cell { color: #c4b5fd !important; background: linear-gradient(135deg, rgba(124,58,237,0.25), rgba(124,58,237,0.1)) !important; border: 1px solid rgba(168,85,247,0.5); font-weight: 900; }

.f2-summary { background: linear-gradient(135deg, rgba(245,158,11,0.15) 0%, rgba(245,158,11,0.05) 100%); border: 1px solid rgba(245,158,11,0.25); border-radius: 18px; padding: 16px; margin-bottom: 14px; }
.f2-icon-wrap { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.f2-icon { width: 44px; height: 44px; background: linear-gradient(135deg, #f59e0b, #fbbf24); border-radius: 14px; display: flex; align-items: center; justify-content: center; font-size: 22px; }
.f2-title { font-size: 15px; font-weight: 800; }
.f2-subtitle { color: #94a3b8; font-size: 11px; margin-top: 1px; }
.f2-big { font-size: 26px; font-weight: 900; }
.f2-big span { color: #fbbf24; }
.f2-small { font-size: 12px; color: #94a3b8; margin-top: 2px; }
.daily-item { display: flex; align-items: center; gap: 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; padding: 10px 12px; margin-bottom: 6px; }
.daily-date { font-size: 11px; color: #94a3b8; font-weight: 600; min-width: 80px; }
.daily-btc { font-size: 13px; font-weight: 800; }
.daily-hash { font-size: 10px; color: #64748b; margin-top: 1px; }
.daily-tl { margin-left: auto; text-align: right; }
.daily-tl-val { font-size: 13px; font-weight: 800; color: #4ade80; }
.guncelleme { font-size: 11px; color: #334155; text-align: center; margin-top: 14px; }
.empty-state { text-align: center; padding: 40px 20px; color: #475569; font-size: 13px; }
.tab-content { display: none; }
.tab-content.active { display: block; }
</style>
</head>
<body>
<div class="header">
  <div class="brand">
    <div class="brand-logo">⚡</div>
    <div class="brand-text">Otocoin</div>
  </div>
  <div style="display:flex;align-items:center;gap:8px">
    <div class="user-pill">
      <div class="user-avatar">{{ kullanici[:2].upper() }}</div>
      <div class="user-name">{{ kullanici }}</div>
    </div>
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
        <div>
          <div class="status-title" id="status-title">Yükleniyor...</div>
          <div class="status-sub" id="status-sub"></div>
        </div>
      </div>
    </div>
    <div class="kpi-grid">
      <div class="kpi-card highlight">
        <div class="kpi-label">💰 BTC Fiyatı</div>
        <div class="kpi-value" id="btc-tl">—</div>
        <div class="kpi-sub" id="btc-usd">—</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">📊 Bugünkü Tahmini</div>
        <div class="kpi-value" id="bugun-btc">—</div>
        <div class="kpi-sub" id="bugun-tl">—</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">₿ Dünkü Kazanç</div>
        <div class="kpi-value" id="dun-btc">—</div>
        <div class="kpi-sub" id="dun-tl">—</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">📈 Aylık Net Kar</div>
        <div class="kpi-value" id="ay-kar" style="color:#4ade80">—</div>
        <div class="kpi-sub" id="ay-gun">—</div>
      </div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">⚡ Toplam Hashrate</div>
      <div class="kpi-value" id="toplam-hash" style="color:#60a5fa">—</div>
      <div class="kpi-sub">24 saatlik ortalama</div>
    </div>
  </div>

  <div class="tab-content" id="t-epias">
    <div class="section-header">
  <div class="section-title">📊 Saatlik PTF</div>
  <div class="day-toggle">
    <button class="day-btn active" onclick="ptfGun('bugun', this)">Bugün</button>
    <button class="day-btn" onclick="ptfGun('yarin', this)">Yarın</button>
  </div>
</div>
<div class="ptf-hourly" id="ptf-grid">
  <div class="empty-state" style="grid-column:1/-1">Yükleniyor...</div>
</div>

<div class="kpi-grid" style="margin-top:14px">
  <div class="kpi-card highlight">
    <div class="kpi-label">✅ Karlı Saat</div>
    <div class="kpi-value" id="ptf-karli-saat" style="color:#4ade80">—</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">📈 Günlük Kar</div>
    <div class="kpi-value" id="ptf-kar" style="color:#4ade80">—</div>
    <div class="kpi-sub">TL</div>
  </div>
</div>

    <div class="section-header">
      <div class="section-title">📅 Aylık PTF Tablosu</div>
      <div style="font-size:10px;color:#64748b">⏸ Kapalı saatler mor</div>
    </div>
    <div class="aylik-wrap">
      <table class="aylik-table" id="aylik-table">
        <thead id="aylik-thead"></thead>
        <tbody id="aylik-tbody"></tbody>
      </table>
    </div>
  </div>

  <div class="tab-content" id="t-f2pool">
    <div class="f2-summary">
      <div class="f2-icon-wrap">
        <div class="f2-icon">₿</div>
        <div>
          <div class="f2-title" id="f2-title">Aylık Toplam</div>
          <div class="f2-subtitle" id="f2-subtitle">—</div>
        </div>
      </div>
      <div class="f2-big" id="f2-big">—<span> BTC</span></div>
      <div class="f2-small" id="f2-small">—</div>
    </div>
    <div class="section-title">📅 Günlük Üretim</div>
    <div id="daily-list" style="margin-top:8px">
      <div class="empty-state">Yükleniyor...</div>
    </div>
  </div>

  <div class="tab-content" id="t-cihazlar">
    <div class="empty-state">Saha bilgisayarı bağlantısı yakında<br><br>Cihaz yönetimi saha panelinden yapılacak.</div>
  </div>

  <div class="tab-content" id="t-osos">
    <div class="empty-state">OSOS verisi yakında<br><br>Raspberry Pi kurulduktan sonra aktif olacak.</div>
  </div>

  <div class="guncelleme" id="guncelleme"></div>
</div>

<script>
function sekme(ad, btn) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('t-' + ad).classList.add('active');
}

let ptfBugun = [], ptfYarin = [], karliBugun = [], karliYarin = [];
const ZARARLI_ESIK = 2200;

function renkSinif(v) {
  if (v >= ZARARLI_ESIK) return 'l5 kapali-cell';
  if (v < 500) return 'l0';
  if (v < 1000) return 'l1';
  if (v < 2000) return 'l2';
  return 'l3';
}

function ptfGun(gun, btn) {
  document.querySelectorAll('.day-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  ptfRender(gun);
}

function ptfRender(gun) {
  const veri = gun === 'bugun' ? ptfBugun : ptfYarin;
  let html = '';
  for (let i = 0; i < 24; i++) {
    const ptf = veri[i] || 0;
    const isKapali = ptf >= ZARARLI_ESIK;
    const cls = isKapali ? 'kapali' : 'karli';
    html += `<div class="ptf-cell ${cls}"><div class="ptf-saat">${String(i).padStart(2,'0')}</div><div class="ptf-price">${Math.round(ptf)}</div></div>`;
  }
  document.getElementById('ptf-grid').innerHTML = html;
}

function aylikRender(aylikData) {
  if (!aylikData) {
    document.getElementById('aylik-tbody').innerHTML = '<tr><td colspan="32" class="empty-state">Veri yok</td></tr>';
    return;
  }
  
  const gunler = Object.keys(aylikData).sort();
  if (gunler.length === 0) return;
  
  // Başlık
  let thead = '<tr><th class="saat-head">Saat</th>';
  gunler.forEach(g => { thead += `<th>${g}</th>`; });
  thead += '<th class="saat-head">Ort</th></tr>';
  document.getElementById('aylik-thead').innerHTML = thead;
  
  // Saatler
  let tbody = '';
  for (let saat = 0; saat < 24; saat++) {
    tbody += `<tr><td class="saat-cell">${String(saat).padStart(2,'0')}</td>`;
    let toplam = 0, sayi = 0;
    gunler.forEach(g => {
      const v = aylikData[g][saat] || 0;
      const cls = renkSinif(v);
      tbody += `<td class="${cls}">${Math.round(v)}</td>`;
      toplam += v; sayi++;
    });
    const ort = sayi ? toplam/sayi : 0;
    tbody += `<td class="saat-cell l2">${Math.round(ort)}</td></tr>`;
  }
  
  // Günlük ortalama satırı
  tbody += '<tr style="border-top:2px solid rgba(34,197,94,0.4)"><td class="saat-cell" style="background:linear-gradient(180deg,#16a34a,#15803d);color:white">Ort.</td>';
  let ayToplam = 0, ayCount = 0;
  gunler.forEach(g => {
    const saatler = aylikData[g];
    const t = saatler.reduce((a,b) => a+b, 0);
    const o = t / saatler.length;
    const cls = renkSinif(o);
    tbody += `<td class="${cls}" style="font-weight:900">${Math.round(o)}</td>`;
    ayToplam += t; ayCount += saatler.length;
  });
  const ayOrt = ayCount ? ayToplam/ayCount : 0;
  tbody += `<td class="saat-cell l2" style="font-weight:900">${Math.round(ayOrt)}</td></tr>`;
  
  document.getElementById('aylik-tbody').innerHTML = tbody;
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
    if (d.ptf_bugun) {
      ptfBugun = d.ptf_bugun.fiyatlar || [];
      karliBugun = d.ptf_bugun.karli || [];
      document.getElementById('ptf-karli-saat').innerHTML = karliBugun.length + '<span style="font-size:14px;color:#64748b">/24</span>';
      document.getElementById('ptf-kar').textContent = '+' + (d.ptf_bugun.kar || '—');
      ptfRender('bugun');
    }
    if (d.ptf_yarin) {
      ptfYarin = d.ptf_yarin.fiyatlar || [];
      karliYarin = d.ptf_yarin.karli || [];
    }
    if (d.aylik_ptf) {
      aylikRender(d.aylik_ptf);
    }
    if (d.gunluk_liste) {
      let html = '';
      d.gunluk_liste.forEach(g => {
        html += `<div class="daily-item">
          <div class="daily-date">${g.tarih}</div>
          <div><div class="daily-btc">${g.btc} BTC</div><div class="daily-hash">${g.hash} TH/s</div></div>
          <div class="daily-tl"><div class="daily-tl-val">${g.tl} TL</div></div>
        </div>`;
      });
      document.getElementById('daily-list').innerHTML = html || '<div class="empty-state">Veri yok</div>';
    }
    document.getElementById('guncelleme').textContent = 'Güncellendi: ' + new Date().toLocaleTimeString('tr-TR');
  });
}
yukle();
setInterval(yukle, 60000);
if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js'); }
</script>
</body>
</html>"""

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

    transactions = f2pool_son_gunler(7)
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

    ay_key = datetime.date.today().strftime("%Y-%m")
    ay = github_oku(f"aylik_{ay_key}.json")
    if ay:
        sonuc["aylik"] = {
            "ay":  ay_key, "gun": ay.get("gun_sayisi", 0),
            "btc": f"{ay.get('toplam_btc', 0):.5f}",
            "tl":  f"{ay.get('toplam_btc_tl', 0):,.0f}",
            "kar": f"{ay.get('toplam_kar_tl', 0):,.0f}"
        }

    if sinyal:
        sonuc["ptf_bugun"] = {
            "karli": sinyal.get("karli_saatler", []),
            "fiyatlar": sinyal.get("ptf_saatlik", [0]*24),
            "kar": f"{sinyal.get('gunluk_kar_tl', 0):,.0f}"
        }

    # AYLIK PTF
    aylik_ptf = github_oku("aylik_ptf.json")
    if aylik_ptf:
        ay_data = aylik_ptf.get(ay_key, {})
        sonuc["aylik_ptf"] = ay_data

    # Günlük liste
    gunluk = []
    sorted_tx = sorted(transactions, key=lambda t: t["mining_extra"]["mining_date"], reverse=True)
    for t in sorted_tx[:10]:
        tarih = datetime.datetime.fromtimestamp(t["mining_extra"]["mining_date"], tz=datetime.timezone.utc).strftime("%d.%m.%Y")
        btc = t["changed_balance"]
        ths = t["mining_extra"]["hash_rate"] / 1e12
        gunluk.append({"tarih": tarih, "btc": f"{btc:.5f}", "hash": f"{ths:,.0f}", "tl": f"{btc * btc_try:,.0f}"})
    sonuc["gunluk_liste"] = gunluk

    return jsonify(sonuc)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
