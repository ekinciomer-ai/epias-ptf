import datetime, os, json, urllib.request, urllib.error, base64
from eptr2 import EPTR2
from twilio.rest import Client

EPIAS_KULLANICI  = os.environ.get("EPIAS_KULLANICI", "")
EPIAS_SIFRE      = os.environ.get("EPIAS_SIFRE", "")
TWILIO_SID       = os.environ.get("TWILIO_SID", "")
TWILIO_TOKEN     = os.environ.get("TWILIO_TOKEN", "")
TWILIO_NUMARA    = "whatsapp:+14155238886"
KENDI_NUMARA     = "whatsapp:+905438703340"
IKINCI_NUMARA    = "whatsapp:+905443977380"
GH_TOKEN         = os.environ.get("GH_TOKEN", "")
F2POOL_TOKEN     = os.environ.get("F2POOL_TOKEN", "")
F2POOL_KULLANICI = os.environ.get("F2POOL_KULLANICI", "mehmetas")
REPO             = "ekinciomer-ai/epias-ptf"

CIHAZ_SAYISI  = 29
CIHAZ_GUC_W   = 6000
YEKDEM        = 602.51
TOPLAM_KW     = CIHAZ_SAYISI * CIHAZ_GUC_W / 1000  # 174 kW
GUNLUK_BTC_VARSAYILAN = 0.0037

bugun   = datetime.date.today().strftime("%Y-%m-%d")
yarin   = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
ay_key  = datetime.date.today().strftime("%Y-%m")
saat_tr = (datetime.datetime.utcnow() + datetime.timedelta(hours=3)).strftime("%H:%M")
GUNLER  = ["Pazartesi","Sali","Carsamba","Persembe","Cuma","Cumartesi","Pazar"]

def whatsapp_gonder(mesaj):
    """Twilio hatasi isi dusurmesin (sandbox suresi dolmus olabilir): hata yazilir, devam edilir."""
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
    except Exception as e:
        print(f"WhatsApp HATA (istemci): {e}"); return False
    ok = True
    for numara in [KENDI_NUMARA, IKINCI_NUMARA]:
        try:
            client.messages.create(body=mesaj, from_=TWILIO_NUMARA, to=numara)
        except Exception as e:
            ok = False; print(f"WhatsApp HATA ({numara[-4:]}): {str(e)[:200]}")
    print("WhatsApp gonderildi!" if ok else "WhatsApp kismen/hic gonderilemedi")
    return ok

