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
TOPLAM_KW     = CIHAZ_SAYISI * CIHAZ_GUC_W / 1000  # 174 kW
GUNLUK_BTC    = 0.0037

bugun   = datetime.date.today().strftime("%Y-%m-%d")
yarin   = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
ay_key  = datetime.date.today().strftime("%Y-%m")
saat_tr = (datetime.datetime.utcnow() + datetime.timedelta(hours=3)).strftime("%H:%M")
GUNLER  = ["Pazartesi","Sali","Carsamba","Persembe","Cuma","Cumartesi","Pazar"]

def whatsapp_gonder(mesaj):
    client = Client(TWILIO_SID, TWILIO_TOKEN)
    for numara in [KENDI_NUMARA, IKINCI_NUMARA]:
        client.messages.create(body=mesaj, from_=TWILIO_NUMARA, to=numara)
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
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,try"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
            return float(data["bitcoin"]["try"]), float(data["bitcoin"]["usd"])
    except:
        pass
    try:
        url = "https://api.coinbase.com/v2/prices/BTC-TRY/spot"
        with urllib.request.urlopen(url, timeout=10) as r:
            btc_try = float(json.loads(r.read())["data"]["amount"])
        url2 = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
        with urllib.request.urlopen(url2, timeout=10) as r:
            btc_usd = float(json.loads(r.read())["data"]["amount"])
        return btc_try, btc_usd
    except:
        pass
    return 0, 0

# Bugün mesaj gönderildi mi?
gonderim, sha = dosya_oku("son_gonderim.json")
if gonderim and gonderim.get("tarih") == bugun:
    print("Bugun zaten gonderildi.")
    exit(0)

# Veriyi çek — önce yarın, olmazsa bugün
items = []
hedef_str = ""
for tarih in [yarin, bugun]:
    try:
        eptr  = EPTR2(username=EPIAS_KULLANICI, password=EPIAS_SIFRE)
        sonuc = eptr.call("mcp", start_date=tarih, end_date=tarih, postprocess=False)
        items = sonuc.get("items", [])
        if items:
            dt = datetime.date.fromisoformat(tarih)
            hedef_str = f"{dt.strftime('%d.%m.%Y')} {GUNLER[dt.weekday()]}"
            print(f"Veri bulundu: {tarih}")
            break
    except Exception as e:
        print(f"{tarih} verisi yok: {e}")

if not items:
    whatsapp_gonder(f"EPiAS PTF\nHenuz veri yayinlanmadi.\nSaat: {saat_tr}\nYarim saat sonra tekrar denenecek.")
    exit(0)

# BTC fiyatı
try:
    btc_try, btc_usd = btc_cek()
    print(f"BTC: {btc_try:.0f} TL | {btc_usd:.0f} USD")
except:
    btc_try, btc_usd = 0, 0

kur = btc_try / btc_usd if btc_usd > 0 and btc_try > 0 else 1

# Önce karlı saat sayısını bul (SAATLIK_BTC için)
karli_saat_on = 0
for item in items:
    ptf_tl    = item["price"] / 1000
    yekdem_tl = YEKDEM / 1000
    maliyet_tl = (ptf_tl + yekdem_tl) * 1.05 * TOPLAM_KW
    btc_gelir_tl = (GUNLUK_BTC / 24) * btc_try if btc_try > 0 else 0
    if btc_gelir_tl > maliyet_tl:
        karli_saat_on += 1

# Saatlik BTC karlı saate göre böl
SAATLIK_BTC = GUNLUK_BTC / karli_saat_on if karli_saat_on > 0 else GUNLUK_BTC / 24

# Asıl saatlik hesap
satirlar = []
toplam_kar = toplam_maliyet = toplam_btc_gelir = 0
karli_saat = 0

for item in items:
    saat      = item["hour"]
    ptf_kurus = item["price"]
    ptf_tl    = ptf_kurus / 1000
    yekdem_tl = YEKDEM / 1000
    maliyet_tl   = (ptf_tl + yekdem_tl) * 1.05 * TOPLAM_KW
    btc_gelir_tl = SAATLIK_BTC * btc_try if btc_try > 0 else 0
    kar = btc_gelir_tl - maliyet_tl
    toplam_kar     += kar
    toplam_maliyet += maliyet_tl
    toplam_btc_gelir += btc_gelir_tl
    if kar > 0:
        karli_saat += 1
        satirlar.append(f"✅ {saat[:2]} | {ptf_kurus:.0f} | {maliyet_tl:.0f} | {btc_gelir_tl:.0f} | +{kar:.0f}")
    else:
        satirlar.append(f"❌ {saat[:2]} | {ptf_kurus:.0f} | {maliyet_tl:.0f} | {btc_gelir_tl:.0f} | {kar:.0f}")

