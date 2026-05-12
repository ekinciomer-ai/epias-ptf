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

GITHUB_RAW = "https://raw.githubusercontent.com/ekinciomer-ai/epias-ptf/main"

MANIFEST = json.dumps({
    "name": "Otocoin", "short_name": "Otocoin",
    "description": "Aksaray Enerji Yonetim Paneli",
    "start_url": "/", "display": "standalone",
    "background_color": "#0f172a", "theme_color": "#16a34a",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]
})

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="100" fill="#0f172a"/>
<rect x="60" y="80" width="392" height="300" rx="20" fill="#14532d" stroke="#16a34a" stroke-width="8"/>
<line x1="60" y1="180" x2="452" y2="180" stroke="#16a34a" stroke-width="4" opacity="0.6"/>
<line x1="60" y1="280" x2="452" y2="280" stroke="#16a34a" stroke-width="4" opacity="0.6"/>
<line x1="191" y1="80" x2="191" y2="380" stroke="#16a34a" stroke-width="4" opacity="0.6"/>
<line x1="322" y1="80" x2="322" y2="380" stroke="#16a34a" stroke-width="4" opacity="0.6"/>
<rect x="216" y="380" width="80" height="30" rx="6" fill="#166534"/>
<rect x="156" y="408" width="200" height="16" rx="8" fill="#16a34a"/>
<polygon points="290,110 220,270 262,270 222,400 320,210 272,210 310,110" fill="#ffffff" opacity="0.95"/>
<text x="256" y="478" font-size="56" text-anchor="middle" fill="#22c55e" font-family="Arial" font-weight="900" letter-spacing="4">OTOCOIN</text>
</svg>"""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#16a34a">
<link rel="manifest" href="/manifest.json">
<title>Otocoin</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #0f172a; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
.kart { background: #1e293b; border-radius: 20px; padding: 36px 28px; width: 100%; max-width: 360px; }
.logo-wrap { text-align: center; margin-bottom: 24px; }
.logo-circle { width: 80px; height: 80px; background: linear-gradient(135deg, #16a34a, #22c55e); border-radius: 20px; display: inline-flex; align-items: center; justify-content: center; font-size: 40px; margin-bottom: 12px; }
h1 { font-size: 24px; font-weight: 800; color: white; }
.alt { font-size: 13px; color: #64748b; margin-top: 4px; }
.form { margin-top: 28px; }
label { font-size: 13px; color: #94a3b8; display: block; margin-bottom: 6px; }
input { width: 100%; padding: 13px 14px; background: #0f172a; border: 1px solid #334155; border-radius: 12px; color: white; font-size: 15px; margin-bottom: 16px; outline: none; }
input:focus { border-color: #16a34a; }
button { width: 100%; padding: 14px; background: #16a34a; color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: 700; cursor: pointer; }
.hata { background: #7f1d1d; color: #fca5a5; padding: 10px 14px; border-radius: 10px; font-size: 13px; margin-bottom: 16px; text-align: center; }
</style>
</head>
<body>
<div class="kart">
  <div class="logo-wrap">
    <div class="logo-circle">⚡</div>
    <h1>Otocoin</h1>
    <div class="alt">Aksaray Enerji Yönetim Sistemi</div>
  </div>
  {% if hata %}<div class="hata">{{ hata }}</div>{% endif %}
  <div class="form">
    <form method="POST" action="/giris">
      <label>Kullanıcı Adı</label>
      <input type="text" name="kullanici" autocomplete="username">
      <label>Şifre</label>
      <input type="password" name="sifre" autocomplete="current-password">
      <button type="submit">Giriş Yap</button>
    </form>
  </div>
</div>
<script>if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js');}</script>
</body>
</html>"""

