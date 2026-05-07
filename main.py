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

print(type(sonuc))
print(sonuc)
