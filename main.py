import datetime, os
from eptr2 import EPTR2
from twilio.rest import Client

EPIAS_KULLANICI = os.environ.get("EPIAS_KULLANICI", "")
EPIAS_SIFRE     = os.environ.get("EPIAS_SIFRE", "")
ESIK_FIYAT      = 1200
TWILIO_SID      = os.environ.get("TWILIO_SID", "")
TWILIO_TOKEN    = os.environ.get("TWILIO_TOKEN", "")
TWILIO_NUMARA   = "whatsapp:+14155238886"
KENDI_NUMARA    = "whatsapp:+905438703340"

yarin = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

eptr = EPTR2(username=EPIAS_KULLANICI, password=EPIAS_SIFRE)
sonuc = eptr.call("mcp", start_date=yarin, end_date=yarin, postprocess=False)

items = sonuc.get("items", [])

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
