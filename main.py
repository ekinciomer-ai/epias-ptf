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

print(f"EPIAS_KULLANICI: {'OK' if EPIAS_KULLANICI else 'BOŞ'}")
print(f"TWILIO_SID: {'OK' if TWILIO_SID else 'BOŞ'}")

yarin = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

eptr = EPTR2(username=EPIAS_KULLANICI, password=EPIAS_SIFRE)
df   = eptr.call("mcp", start_date=yarin, end_date=yarin)

if df is None or len(df) == 0:
    print("Veri henüz yayınlanmadı, sonra tekrar denenecek.")
    exit(0)

fiyatlar  = df["price"].tolist()
ortalama  = sum(fiyatlar) / len(fiyatlar)
minimum   = min(fiyatlar)
maksimum  = max(fiyatlar)
esik_alti = sum(1 for f in fiyatlar if f < ESIK_FIYAT)

sinyal = "✅ ÇALIŞMA VAR" if ortalama < ESIK_FIYAT else "🔴 ÇALIŞMA YOK"
durum  = f"Ort. {ortalama:.0f} TL — eşik ({ESIK_FIYAT} TL) {'ALTINDA' if ortalama < ESIK_FIYAT else 'ÜZERİNDE'}"

satirlar = []
for _, row in df.iterrows():
    emoji = "🟢" if row["price"] < ESIK_FIYAT else "🔴"
    satirlar.append(f"{emoji} {row['hour']}  {row['price']:>8.2f} TL")

mesaj = f"""⚡ EPİAŞ PTF SİNYALİ
📅 {yarin}
──────────────────────────
{sinyal}
{durum}

📊 Özet:
- Ortalama : {ortalama:.2f} TL/MWh
- Minimum  : {minimum:.2f} TL/MWh
- Maksimum : {maksimum:.2f} TL/MWh
- Eşik altı: {esik_alti}/24 saat
──────────────────────────
🕐 Saatlik PTF:
{chr(10).join(satirlar)}"""

print(mesaj)
Client(TWILIO_SID, TWILIO_TOKEN).messages.create(
    body=mesaj, from_=TWILIO_NUMARA, to=KENDI_NUMARA)
print("WhatsApp gönderildi ✅")
