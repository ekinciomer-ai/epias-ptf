"""
Saat Kontrol - Her saat 50. dakikada calisir.
- aylik_ptf.json'dan BUGUNUN saatlik PTF degerlerini okur
- Bir sonraki saatin karli/zararli durumunu hesaplar
- Cihaz durumuyla karsilastirir
- Eylem gerekiyorsa: WhatsApp + Otocoin bekleyen onaylar
"""
import datetime, os, json, urllib.request, urllib.error, base64
from twilio.rest import Client

TWILIO_SID       = os.environ.get("TWILIO_SID", "")
TWILIO_TOKEN     = os.environ.get("TWILIO_TOKEN", "")
TWILIO_NUMARA    = "whatsapp:+14155238886"
KENDI_NUMARA     = "whatsapp:+905438703340"
IKINCI_NUMARA    = "whatsapp:+905443977380"
GH_TOKEN         = os.environ.get("GH_TOKEN", "")
F2POOL_TOKEN     = os.environ.get("F2POOL_TOKEN", "")
F2POOL_KULLANICI = os.environ.get("F2POOL_KULLANICI", "mehmetas")
REPO             = "ekinciomer-ai/epias-ptf"
OTOCOIN_URL      = os.environ.get("OTOCOIN_URL", "https://epias-ptf-production.up.railway.app")

CIHAZ_SAYISI = 29
CIHAZ_GUC_W  = 6000
YEKDEM       = 602.51
TOPLAM_KW    = CIHAZ_SAYISI * CIHAZ_GUC_W / 1000
GUNLUK_BTC_VARSAYILAN = 0.0037

now_tr = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
saat_simdi = now_tr.hour
saat_sonraki = (saat_simdi + 1) % 24
bugun_str = now_tr.date().strftime("%Y-%m-%d")
saat_str = now_tr.strftime("%H:%M")


def whatsapp_gonder(mesaj):
    if not TWILIO_SID:
        print("TWILIO env yok:")
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


def btc_cek():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,try"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
            return float(data["bitcoin"]["try"]), float(data["bitcoin"]["usd"])
    except:
        return 0, 0


