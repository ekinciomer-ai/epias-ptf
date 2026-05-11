import datetime, os, json
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
GITHUB_TOKEN    = os.environ.get("GH_TOKEN", "")
REPO            = "ekinciomer-ai/epias-ptf"

bugun = datetime.date.today().strftime("%Y-%m-%d")
yarin = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

# Bugün daha önce mesaj gönderildi mi kontrol et
import urllib.request, urllib.error
try:
    url = f"https://api.github.com/repos/{REPO}/contents/son_gonderim.json"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    })
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
        icerik = json.loads(__import__("base64").b64decode(data["content"]).decode())
        if icerik.get("tarih") == bugun:
            print(f"Bugün ({bugun}) zaten mesaj gönderildi, atlanıyor.")
            exit(0)
        sha = data["sha"]
except urllib.error.HTTPError as e:
    if e.code == 404:
        sha = None
    else:
        raise

# Veri çek
try:
    sonuc = eptr.call("mcp", start_date=yarin, end_date=yarin, postprocess=False)
    items = sonuc.get("items", [])
except Exception as e:
    print(f"Veri henüz yayınlanmadı: {e}")
    exit(0)

if not items:
    print("Veri henüz yayınlanmadı, sonra tekrar denenecek.")
    exit(0)

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

print(mesaj)
Client(TWILIO_SID, TWILIO_TOKEN).messages.create(
    body=mesaj, from_=TWILIO_NUMARA, to=KENDI_NUMARA)
print("WhatsApp gonderildi!")
Client(TWILIO_SID, TWILIO_TOKEN).messages.create(
    body=mesaj, from_=TWILIO_NUMARA, to=IKINCI_NUMARA)
print("Ikinci WhatsApp gonderildi!")

# Gönderim tarihini kaydet
import base64
yeni_icerik = base64.b64encode(json.dumps({"tarih": bugun}).encode()).decode()
guncelleme = {"message": f"Gonderim: {bugun}", "content": yeni_icerik}
if sha:
    guncelleme["sha"] = sha

req2 = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/contents/son_gonderim.json",
    data=json.dumps(guncelleme).encode(),
    headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    },
    method="PUT"
)
urllib.request.urlopen(req2)
print(f"Gonderim tarihi kaydedildi: {bugun}")