def dosya_oku(dosya):
    """CDN-oncelikli okuma (public repo, token gerekmez).
    Yazma icin sha lazimsa API'dan ayrica cekilir."""
    # 1. CDN dene - token YOK, 401 olmaz
    cdn_url = f"https://raw.githubusercontent.com/{REPO}/main/{dosya}?t={int(datetime.datetime.utcnow().timestamp())}"
    try:
        with urllib.request.urlopen(cdn_url, timeout=15) as resp:
            icerik = json.loads(resp.read())
            print(f"[CDN OK] {dosya}")
            # SHA'yi ayrica cek (yazma icin gerek)
            sha = _sha_cek(dosya)
            return icerik, sha
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[CDN 404] {dosya} - yeni dosya")
            return None, None
        print(f"[CDN {e.code}] API'ya geciliyor")
    except Exception as e:
        print(f"[CDN hata] {e}, API'ya geciliyor")
    
    # 2. API fallback (token ile, eski mantik)
    try:
        url = f"https://api.github.com/repos/{REPO}/contents/{dosya}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        })
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            icerik = json.loads(base64.b64decode(data["content"]).decode())
            print(f"[API OK] {dosya}")
            return icerik, data["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        print(f"[API HATA {e.code}] {dosya}")
        # Son care: bos dict don, sha=None
        # Yazma denenince yeni dosya gibi davranir
        return None, None

def _sha_cek(dosya):
    """Yazma icin sha'yi API'dan getir (kucuk istek). Token bozuksa None doner."""
    try:
        url = f"https://api.github.com/repos/{REPO}/contents/{dosya}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("sha")
    except:
        return None

def dosya_yaz(dosya, icerik, sha=None):
    yeni = base64.b64encode(json.dumps(icerik, ensure_ascii=False, indent=2).encode()).decode()
    body = {"message": f"Guncelleme: {bugun} {saat_tr}", "content": yeni}
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

def f2pool_dunku_btc():
    """F2Pool'dan dünkü gerçek BTC kazancını çek"""
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
            toplam_btc = sum(t.get("changed_balance", 0) for t in transactions)
            hashrate   = transactions[0].get("mining_extra", {}).get("hash_rate", 0)
            ths        = hashrate / 1_000_000_000_000 if hashrate else 0
            print(f"F2Pool dunku BTC: {toplam_btc:.8f} BTC | Hashrate: {ths:.0f} TH/s")
            return toplam_btc, ths
    except Exception as e:
        print(f"F2Pool verisi alinamadi: {e}")
    return None, None

# ============================================================
# YENI MANTIK: "Yarinin verisini gonderdik mi?" diye kontrol et
# Eski mantik: "Bugun script kosturuldu mu?" diye kontrol ediyordu
# ============================================================

gonderim, sha = dosya_oku("son_gonderim.json")

# YARIN icin gonderim yapildiysa atla (yarin = hedef tarih)
# Boylelikle script gun icinde defalarca calissa bile, yarinin verisi geldigine emin olunur
if gonderim and gonderim.get("hedef_tarih") == yarin:
    print(f"Yarinin ({yarin}) verisi zaten gonderildi.")
    exit(0)

# Sadece yarin'i dene - bugun varsa atma (yarinin verisi cikmamissa bekle)
items = []
hedef_str = ""
hedef_tarih = yarin
try:
    eptr  = EPTR2(username=EPIAS_KULLANICI, password=EPIAS_SIFRE)
    sonuc = eptr.call("mcp", start_date=yarin, end_date=yarin, postprocess=False)
    items = sonuc.get("items", [])
    if items:
        dt = datetime.date.fromisoformat(yarin)
        hedef_str = f"{dt.strftime('%d.%m.%Y')} {GUNLER[dt.weekday()]}"
        print(f"EPiAS verisi bulundu: {yarin}")
except Exception as e:
    print(f"{yarin} verisi yok: {e}")

if not items:
    # Yarinin verisi yok - sadece sabah ilk denemede uyari at, sonraki denemelerde sessiz cik
    son_uyari = gonderim.get("son_bekleme_uyarisi") if gonderim else None
    if son_uyari != bugun:
        print(f"EPiAS PTF beklemede: yarin ({yarin}) verisi henuz yok ({saat_tr}). Uyari bildirim_isler.py'den (konu: sistem).")
        # Uyari gonderildi isaretle
        yeni_gonderim = gonderim or {}
        yeni_gonderim["son_bekleme_uyarisi"] = bugun
        dosya_yaz("son_gonderim.json", yeni_gonderim, sha)
    else:
        print(f"Yarinin verisi yok ama bugun zaten uyari gonderilmis. Sessiz cikiyorum.")
    exit(0)

# BTC fiyatı
try:
    btc_try, btc_usd = btc_cek()
    print(f"BTC: {btc_try:.0f} TL | {btc_usd:.0f} USD")
except:
    btc_try, btc_usd = 0, 0

kur = btc_try / btc_usd if btc_usd > 0 and btc_try > 0 else 1

# F2Pool'dan dünkü gerçek BTC kazancı
f2_btc, f2_ths = f2pool_dunku_btc()
GUNLUK_BTC = f2_btc if f2_btc and f2_btc > 0 else GUNLUK_BTC_VARSAYILAN
f2_kaynak  = "F2Pool gercek" if f2_btc else "tahmini"
print(f"Kullanilan gunluk BTC: {GUNLUK_BTC:.8f} ({f2_kaynak})")

# ============================================================
# Karlilik: panel ve Pi cihaz yonetimi ile AYNI kural ve degerler (n8n/cihaz_yonetimi_durum.json):
#   cihaz basi saatlik maliyet = (PTF + YEKDEM) / 1000 x carpan x cihaz gucu (kW)
#   cihaz basi saatlik gelir   = hashprice (F2Pool, BTC/TH/gun) x cihaz TH / 24 x BTC/TL
#   gunes saatleri (dogus+1 .. batis-1) her zaman CALIS; diger saatler gelir >= maliyet ise CALIS
# (Eski hesap dunku gercek BTC'yi "karli saat" sayisina bolup her saate yaziyordu; dunku calisma azsa
#  saatlik gelir sisiyor, 24/24 karli ve +170.000 TL gibi yanlis sonuclar cikiyordu.)
# ============================================================
import math
yon, _ = dosya_oku("n8n/cihaz_yonetimi_durum.json")
yon = yon or {}
ay = yon.get("ayarlar") or {}
KAT      = ay.get("maliyet_carpani") or 1.035
CIHAZ_KW = ay.get("cihaz_guc_kw") or 5.59
CIHAZ_TH = ay.get("cihaz_th") or 285
ESIK_KW  = ay.get("uretim_esik_kw") or 50
YEKDEM   = yon.get("yekdem") or YEKDEM
HP       = yon.get("hashprice_btc_th_gun")
if not btc_try and yon.get("btc_try"):       # BTC fiyatı çekilemediyse cihaz yönetiminin son fiyatı
    btc_try = yon["btc_try"]
kim, _ = dosya_oku("n8n/cihaz_kimlik.json")
FILO = len([v for v in (kim or {}).values() if not v.get("not")]) or CIHAZ_SAYISI
TOPLAM_KW = FILO * CIHAZ_KW
if HP:
    gelir_cihaz = HP * CIHAZ_TH / 24 * btc_try if btc_try > 0 else 0
    f2_kaynak = "hashprice " + f"{HP*1e8:.1f} sat/TH-gun"
else:   # yedek: dunku gercek BTC / dunku ortalama TH (F2Pool)
    gelir_cihaz = (GUNLUK_BTC / f2_ths * CIHAZ_TH / 24 * btc_try) if (f2_ths and btc_try > 0) else 0
    f2_kaynak = "F2Pool dunku verim"

def gunes_saatleri(gun):
    n = gun.timetuple().tm_yday; g = 2 * math.pi / 365 * (n - 1)
    dek = 0.006918 - 0.399912*math.cos(g) + 0.070257*math.sin(g) - 0.006758*math.cos(2*g) + 0.000907*math.sin(2*g)
    eq = 229.18 * (0.000075 + 0.001868*math.cos(g) - 0.032077*math.sin(g) - 0.014615*math.cos(2*g) - 0.040849*math.sin(2*g))
    la = math.radians(38.37)
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(la)*math.cos(dek)) - math.tan(la)*math.tan(dek)))
    og = (720 - 4*34.03 - eq) / 60 + 3
    return og - ha/15, og + ha/15