PANEL_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#16a34a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Otocoin">
<link rel="manifest" href="/manifest.json">
<title>Otocoin</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #0f172a; color: white; min-height: 100vh; padding-bottom: 20px; }
.header { background: #1e293b; padding: 14px 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #334155; position: sticky; top: 0; z-index: 10; }
.logo-sm { width: 32px; height: 32px; background: linear-gradient(135deg, #16a34a, #22c55e); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 18px; }
.h-title { font-size: 18px; font-weight: 800; margin-left: 8px; }
.user-name { font-size: 11px; color: #94a3b8; }
.rol-badge { font-size: 10px; padding: 2px 8px; border-radius: 8px; background: #1d4ed8; color: #93c5fd; font-weight: 700; display: inline-block; }
.cikis-btn { background: none; border: 1px solid #334155; color: #94a3b8; padding: 5px 10px; border-radius: 8px; font-size: 12px; cursor: pointer; margin-left: 8px; }
.icerik { padding: 14px; }
.sinyal-kart { border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; display: flex; align-items: center; gap: 12px; border: 1px solid; }
.sinyal-kart.yesil { background: #14532d; border-color: #16a34a; }
.sinyal-kart.kirmizi { background: #7f1d1d; border-color: #dc2626; }
.sinyal-kart.gri { background: #1e293b; border-color: #334155; }
.s-icon { font-size: 30px; }
.s-baslik { font-size: 15px; font-weight: 800; }
.s-alt { font-size: 11px; color: #94a3b8; margin-top: 2px; }
.ozet-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 10px; }
.ozet-kart { background: #1e293b; border-radius: 12px; padding: 12px; }
.ozet-kart .baslik { font-size: 10px; color: #64748b; margin-bottom: 6px; text-transform: uppercase; }
.ozet-kart .deger { font-size: 18px; font-weight: 800; }
.ozet-kart .alt { font-size: 11px; color: #64748b; margin-top: 2px; }
.bolum-baslik { font-size: 11px; font-weight: 700; color: #64748b; margin-bottom: 8px; letter-spacing: 1px; text-transform: uppercase; }
.ptf-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 4px; margin-bottom: 12px; }
.ptf-saat { background: #1e293b; border-radius: 8px; padding: 6px 4px; text-align: center; border: 1px solid #334155; }
.ptf-saat.karli { border-color: #16a34a; background: #14532d; }
.ptf-saat.zarарli { border-color: #dc2626; background: #7f1d1d; }
.ptf-no { font-size: 10px; color: #64748b; }
.ptf-fiyat { font-size: 10px; font-weight: 700; margin-top: 2px; }
.ptf-saat.karli .ptf-fiyat { color: #86efac; }
.ptf-saat.zarарli .ptf-fiyat { color: #fca5a5; }
.aylik-kart { background: #1e293b; border-radius: 12px; padding: 14px; margin-bottom: 10px; }
.aylik-satir { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid #334155; }
.aylik-satir:last-child { border-bottom: none; }
.aylik-lbl { font-size: 12px; color: #94a3b8; }
.aylik-val { font-size: 13px; font-weight: 700; }
.guncelleme { font-size: 11px; color: #334155; text-align: center; margin-top: 12px; }
</style>
</head>
<body>
<div class="header">
  <div style="display:flex;align-items:center">
    <div class="logo-sm">⚡</div>
    <div class="h-title">Otocoin</div>
  </div>
  <div style="display:flex;align-items:center">
    <div style="text-align:right">
      <div class="user-name">{{ kullanici }}</div>
      <span class="rol-badge">{{ rol }}</span>
    </div>
    <form action="/cikis" method="GET" style="margin-left:8px">
      <button type="submit" class="cikis-btn">Çıkış</button>
    </form>
  </div>
</div>
<div class="icerik">
  <div class="sinyal-kart gri" id="sinyal-kart">
    <div class="s-icon" id="sinyal-icon">⏳</div>
    <div>
      <div class="s-baslik" id="sinyal-baslik">Yükleniyor...</div>
      <div class="s-alt" id="sinyal-alt"></div>
    </div>
  </div>
  <div class="ozet-grid">
    <div class="ozet-kart">
      <div class="baslik">💰 BTC Fiyatı</div>
      <div class="deger" id="btc-tl">—</div>
      <div class="alt" id="btc-usd">—</div>
    </div>
    <div class="ozet-kart">
      <div class="baslik">₿ Dünkü Kazanç</div>
      <div class="deger" id="btc-kazanc">—</div>
      <div class="alt" id="btc-kazanc-tl">—</div>
    </div>
    <div class="ozet-kart">
      <div class="baslik">⚡ Günlük Kar</div>
      <div class="deger" id="gunluk-kar">—</div>
      <div class="alt" id="gunluk-kar-usd">—</div>
    </div>
    <div class="ozet-kart">
      <div class="baslik">🔋 Enerji Maliyeti</div>
      <div class="deger" id="enerji-maliyet">—</div>
      <div class="alt" id="enerji-maliyet-usd">—</div>
    </div>
  </div>
  <div class="bolum-baslik">📊 Yarınki PTF Saatlik</div>
  <div class="ptf-grid" id="ptf-grid">
    <div style="grid-column:1/-1;text-align:center;color:#475569;padding:20px;font-size:13px">Yükleniyor...</div>
  </div>
  <div class="bolum-baslik">📅 Aylık Özet</div>
  <div class="aylik-kart" id="aylik-kart">
    <div style="text-align:center;color:#475569;font-size:13px">Yükleniyor...</div>
  </div>
  <div class="guncelleme" id="guncelleme"></div>
</div>
<script>
function yukle() {
  fetch('/api/ozet')
    .then(r => r.json())
    .then(d => {
      const kart = document.getElementById('sinyal-kart');
      const icon = document.getElementById('sinyal-icon');
      const baslik = document.getElementById('sinyal-baslik');
      const alt = document.getElementById('sinyal-alt');
      if (d.sinyal) {
        kart.className = 'sinyal-kart ' + (d.sinyal.karli ? 'yesil' : 'kirmizi');
        icon.textContent = d.sinyal.karli ? '✅' : '❌';
        baslik.textContent = d.sinyal.karli ? 'ÇALIŞMA VAR' : 'ÇALIŞMA YOK';
        alt.textContent = d.sinyal.mesaj || '';
      }
      if (d.btc) {
        document.getElementById('btc-tl').textContent = d.btc.tl_str + ' TL';
        document.getElementById('btc-usd').textContent = d.btc.usd_str + ' $';
      }
      if (d.f2pool) {
        document.getElementById('btc-kazanc').textContent = d.f2pool.btc + ' BTC';
        document.getElementById('btc-kazanc-tl').textContent = d.f2pool.tl_str + ' TL';
      }
      if (d.karlilik) {
        document.getElementById('gunluk-kar').textContent = d.karlilik.kar_tl;
        document.getElementById('gunluk-kar-usd').textContent = d.karlilik.kar_usd;
        document.getElementById('enerji-maliyet').textContent = d.karlilik.maliyet_tl;
        document.getElementById('enerji-maliyet-usd').textContent = d.karlilik.maliyet_usd;
      }
      if (d.ptf && d.ptf.length > 0) {
        let html = '';
        d.ptf.forEach(p => {
          const cls = p.karli ? 'karli' : 'zarарli';
          html += `<div class="ptf-saat ${cls}"><div class="ptf-no">${p.saat}</div><div class="ptf-fiyat">${p.ptf}</div></div>`;
        });
        document.getElementById('ptf-grid').innerHTML = html;
      }
      if (d.aylik) {
        const a = d.aylik;
        document.getElementById('aylik-kart').innerHTML = `
          <div class="aylik-satir"><span class="aylik-lbl">Ay / Gün</span><span class="aylik-val">${a.ay} / ${a.gun_sayisi} gün</span></div>
          <div class="aylik-satir"><span class="aylik-lbl">₿ BTC Üretim</span><span class="aylik-val">${a.btc} BTC</span></div>
          <div class="aylik-satir"><span class="aylik-lbl">💰 BTC Gelir</span><span class="aylik-val">${a.gelir_tl} TL | ${a.gelir_usd} $</span></div>
          <div class="aylik-satir"><span class="aylik-lbl">⚡ Enerji Maliyeti</span><span class="aylik-val">${a.maliyet_tl} TL</span></div>
          <div class="aylik-satir"><span class="aylik-lbl" style="color:#22c55e">📈 Net Kar</span><span class="aylik-val" style="color:#22c55e">${a.kar_tl} TL | ${a.kar_usd} $</span></div>
          <div class="aylik-satir"><span class="aylik-lbl">🔋 Toplam Tüketim</span><span class="aylik-val">${a.kwh} kWh</span></div>`;
      }
      const now = new Date();
      document.getElementById('guncelleme').textContent = 'Güncellendi: ' + now.toLocaleTimeString('tr-TR');
    });
}
yukle();
setInterval(yukle, 60000);
if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js'); }
</script>
</body>
</html>"""

def github_oku(dosya):
    try:
        url = f"{GITHUB_RAW}/{dosya}"
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except:
        return None

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

    # Sinyal ve BTC - GitHub'dan
    sinyal = github_oku("sinyal.json")
    if sinyal:
        su_an = (datetime.datetime.utcnow() + datetime.timedelta(hours=3)).strftime("%H")
        karli = su_an in sinyal.get("karli_saatler", [])
        sonuc["sinyal"] = {
            "karli": karli,
            "mesaj": f"Saat {su_an}:00 — {'karlı' if karli else 'zararlı'} | {sinyal.get('tarih','')}"
        }
        # BTC fiyatı sinyal.json'dan
        btc_try = sinyal.get("btc_try", 0)
        btc_usd = sinyal.get("btc_usd", 0)
        if btc_try > 0:
            sonuc["btc"] = {
                "tl_str": f"{btc_try:,.0f}",
                "usd_str": f"{btc_usd:,.0f}"
            }
        else:
            sonuc["btc"] = {"tl_str": "—", "usd_str": "—"}

        # Günlük BTC kazanç
        gunluk_btc = sinyal.get("gunluk_btc", 0)
        gunluk_kar = sinyal.get("gunluk_kar_tl", 0)
        gunluk_mal = sinyal.get("gunluk_maliyet_tl", 0)
        kur = btc_try / btc_usd if btc_usd > 0 and btc_try > 0 else 1

        sonuc["f2pool"] = {
            "btc": f"{gunluk_btc:.5f}",
            "tl_str": f"{gunluk_btc * btc_try:,.0f}"
        }
        sonuc["karlilik"] = {
            "kar_tl": f"{gunluk_kar:+,.0f} TL",
            "kar_usd": f"{gunluk_kar/kur:+,.0f} $",
            "maliyet_tl": f"{gunluk_mal:,.0f} TL",
            "maliyet_usd": f"{gunluk_mal/kur:,.0f} $"
        }

        # PTF saatlik
        karli_saatler = sinyal.get("karli_saatler", [])
        ptf_list = []
        for i in range(24):
            saat_str = f"{i:02d}"
            ptf_list.append({
                "saat": saat_str,
                "ptf": "✅" if saat_str in karli_saatler else "❌",
                "karli": saat_str in karli_saatler
            })
        sonuc["ptf"] = ptf_list
    else:
        sonuc["sinyal"] = {"karli": False, "mesaj": "Sinyal alınamadı"}
        sonuc["btc"] = {"tl_str": "—", "usd_str": "—"}

    # Aylık veri - GitHub'dan
    ay_key = datetime.date.today().strftime("%Y-%m")
    ay = github_oku(f"aylik_{ay_key}.json")
    if ay:
        btc_try_fiyat = sinyal.get("btc_try", 0) if sinyal else 0
        btc_usd_fiyat = sinyal.get("btc_usd", 0) if sinyal else 0
        kur = btc_try_fiyat / btc_usd_fiyat if btc_usd_fiyat > 0 else 1
        sonuc["aylik"] = {
            "ay": ay_key,
            "gun_sayisi": ay.get("gun_sayisi", 0),
            "btc": f"{ay.get('toplam_btc', 0):.5f}",
            "gelir_tl": f"{ay.get('toplam_btc_tl', 0):,.0f}",
            "gelir_usd": f"{ay.get('toplam_btc', 0) * btc_usd_fiyat:,.0f}",
            "maliyet_tl": f"{ay.get('toplam_maliyet_tl', 0):,.0f}",
            "kar_tl": f"{ay.get('toplam_kar_tl', 0):+,.0f}",
            "kar_usd": f"{ay.get('toplam_kar_tl', 0) / kur:+,.0f}",
            "kwh": f"{ay.get('toplam_kwh', 0):,.0f}"
        }

    return jsonify(sonuc)

if __name__ == "__main__":
    print("Otocoin Ofis Paneli baslatiliyor: http://0.0.0.0:8081")
    app.run(host="0.0.0.0", port=8081, debug=False)
