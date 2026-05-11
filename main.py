import datetime, os, json, urllib.request, urllib.error, base64
from eptr2 import EPTR2
from twilio.rest import Client

EPIAS_KULLANICI = os.environ.get("EPIAS_KULLANICI", "")
EPIAS_SIFRE     = os.environ.get("EPIAS_SIFRE", "")
ESIK_FIYAT      = 1200
TWILIO_SID      = os.environ.get("TWILIO_SID", "")
TWILIO_TOKEN    = os.environ.get("TWILIO_TOKEN", "")
TWILIO_NUMARA   = "whatsapp:+14155238886"
KENDI_NUMARA    = "whatsapp:+905438703340"
IKINCI_NUMARA   = "whatsapp:+905443977380"
GH_TOKEN        = os.environ.get("GH_TOKEN", "")
REPO            = "ekinciomer-ai/epias-ptf"

bugun = datetime.date.today().strftime("%Y-%m-%d")
yarin = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

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

# Bugün zaten mesaj gönderildi mi?
gonderim, sha = dosya_oku("son_gonderim.json")
if gonderim and gonderim.get("tarih") == bugun:
    print(f"Bugün zaten mesaj gönderildi, atlanıyor.")
    exit(0)

# Veriyi çekmeyi dene
try:
    eptr = EPTR2(username=EPIAS_KULLANICI, password=EPIAS_SIFRE)
    sonuc = eptr.call("mcp", start_date=yarin, end_date=yarin, postprocess=False)
    items = sonuc.get("items", [])
except Exception as e:
    print(f"Veri henüz yok: {e}")
    whatsapp_gonder(f"⏳ EPİAŞ PTF\nHenüz veri yayınlanmadı.\nSaat: {datetime.datetime.now().strftime('%H:%M')}\nYarım saat sonra tekrar denenecek.")
    exit(0)

if not items:
    print("Veri boş.")
    whatsapp_gonder(f"⏳ EPİAŞ PTF\nHenüz veri yayınlanmadı.\nSaat: {datetime.datetime.now().strftime('%H:%M')}\nYarım saat sonra tekrar denenecek.")
    exit(0)

# Veri geldi, mesajı hazırla
fiyatlar  = [item["price"] for item in items]
ortalama  = sum(fiyatlar) / len(fiyatlar)
minimum   = min(fiyatlar)
maksimum  = max(fiyatlar)
esik_alti = sum(1 for f in fiyatlar if f < ESIK_FIYAT)

sinyal = "✅ ÇALIŞMA VAR" if ortalama < ESIK_FIYAT else "🔴 ÇALIŞMA YOK"
durum  = f"Ort. {ortalama:.0f} TL - esik ({ESIK_FIYAT} TL) {'ALTINDA' if ortalama < ESIK_FIYAT else 'UZERINDE'}"

satirlar = []
for item in items:
    emoji = "🟢" if item["price"] < ESIK_FIYAT else "🔴"
    satirlar.append(f"{emoji} {item['hour']}  {item['price']:>8.2f} TL")

mesaj = f"""EPİAŞ PTF SİNYALİ
Tarih: {yarin}
--------------------------
{sinyal}
{durum}

Ozet:
- Ortalama : {ortalama:.2f} TL/MWh
- Minimum  : {minimum:.2f} TL/MWh
- Maksimum : {maksimum:.2f} TL/MWh
- Esik alti: {esik_alti}/24 saat
--------------------------
Saatlik PTF:
{chr(10).join(satirlar)}"""

whatsapp_gonder(mesaj)

# Gönderim tarihini kaydet
dosya_yaz("son_gonderim.json", {"tarih": bugun}, sha)
print(f"Tamamlandi: {bugun}")