dog, bat = gunes_saatleri(datetime.date.fromisoformat(hedef_tarih))

satirlar = []; satirlar_sinyal = []
toplam_kar = toplam_maliyet = toplam_btc_gelir = 0
karli_saat = 0; karli_saatler = []; zararli_saatler = []; saatlik_detay = []
for item in items:
    saat = item["hour"]; h = int(saat[:2]); ptf = item["price"]
    m_c = (ptf + YEKDEM) / 1000 * KAT * CIHAZ_KW
    gunes = (dog + 1.0) <= h and (h + 1) <= (bat - 1.0)
    calis = gunes or gelir_cihaz >= m_c
    maliyet_tl, gelir_tl = m_c * FILO, gelir_cihaz * FILO
    kar = gelir_tl - maliyet_tl
    saatlik_detay.append({"saat": saat[:2], "ptf": ptf, "maliyet": round(maliyet_tl, 2), "btc_gelir_tl": round(gelir_tl, 2),
                          "kar": round(kar, 2), "karli": calis, "gunes": gunes})
    if calis:
        karli_saat += 1; karli_saatler.append(saat[:2])
        toplam_kar += kar; toplam_maliyet += maliyet_tl; toplam_btc_gelir += gelir_tl
    else:
        zararli_saatler.append(saat[:2])
    isaret = "☀️" if gunes else ("✅" if calis else "❌")
    satirlar.append(f"{isaret} {saat[:2]} | {ptf:.0f} | {maliyet_tl:,.0f} | {gelir_tl:,.0f} | {kar:+,.0f}")
