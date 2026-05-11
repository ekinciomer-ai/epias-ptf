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

# Sabit değerler
CIHAZ_SAYISI    = 29
CIHAZ_HASHRATE  = 310        # TH/s
CIHAZ_GUC       = 6000       # Watt
HAVUZ_KOMISYON  = 0.025      # %2.5
YEKDEM          = 602.51     # TL/MWh (Mayıs 2026)
TOPLAM_GUC_MW   = (CIHAZ_SAYISI * CIHAZ_GUC) / 1_000_000  # MW = 0.174

bugun = datetime.date.today().strftime("%Y-%m-%d")
yarin = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
saat_tr = (datetime.datetime.utcnow() + datetime.timedelta(hours=3)).strftime("%H:%M")

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

def btc_verisi_cek():
    # BTC/TL fiyatı
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCTRY"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        btc_try = float(data["price"])

    # Network hashrate ve blok ödülü
    url2 = "https://blockchain.info/q/hashrate"
    req2 = urllib.request.Request(url2)
    with urllib.request.urlopen(req2, timeout=10) as resp2:
        network_hash_ghs = float(resp2.read())  # GH/s
        network_hash_ths = network_hash_ghs / 1000  # TH/s

    blok_odulu = 3.125  # BTC (halving sonrası)

    return btc_try, network_hash_ths, blok_odulu

def saatlik_btc_geliri(btc_try, network_hash_ths, blok_odulu):
    # Toplam hashrate TH/s
    toplam_hash = CIHAZ_SAYISI * CIHAZ_HASHRATE  # 8990 TH/s
    # Saatte kaç blok: 6 blok/saat
    blok_per_saat = 6
    # Saatlik BTC kazanç
    btc_kazanc = (toplam_hash / network_hash_ths) * blok_odulu * blok_per_saat
    # Havuz komisyonu düş
    net_btc = btc_kazanc * (1 - HAVUZ_KOMISYON)
    # TL cinsinden
    net_tl = net_btc * btc_try
    return net_tl, net_btc

# Bugün mesaj gönderildi mi?
gonderim, sha = dosya_oku("son_gonderim.json")
if gonderim and gonderim.get("tarih") == bugun:
    print("Bugün zaten mesaj gönderildi, atlanıyor.")
    exit(0)

# EPİAŞ verisi çek
try:
    eptr = EPTR2(username=EPIAS_KULLANICI, password=EPIAS_SIFRE)
    sonuc = eptr.call("mcp", start_date=yarin, end_date=yarin, postprocess=False)
    items = sonuc.get("items", [])
except Exception as e:
    print(f"Veri henüz yok: {e}")
    whatsapp_gonder(f"EPiAS PTF\nHenuz veri yayinlanmadi.\nSaat: {saat_tr}\nYarim saat sonra tekrar denenecek.")
    exit(0)

if not items:
    print("Veri bos.")
    whatsapp_gonder(f"EPiAS PTF\nHenuz veri yayinlanmadi.\nSaat: {saat_tr}\nYarim saat sonra tekrar denenecek.")
    exit(0)

# BTC verisi çek
try:
    btc_try, network_hash_ths, blok_odulu = btc_verisi_cek()
    btc_tl_str = f"{btc_try:,.0f}"
    network_eh = network_hash_ths / 1_000_000
except Exception as e:
    print(f"BTC verisi alinamadi: {e}")
    btc_try = 0
    network_hash_ths = 900_000_000  # 900 EH/s varsayılan
    blok_odulu = 3.125
    btc_tl_str = "?"
    network_eh = 900

# Saatlik karlılık hesabı
satirlar = []
toplam_kar = 0
karli_saat = 0

for item in items:
    saat       = item["hour"]
    ptf_raw    = item["price"]  # kuruş/MWh
    ptf_tl     = ptf_raw / 1000  # TL/MWh

    # Elektrik maliyeti (TL) — saatlik, 29 cihaz için
    maliyet_mwh = (ptf_tl + YEKDEM) * 1.05
    maliyet_tl  = maliyet_mwh * TOPLAM_GUC_MW

    # BTC kazanç (TL) — saatlik
    if btc_try > 0:
        btc_gelir_tl, _ = saatlik_btc_geliri(btc_try, network_hash_ths, blok_odulu)
    else:
        btc_gelir_tl = 0

    kar = btc_gelir_tl - maliyet_tl
    toplam_kar += kar
    if kar > 0:
        karli_saat += 1
        emoji = "✅"
    else:
        emoji = "❌"

    satirlar.append(
        f"{emoji} {saat} | {ptf_tl:.3f} TL/MWh | {maliyet_tl:.0f}TL | {btc_gelir_tl:.0f}TL | {kar:+.0f}TL"
    )

mesaj = f"""EPiAS KARLILIK ANALiZi
Tarih: {yarin}
BTC: {btc_tl_str} TL
Network: {network_eh:.0f} EH/s
YEKDEM: {YEKDEM} TL/MWh
---------------------------------
Saat|PTF TL/MWh|Maliyet|BTC|Kar
---------------------------------
{chr(10).join(satirlar)}
---------------------------------
Karli saat: {karli_saat}/24
Gunluk tahmini kar: {toplam_kar:+,.0f} TL"""

print(mesaj)
whatsapp_gonder(mesaj)
dosya_yaz("son_gonderim.json", {"tarih": bugun}, sha)
print(f"Tamamlandi: {bugun}")