gunluk_kwh     = karli_saat * TOPLAM_KW
gunluk_btc_tl  = GUNLUK_BTC * btc_try if btc_try > 0 else 0
gunluk_btc_usd = GUNLUK_BTC * btc_usd if btc_usd > 0 else 0
gunluk_kar_usd = toplam_kar / kur
maliyet_usd    = toplam_maliyet / kur

# Sinyal mesajı (mesaj3)
satirlar_sinyal = []
for row_start in range(0, 24, 6):
    satir = ""
    for i in range(row_start, row_start + 6):
        item = items[i] if i < len(items) else None
        if item:
            ptf_tl    = item["price"] / 1000
            yekdem_tl = YEKDEM / 1000
            maliyet   = (ptf_tl + yekdem_tl) * 1.05 * TOPLAM_KW
            btc_gelir = SAATLIK_BTC * btc_try if btc_try > 0 else 0
            isaret = "✅" if btc_gelir > maliyet else "❌"
        else:
            isaret = "✅"
        satir += f"{i:02d}{isaret}"
    satirlar_sinyal.append(satir)

mesaj3 = f"""⚡ {hedef_str}
──────────────────────
{chr(10).join(satirlar_sinyal)}"""

# Karlılık tablosu (mesaj1)
mesaj1 = f"""EPiAS KARLILIK {hedef_str}
BTC:{btc_try:,.0f}TL|{btc_usd:,.0f}$
YEKDEM:{YEKDEM}kr/MWh
Saat|PTF|Maliyet|BTC|Kar
{chr(10).join(satirlar)}
Karli:{karli_saat}/24 Kar:{toplam_kar:+,.0f}TL|{gunluk_kar_usd:+,.0f}$
Guc:{TOPLAM_KW:.0f}kW/s Tuk:{gunluk_kwh:.0f}kWh"""

# Aylık birikim
ay_data, ay_sha = dosya_oku(f"aylik_{ay_key}.json")
if not ay_data:
    ay_data = {"ay": ay_key, "gun_sayisi": 0, "toplam_btc": 0,
               "toplam_btc_tl": 0, "toplam_maliyet_tl": 0,
               "toplam_kar_tl": 0, "toplam_kwh": 0}
ay_data["gun_sayisi"]        += 1
ay_data["toplam_btc"]        += GUNLUK_BTC
ay_data["toplam_btc_tl"]     += gunluk_btc_tl
ay_data["toplam_maliyet_tl"] += toplam_maliyet
ay_data["toplam_kar_tl"]     += toplam_kar
ay_data["toplam_kwh"]        += gunluk_kwh

ay_kar_usd     = ay_data["toplam_kar_tl"] / kur
ay_maliyet_usd = ay_data["toplam_maliyet_tl"] / kur
ay_btc_usd     = ay_data["toplam_btc"] * btc_usd if btc_usd > 0 else 0

# Özet mesajı (mesaj2)
mesaj2 = f"""GUNLUK OZET {hedef_str}
BTC:{GUNLUK_BTC:.5f}BTC
Gelir:{gunluk_btc_tl:,.0f}TL|{gunluk_btc_usd:,.0f}$
Enerji:{toplam_maliyet:,.0f}TL|{maliyet_usd:,.0f}$
Kar:{toplam_kar:+,.0f}TL|{gunluk_kar_usd:+,.0f}$
--- {ay_key} TOPLAM ({ay_data['gun_sayisi']} gun) ---
BTC:{ay_data['toplam_btc']:.5f}BTC
Gelir:{ay_data['toplam_btc_tl']:,.0f}TL|{ay_btc_usd:,.0f}$
Enerji:{ay_data['toplam_maliyet_tl']:,.0f}TL|{ay_maliyet_usd:,.0f}$
Kar:{ay_data['toplam_kar_tl']:+,.0f}TL|{ay_kar_usd:+,.0f}$
Tuk:{ay_data['toplam_kwh']:,.0f}kWh"""

print(mesaj3)
print(mesaj1)
print(mesaj2)

client = Client(TWILIO_SID, TWILIO_TOKEN)
for numara in [KENDI_NUMARA, IKINCI_NUMARA]:
    client.messages.create(body=mesaj3, from_=TWILIO_NUMARA, to=numara)
    client.messages.create(body=mesaj1, from_=TWILIO_NUMARA, to=numara)
    client.messages.create(body=mesaj2, from_=TWILIO_NUMARA, to=numara)
print("WhatsApp gonderildi!")

dosya_yaz("son_gonderim.json", {"tarih": bugun}, sha)
dosya_yaz(f"aylik_{ay_key}.json", ay_data, ay_sha)
print(f"Tamamlandi: {bugun}")