for row_start in range(0, 24, 6):
    satirlar_sinyal.append("".join(f"{i:02d}{('☀️' if saatlik_detay[i]['gunes'] else '✅' if saatlik_detay[i]['karli'] else '❌')}"
                                   for i in range(row_start, min(row_start + 6, len(saatlik_detay)))))

gunluk_kwh     = karli_saat * TOPLAM_KW
gunluk_btc_tl  = toplam_btc_gelir
gunluk_btc_usd = toplam_btc_gelir / kur if kur else 0
gunluk_kar_usd = toplam_kar / kur
maliyet_usd    = toplam_maliyet / kur
GUNLUK_BTC     = (toplam_btc_gelir / btc_try) if btc_try > 0 else GUNLUK_BTC

mesaj3 = f"""EPiAS {hedef_str}
☀️ gunes · ✅ karli · ❌ uyut
──────────────────────
{chr(10).join(satirlar_sinyal)}"""

mesaj1 = f"""EPiAS KARLILIK {hedef_str}
Filo {FILO} cihaz · {TOPLAM_KW:.0f} kW
BTC:{btc_try:,.0f}TL · {f2_kaynak}
Maliyet=(PTF+YEKDEM {YEKDEM:.0f})x{KAT:.3f}
Saat|PTF|Maliyet|Gelir|Fark (TL/saat, filo)
{chr(10).join(satirlar)}
Calisma:{karli_saat}/24 saat · Beklenen net:{toplam_kar:+,.0f}TL"""

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
mesaj2 = f"""GUNLUK OZET (beklenen) {hedef_str}
BTC:{GUNLUK_BTC:.5f}BTC ({karli_saat} saat calisma)
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

# WhatsApp: artik buradan gonderilmiyor. Yarinin plani Pi planindan (cihaz_yonetimi_durum.json) grafikle
# bildirim_isler.py tarafindan, n8n/bildirim_ayar.json'da "plan" konusunu secen kisilere gider.

# Sinyal dosyası (her zaman üzerine yaz - en güncel gün)
sinyal_data = {
    "tarih": hedef_tarih,
    "guncelleme": saat_tr,
    "karli_saatler": karli_saatler,
    "zararli_saatler": zararli_saatler,
    "btc_try": btc_try,
    "btc_usd": btc_usd,
    "gunluk_btc": GUNLUK_BTC,
    "gunluk_kar_tl": round(toplam_kar, 2),
    "gunluk_maliyet_tl": round(toplam_maliyet, 2),
    "ptf_saatlik": [item["price"] for item in items]
}
sinyal_sha_data, sinyal_sha = dosya_oku("sinyal.json")
dosya_yaz("sinyal.json", sinyal_data, sinyal_sha)

# *** YENI: Gunluk arsiv - tum gunleri saklar ***
arsiv, arsiv_sha = dosya_oku("gunluk_arsiv.json")
if not arsiv:
    arsiv = {"gunler": {}}

arsiv["gunler"][hedef_tarih] = {
    "tarih": hedef_tarih,
    "gun_adi": GUNLER[datetime.date.fromisoformat(hedef_tarih).weekday()],
    "olusturulma": f"{bugun} {saat_tr}",
    "btc_try": btc_try,
    "btc_usd": btc_usd,
    "gunluk_btc": GUNLUK_BTC,
    "btc_kaynak": f2_kaynak,
    "karli_saat_sayisi": karli_saat,
    "zararli_saat_sayisi": 24 - karli_saat,
    "karli_saatler": karli_saatler,
    "zararli_saatler": zararli_saatler,
    "toplam_kar_tl": round(toplam_kar, 2),
    "toplam_maliyet_tl": round(toplam_maliyet, 2),
    "toplam_btc_gelir_tl": round(toplam_btc_gelir, 2),
    "gunluk_kwh": gunluk_kwh,
    "ptf_saatlik": [item["price"] for item in items],
    "saatlik_detay": saatlik_detay,
}

# Sadece son 90 gunu tut (eski kayitlari sil)
cutoff = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
arsiv["gunler"] = {k: v for k, v in arsiv["gunler"].items() if k >= cutoff}
arsiv["son_guncelleme"] = f"{bugun} {saat_tr}"
arsiv["gun_sayisi"] = len(arsiv["gunler"])

dosya_yaz("gunluk_arsiv.json", arsiv, arsiv_sha)
print(f"Gunluk arsive eklendi: {hedef_tarih}")

# *** YENI: aylik_ptf.json - aya gore PTF saatlik ***
# Format: { "2026-05": { "14": [saat0_fiyat, saat1_fiyat, ...], ... } }
hedef_ay = hedef_tarih[:7]   # "2026-05"
hedef_gun = hedef_tarih[8:10]  # "14"

ayptf, ayptf_sha = dosya_oku("aylik_ptf.json")

# *** GUVENLIK KILIDI: gecmis veriyi asla ezme ***
# Okuma basarisiz (None) ise ya da beklenmedik tip ise YAZMA.
# Bos dict sadece ilk kurulumda olur; dosya zaten aylardir var, bos gelirse okuma hatasidir.
_ptf_yaz = True
if ayptf is None or not isinstance(ayptf, dict):
    print("[GUVENLIK] aylik_ptf.json okunamadi (None/gecersiz) - gecmisi korumak icin YAZILMIYOR")
    _ptf_yaz = False
else:
    _onceki_gun = sum(len(v) for v in ayptf.values() if isinstance(v, dict))
    if hedef_ay not in ayptf:
        ayptf[hedef_ay] = {}
    # Saatlik fiyatlari TL/MWh formatinda yaz (EPiAS'dan geldigi gibi)
    ayptf[hedef_ay][hedef_gun] = [round(item["price"], 2) for item in items]
    _yeni_gun = sum(len(v) for v in ayptf.values() if isinstance(v, dict))
    # Normalde sadece gun EKLENIR (yeni >= onceki). Dususe geciyorsa okuma bozuk demektir.
    if _onceki_gun >= 10 and _yeni_gun < _onceki_gun:
        print(f"[GUVENLIK] gun sayisi {_onceki_gun}->{_yeni_gun} DUSUYOR - YAZILMIYOR")
        _ptf_yaz = False

if _ptf_yaz:
    dosya_yaz("aylik_ptf.json", ayptf, ayptf_sha)
    print(f"aylik_ptf.json guncellendi: {hedef_ay}/{hedef_gun} ({_yeni_gun} gun)")

# son_gonderim.json - HEDEF TARIH'i sakla (bugun degil)
dosya_yaz("son_gonderim.json", {
    "hedef_tarih": hedef_tarih,
    "gonderim_zamani": f"{bugun} {saat_tr}",
    "tarih": bugun,  # Geriye uyumluluk
}, sha)

dosya_yaz(f"aylik_{ay_key}.json", ay_data, ay_sha)
print(f"Tamamlandi: hedef tarih {hedef_tarih}")
