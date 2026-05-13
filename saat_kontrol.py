"""
Saat Kontrol - Her saat başı 10 dakika önce çalışır.
- Bir sonraki saatin kârlı/zararlı durumunu kontrol eder
- Mevcut cihaz durumuyla karşılaştırır
- Eylem gerekiyorsa WhatsApp + GitHub bekleyen-onay listesi

Cron: */10 * * * *  (her 10 dk - basitlik icin)
Onerilen: 50 * * * * (her saat 50. dakika - bir sonraki saatten 10 dk once)
"""
import datetime, os, json, urllib.request, urllib.error, base64
from twilio.rest import Client

# === ENV ===
TWILIO_SID       = os.environ.get("TWILIO_SID", "")
TWILIO_TOKEN     = os.environ.get("TWILIO_TOKEN", "")
TWILIO_NUMARA    = "whatsapp:+14155238886"
KENDI_NUMARA     = "whatsapp:+905438703340"
IKINCI_NUMARA    = "whatsapp:+905443977380"
GH_TOKEN         = os.environ.get("GH_TOKEN", "")
REPO             = "ekinciomer-ai/epias-ptf"
OTOCOIN_URL      = os.environ.get("OTOCOIN_URL", "https://epias-ptf-production.up.railway.app")

now_tr = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
saat_simdi = now_tr.hour
saat_sonraki = (saat_simdi + 1) % 24
bugun_str = now_tr.date().strftime("%Y-%m-%d")
saat_str = now_tr.strftime("%H:%M")


def whatsapp_gonder(mesaj):
    if not TWILIO_SID:
        print("TWILIO env yok, mesaj atilamadi:")
        print(mesaj)
        return
    client = Client(TWILIO_SID, TWILIO_TOKEN)
    for numara in [KENDI_NUMARA, IKINCI_NUMARA]:
        try:
            client.messages.create(body=mesaj, from_=TWILIO_NUMARA, to=numara)
        except Exception as e:
            print(f"WhatsApp hata ({numara}): {e}")
    print("WhatsApp gonderildi")


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
    yeni = base64.b64encode(json.dumps(icerik, ensure_ascii=False, indent=2).encode()).decode()
    body = {"message": f"saat_kontrol: {bugun_str} {saat_str}", "content": yeni}
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


# === 1. Sinyal verisini al (bugun icin karli/zararli saatler) ===
sinyal, _ = dosya_oku("sinyal.json")
if not sinyal:
    print("sinyal.json yok, atlaniyor")
    exit(0)

sinyal_tarihi = sinyal.get("tarih")
if sinyal_tarihi != bugun_str:
    # Sinyal yarin icin - bugun icin uygulanmaz
    print(f"Sinyal {sinyal_tarihi} icin, bugun ({bugun_str}) icin atlaniyor")
    exit(0)

karli_saatler = [int(s) for s in sinyal.get("karli_saatler", [])]
zararli_saatler = [int(s) for s in sinyal.get("zararli_saatler", [])]

# === 2. Mevcut cihaz durumunu al ===
antminer, _ = dosya_oku("antminer_panel.json")
if not antminer:
    print("antminer_panel.json yok, sahada panel calismiyor olabilir")
    exit(0)

devices = antminer.get("devices", [])
if not devices:
    print("Cihaz yok")
    exit(0)

online_count = sum(1 for d in devices if d.get("online") and not d.get("sleeping"))
sleeping_count = sum(1 for d in devices if d.get("sleeping"))

cihazlar_calisiyor = online_count > sleeping_count  # Cogunluk acik mi?

# === 3. Karar mantigi ===
sonraki_karli = saat_sonraki in karli_saatler

# Onceki bekleyen onaylar
bekleyen, bekleyen_sha = dosya_oku("bekleyen_onaylar.json")
if not bekleyen:
    bekleyen = {"onaylar": []}

# Bugun bu saat icin zaten onay olusturulmus mu?
key = f"{bugun_str}_{saat_sonraki:02d}"
zaten_var = any(o.get("key") == key and o.get("durum") in ("bekliyor", "onaylandi") for o in bekleyen["onaylar"])

if zaten_var:
    print(f"Saat {saat_sonraki:02d}:00 icin onay zaten var")
    exit(0)

# Karar ver
eylem = None
if sonraki_karli and not cihazlar_calisiyor:
    # Karli saate giriyor, cihazlar kapali - AC
    eylem = "wake"
elif not sonraki_karli and cihazlar_calisiyor:
    # Zararli saate giriyor, cihazlar acik - UYUT
    eylem = "sleep"

if not eylem:
    print(f"Saat {saat_sonraki:02d} icin eylem gerekmiyor (karli={sonraki_karli}, calisan={cihazlar_calisiyor})")
    exit(0)

# === 4. Onay olustur ===
import uuid
onay_id = str(uuid.uuid4())[:8]

eylem_ad = "ÇALIŞTIR" if eylem == "wake" else "UYUT"
saat_ad = "Kârlı" if sonraki_karli else "Zararlı"

yeni_onay = {
    "id": onay_id,
    "key": key,
    "tarih": bugun_str,
    "hedef_saat": saat_sonraki,
    "olusturulma": saat_str,
    "eylem": eylem,  # wake | sleep
    "durum": "bekliyor",  # bekliyor | onaylandi | reddedildi | suresi_doldu
    "saat_durumu": saat_ad,
    "mevcut_online": online_count,
    "mevcut_sleeping": sleeping_count,
}

bekleyen["onaylar"].append(yeni_onay)
# Son 50 onay tut
bekleyen["onaylar"] = bekleyen["onaylar"][-50:]
bekleyen["son_guncelleme"] = f"{bugun_str} {saat_str}"

dosya_yaz("bekleyen_onaylar.json", bekleyen, bekleyen_sha)
print(f"Onay olusturuldu: {onay_id} - {eylem} - saat {saat_sonraki:02d}")

# === 5. WhatsApp bildirim ===
onay_link = f"{OTOCOIN_URL}/onay/{onay_id}"
mesaj = f"""⏰ SAAT {saat_sonraki:02d}:00 - {saat_ad.upper()} SAAT

Eylem: {eylem_ad}
Mevcut: {online_count} acik, {sleeping_count} uyuyor

ONAY: {onay_link}
veya Otocoin > Bekleyen Onaylar

Saat: {saat_str}"""

whatsapp_gonder(mesaj)
print("Tamamlandi.")
