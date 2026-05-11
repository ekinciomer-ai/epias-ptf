import datetime, os, json, urllib.request, urllib.error, base64
from eptr2 import EPTR2
from twilio.rest import Client

EPIAS_KULLANICI = os.environ.get("EPIAS_KULLANICI", "")
EPIAS_SIFRE     = os.environ.get("EPIAS_SIFRE", "")
TWILIO_SID      = os.environ.get("TWILIO_SID", "")
TWILIO_TOKEN    = os.environ.get("TWILIO_TOKEN", "")
TWILIO_NUMARA   = "whatsapp:+14155238886"
KENDI_NUMARA    = "whatsapp:+905438703340"
IKINCI_NUMARA   = "whatsapp:+905443977380"
GH_TOKEN        = os.environ.get("GH_TOKEN", "")
REPO            = "ekinciomer-ai/epias-ptf"

CIHAZ_SAYISI  = 29
CIHAZ_GUC_W   = 6000
YEKDEM        = 602.51
TOPLAM_GUC_MW = (CIHAZ_SAYISI * CIHAZ_GUC_W) / 1_000_000
GUNLUK_BTC    = 0.0037
SAATLIK_BTC   = GUNLUK_BTC / 24

bugun   = datetime.date.today().strftime("%Y-%m-%d")
yarin   = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
ay_key  = datetime.date.today().strftime("%Y-%m")
saat_tr = (datetime.datetime.utcnow() + datetime.timedelta(hours=3)).strftime("%H:%M")

GUNLER  = ["Pazartesi","Sali","Carsamba","Persembe","Cuma","Cumartesi","Pazar"]
yarin_dt  = datetime.date.today() + datetime.timedelta(days=1)
yarin_str = f"{yarin_dt.strftime('%d.%m.%Y')} {GUNLER[yarin_dt.weekday()]}"

def whatsapp_gonder(mesaj):
    client = Client(TWILIO_SID, TWILIO_TOKEN)
    client.messages.create(body=mesaj, from_=TWILIO_NUMARA, to=KENDI_NUMARA)
    client.messages.create(body=mesaj, from_=TWILIO_NUMARA, to=IKINCI_NUMARA)
    print("WhatsApp gonderildi!")

def dosya_oku(dosya):
    try:
        url = f"https://api.github.com/repos/{REPO}/contents/{dosya}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        })
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            icerik = json.loads(base64.b64decode(data["content"]).decode())
            return icerik, data["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise

def dosya_yaz(dosya, icerik, sha=None):
    yeni = base64.b64encode(json.dumps(icerik).encode()).decode()
    body = {"message": f"Guncelleme: {bugun}", "content": yeni}
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/{dosya}",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"token {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        },
        method="PUT"
    )
    urllib.request.urlopen(req)

def btc_cek():
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCTRY"
    with urllib.request.urlopen(url, timeout=10) as r:
        btc_try = float(json.loads(r.read())["price"])
    url2 = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    with urllib.request.urlopen(url2, timeout=10) as r:
        btc_usd = float(json.loads(r.read())["price"])
    return btc_try, btc_usd

# Bugün mesaj gönderildi mi?
gonderim, sha = dosya_oku("son_gonderim.json")
if gonderim and gonderim.get("tarih") == bugun:
    print("Bugun zaten gonderildi.")
    exit(0)

# Veriyi çek — önce yarın, olmazsa bugün dene
items = []
hedef_tarih = yarin
hedef_str   = yarin_str

for tarih in [yarin, bugun]:
    try:
        eptr  = EPTR2(username=EPIAS_KULLANICI, password=EPIAS_SIFRE)
        sonuc = eptr.call("mcp", start_date=tarih, end_date=tarih, postprocess=False)
        items = sonuc.get("items", [])
        if items:
            hedef_tarih = tarih
            dt = datetime.date.fromisoformat(tarih)
            hedef_str = f"{dt.strftime('%d.%m.%Y')} {GUNLER[dt.weekday()]}"
            print(f"Veri bulundu: {tarih}")
            break
    except Exception as e:
        print(f"{tarih} verisi yok: {e}")

if not items:
    print("Veri henuz yayinlanmadi.")
    whatsapp_gonder(f"EPiAS PTF\nHenuz veri yayinlanmadi.\nSaat: {saat_tr}\nYarim saat sonra tekrar denenecek.")
    exit(0)

# BTC fiyatı çek
try:
    btc_try, btc_usd = btc_cek()
except Exception as e:
    print(f"BTC verisi alinamadi: {e}")
    btc_try, btc_usd = 0, 0

# Saatlik karlılık hesabı
satirlar   = []
toplam_kar = 0
toplam_maliyet = 0
toplam_btc_gelir = 0
karli_saat = 0