def f2pool_gunluk_btc():
    if not F2POOL_TOKEN:
        return None
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        dun_baslangic = int((now - datetime.timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        dun_bitis     = int((now - datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        data = json.dumps({
            "currency": "bitcoin",
            "mining_user_name": F2POOL_KULLANICI,
            "type": "revenue",
            "start_time": dun_baslangic,
            "end_time": dun_bitis
        }).encode()
        req = urllib.request.Request(
            "https://api.f2pool.com/v2/assets/transactions/list",
            data=data,
            headers={
                "Content-Type": "application/json",
                "F2P-API-SECRET": F2POOL_TOKEN
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
        transactions = result.get("transactions", [])
        if transactions:
            return sum(t.get("changed_balance", 0) for t in transactions)
    except Exception as e:
        print(f"F2Pool hata: {e}")
    return None


# 1. BUGUNUN PTF verisi
ayptf, _ = dosya_oku("aylik_ptf.json")
if not ayptf:
    print("aylik_ptf.json bulunamadi")
    exit(0)

ay_key = bugun_str[:7]
gun_key = bugun_str[8:10]

bugun_ptf = ayptf.get(ay_key, {}).get(gun_key)
if not bugun_ptf or len(bugun_ptf) != 24:
    print(f"Bugun ({bugun_str}) icin PTF verisi yok veya eksik (uzunluk: {len(bugun_ptf) if bugun_ptf else 0})")
    exit(0)

print(f"Bugun PTF: 24 saat (sonraki saat {saat_sonraki:02d}: {bugun_ptf[saat_sonraki]} TL/MWh)")

# 2. BTC fiyat
btc_try, btc_usd = btc_cek()
if btc_try <= 0:
    print("BTC fiyat alinamadi")
    exit(0)

gunluk_btc = f2pool_gunluk_btc() or GUNLUK_BTC_VARSAYILAN
print(f"BTC: {btc_try:.0f} TL, Gunluk: {gunluk_btc:.5f}")

# 3. Karli saat sayisi
karli_saat_on = 0
for ptf_tl_mwh in bugun_ptf:
    ptf_tl_kwh    = ptf_tl_mwh / 1000
    yekdem_tl_kwh = YEKDEM / 1000
    maliyet_tl    = (ptf_tl_kwh + yekdem_tl_kwh) * 1.05 * TOPLAM_KW
    btc_gelir     = (gunluk_btc / 24) * btc_try
    if btc_gelir > maliyet_tl:
        karli_saat_on += 1

saatlik_btc = gunluk_btc / karli_saat_on if karli_saat_on > 0 else gunluk_btc / 24

# 4. Sonraki saat karli mi?
sonraki_ptf_tl_mwh = bugun_ptf[saat_sonraki]
sonraki_maliyet    = (sonraki_ptf_tl_mwh / 1000 + YEKDEM / 1000) * 1.05 * TOPLAM_KW
sonraki_gelir      = saatlik_btc * btc_try
sonraki_kar        = sonraki_gelir - sonraki_maliyet
sonraki_karli      = sonraki_kar > 0

print(f"Saat {saat_sonraki:02d}:00 -> Kar: {sonraki_kar:+.0f} TL ({'KARLI' if sonraki_karli else 'ZARARLI'})")

# 5. Cihaz durumu
antminer, _ = dosya_oku("antminer_panel.json")
if not antminer:
    print("antminer_panel.json yok")
    exit(0)

devices = antminer.get("devices", [])
online_count = sum(1 for d in devices if d.get("online") and not d.get("sleeping"))
sleeping_count = sum(1 for d in devices if d.get("sleeping"))
cihazlar_calisiyor = online_count > sleeping_count

print(f"Cihazlar: {online_count} acik, {sleeping_count} uyuyor")

# 6. Karar
eylem = None
if sonraki_karli and not cihazlar_calisiyor:
    eylem = "wake"
elif not sonraki_karli and cihazlar_calisiyor:
    eylem = "sleep"

if not eylem:
    print(f"Eylem gerekmiyor")
    exit(0)

# 7. Duplicate kontrol
bekleyen, bekleyen_sha = dosya_oku("bekleyen_onaylar.json")
if not bekleyen:
    bekleyen = {"onaylar": []}

key = f"{bugun_str}_{saat_sonraki:02d}"
zaten_var = any(o.get("key") == key and o.get("durum") in ("bekliyor", "onaylandi") for o in bekleyen["onaylar"])
if zaten_var:
    print(f"Saat {saat_sonraki:02d}:00 icin onay zaten var")
    exit(0)

# 8. Onay olustur
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
    "eylem": eylem,
    "durum": "bekliyor",
    "saat_durumu": saat_ad,
    "sonraki_ptf": sonraki_ptf_tl_mwh,
    "sonraki_maliyet_tl": round(sonraki_maliyet, 2),
    "sonraki_gelir_tl": round(sonraki_gelir, 2),
    "sonraki_kar_tl": round(sonraki_kar, 2),
    "mevcut_online": online_count,
    "mevcut_sleeping": sleeping_count,
}

bekleyen["onaylar"].append(yeni_onay)
bekleyen["onaylar"] = bekleyen["onaylar"][-50:]
bekleyen["son_guncelleme"] = f"{bugun_str} {saat_str}"

dosya_yaz("bekleyen_onaylar.json", bekleyen, bekleyen_sha)
print(f"Onay olusturuldu: {onay_id} - {eylem}")

# 9. WhatsApp
onay_link = f"{OTOCOIN_URL}/onay/{onay_id}"
mesaj = f"""⏰ SAAT {saat_sonraki:02d}:00 - {saat_ad.upper()}

Eylem: {eylem_ad}
PTF: {sonraki_ptf_tl_mwh:.0f} TL/MWh
Maliyet: {sonraki_maliyet:.0f} TL
Kar: {sonraki_kar:+.0f} TL

Mevcut: {online_count} acik, {sleeping_count} uyuyor

ONAY: {onay_link}
veya Otocoin > Cihazlarim

Saat: {saat_str}"""

whatsapp_gonder(mesaj)
print("Tamamlandi")