for item in items:
    saat      = item["hour"]
    ptf_kurus = item["price"]
    ptf_tl    = ptf_kurus / 1000

    maliyet_tl   = (ptf_tl + YEKDEM) * 1.05 * TOPLAM_GUC_MW
    btc_gelir_tl = SAATLIK_BTC * btc_try if btc_try > 0 else 0
    kar          = btc_gelir_tl - maliyet_tl

    toplam_kar       += kar
    toplam_maliyet   += maliyet_tl
    toplam_btc_gelir += btc_gelir_tl

    if kar > 0:
        karli_saat += 1
        satirlar.append(f"✅ {saat} | {ptf_kurus:.0f} | {maliyet_tl:.0f}TL | {btc_gelir_tl:.0f}TL | +{kar:.0f}TL")
    else:
        satirlar.append(f"❌ {saat} | {ptf_kurus:.0f} | {maliyet_tl:.0f}TL | {btc_gelir_tl:.0f}TL | {kar:.0f}TL")

gunluk_btc_tl  = GUNLUK_BTC * btc_try if btc_try > 0 else 0
gunluk_btc_usd = GUNLUK_BTC * btc_usd if btc_usd > 0 else 0
gunluk_kar_usd = toplam_kar / (btc_try / btc_usd) if btc_try > 0 and btc_usd > 0 else 0
maliyet_usd    = toplam_maliyet / (btc_try / btc_usd) if btc_try > 0 and btc_usd > 0 else 0
gunluk_kwh     = TOPLAM_GUC_MW * 1000 * 24

# Aylık birikim güncelle
ay_data, ay_sha = dosya_oku(f"aylik_{ay_key}.json")
if not ay_data:
    ay_data = {"ay": ay_key, "gun_sayisi": 0, "toplam_btc": 0, "toplam_btc_tl": 0,
               "toplam_maliyet_tl": 0, "toplam_kar_tl": 0, "toplam_kwh": 0}

ay_data["gun_sayisi"]      += 1
ay_data["toplam_btc"]      += GUNLUK_BTC
ay_data["toplam_btc_tl"]   += gunluk_btc_tl
ay_data["toplam_maliyet_tl"] += toplam_maliyet
ay_data["toplam_kar_tl"]   += toplam_kar
ay_data["toplam_kwh"]      += gunluk_kwh

ay_btc_usd = ay_data["toplam_btc"] * btc_usd if btc_usd > 0 else 0
ay_kar_usd = ay_data["toplam_kar_tl"] / (btc_try / btc_usd) if btc_try > 0 and btc_usd > 0 else 0
ay_maliyet_usd = ay_data["toplam_maliyet_tl"] / (btc_try / btc_usd) if btc_try > 0 and btc_usd > 0 else 0

mesaj = f"""EPiAS KARLILIK ANALiZi
Tarih: {hedef_str}
BTC: {btc_try:,.0f} TL | {btc_usd:,.0f} $
YEKDEM: {YEKDEM} TL/MWh
------------------------------
Saat | PTF(kr) | Maliyet | BTC | Kar
------------------------------
{chr(10).join(satirlar)}
------------------------------
Karli     : {karli_saat}/24 saat
Gunluk kar: {toplam_kar:+,.0f} TL | {gunluk_kar_usd:+,.0f} $
Toplam guc: {CIHAZ_SAYISI * CIHAZ_GUC_W / 1000:.0f} kW/saat
Gunluk tuk: {gunluk_kwh:,.0f} kWh/gun
------------------------------
GUNLUK OZET
------------------------------
BTC uretim   : {GUNLUK_BTC:.5f} BTC
BTC gelir    : {gunluk_btc_tl:,.0f} TL | {gunluk_btc_usd:,.0f} $
Enerji maliyet: {toplam_maliyet:,.0f} TL | {maliyet_usd:,.0f} $
Gunluk kar   : {toplam_kar:+,.0f} TL | {gunluk_kar_usd:+,.0f} $
------------------------------
{ay_key} TOPLAM ({ay_data['gun_sayisi']} gun)
------------------------------
BTC uretim   : {ay_data['toplam_btc']:.5f} BTC
BTC gelir    : {ay_data['toplam_btc_tl']:,.0f} TL | {ay_btc_usd:,.0f} $
Enerji maliyet: {ay_data['toplam_maliyet_tl']:,.0f} TL | {ay_maliyet_usd:,.0f} $
Aylik kar    : {ay_data['toplam_kar_tl']:+,.0f} TL | {ay_kar_usd:+,.0f} $
Toplam tuk   : {ay_data['toplam_kwh']:,.0f} kWh"""

print(mesaj)
whatsapp_gonder(mesaj)

# Kaydet
dosya_yaz("son_gonderim.json", {"tarih": bugun}, sha)
dosya_yaz(f"aylik_{ay_key}.json", ay_data, ay_sha)
print(f"Tamamlandi: {bugun}")
