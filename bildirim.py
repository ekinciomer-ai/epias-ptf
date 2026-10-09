"""WhatsApp bildirim gönderici (Twilio) — konuya göre alıcı seçer.

Kim hangi konuyu alır: n8n/bildirim_ayar.json (panel → Bildirimler).
Numaralar depoda YOK: her kişi için GitHub gizli değişkeni BILDIRIM_<anahtar> (ör. BILDIRIM_K3 = +905xxxxxxxxx);
iş akışı bunları ortam değişkeni olarak verir. K1/K2 için gizli değişken yoksa eski sabit numaralar kullanılır.
Her gönderim n8n/bildirim_kayit.json'a yazılır (son 300; numara değil kişi adı ve son 4 hane).
"""
import json, os, time
from datetime import datetime, timedelta, timezone

TR = timezone(timedelta(hours=3))
GONDEREN = "whatsapp:+14155238886"
AYAR, KAYIT = "n8n/bildirim_ayar.json", "n8n/bildirim_kayit.json"
_ESKI = {"K1": "+905438703340", "K2": "+905443977380"}     # gizli değişken tanımlanana kadar
_istemci, _gonderilen = None, []
# Twilio hata kodları (WhatsApp) → anlaşılır açıklama
HATA = {63016: "24 saat penceresi dışında (alıcı son 24 saatte bu numaraya yazmamış)",
        63015: "alıcı sandbox'a katılmamış ya da katılımı düşmüş (join ... mesajını tekrar göndermeli)",
        63003: "numara WhatsApp'ta yok / geçersiz", 21211: "numara geçersiz", 21608: "deneme hesabı: numara doğrulanmamış",
        63018: "gönderim hız sınırı", 63038: "günlük mesaj sınırı (sandbox) doldu", 20003: "Twilio kimliği hatalı"}


def oku(y, v=None):
    try:
        return json.load(open(y))
    except Exception:
        return v


def ayar():
    return oku(AYAR, {}) or {}


def numara(k):
    n = (os.environ.get("BILDIRIM_" + k["anahtar"]) or _ESKI.get(k["anahtar"]) or "").strip().replace(" ", "")
    if n and not n.startswith("+"):
        n = "+90" + n.lstrip("0") if len(n.lstrip("0")) == 10 else "+" + n
    return n


def alicilar(konu):
    return [k for k in ayar().get("kisiler") or [] if k.get("aktif", True) and konu in (k.get("konular") or [])]


def _client():
    global _istemci
    if _istemci is None:
        sid, tok = os.environ.get("TWILIO_SID"), os.environ.get("TWILIO_TOKEN")
        if not sid or not tok:
            return None
        from twilio.rest import Client
        _istemci = Client(sid, tok)
    return _istemci


def _kayit(o):
    k = oku(KAYIT, {}) or {}
    l = (k.get("kayit") or []) + [o]
    json.dump({"guncellendi": datetime.now(TR).isoformat(timespec="seconds"), "kayit": l[-300:]}, open(KAYIT, "w"), ensure_ascii=False, indent=1)


SINIR = False        # son gonder() çağrısında hiçbir alıcıya gitmedi ve en az biri "günlük sınır" (63038) aldı


def gonder(konu, metin, gorsel=None, kisiler=None):
    """konu: bildirim_ayar konularından biri. gorsel: herkese açık https görsel adresi (WhatsApp'ta resim olarak gelir).
    Sonra B.SINIR True ise mesaj sınır yüzünden kimseye gitmedi: çağıran 'gönderildi' işaretlemesin, sonraki turda tekrar denesin."""
    global SINIR
    sonuc = []
    hedef = kisiler if kisiler is not None else alicilar(konu)
    print(f"--- [{konu}] → {', '.join(k['ad'] for k in hedef) or 'alıcı yok'}\n{metin}" + (f"\n(görsel {gorsel})" if gorsel else ""))
    c = _client()
    for k in hedef:
        o = {"t": datetime.now(TR).isoformat(timespec="seconds"), "konu": konu, "kisi": k["ad"], "anahtar": k["anahtar"],
             "son4": k.get("son4", ""), "ozet": metin.split("\n")[0][:80]}
        n = numara(k)
        if not n:
            o.update(ok=False, hata=f"numara yok: GitHub gizli değişkeni BILDIRIM_{k['anahtar']} tanımlanmalı")
        elif c is None:
            o.update(ok=False, hata="Twilio kimliği yok (yalnız deneme çıktısı)")
        else:
            try:
                arg = {"body": metin, "from_": GONDEREN, "to": "whatsapp:" + n}
                if gorsel:
                    arg["media_url"] = [gorsel]
                m = c.messages.create(**arg)
                o.update(ok=True, sid=m.sid, durum=m.status)
                _gonderilen.append(o)
            except Exception as e:
                kod = getattr(e, "code", None)
                o.update(ok=False, kod=kod, hata=(HATA.get(kod) or str(e))[:200])
        if not o["ok"]:
            print("  !", k["ad"], o.get("hata"))
        _kayit(o)
        sonuc.append(o)
    SINIR = bool(sonuc) and not any(o["ok"] for o in sonuc) and any(o.get("kod") == 63038 for o in sonuc)
    return hedef


def teslim_kontrol(bekle=12):
    """Gönderilen mesajların teslim durumunu Twilio'dan okur (24 saat penceresi gibi sessiz hatalar burada görünür)."""
    if not _gonderilen or _client() is None:
        return
    time.sleep(bekle)
    k = oku(KAYIT, {}) or {}
    l = k.get("kayit") or []
    for o in _gonderilen:
        try:
            m = _client().messages(o["sid"]).fetch()
        except Exception as e:
            continue
        for x in l:
            if x.get("sid") == o["sid"]:
                x["durum"] = m.status
                if m.error_code:
                    x.update(ok=False, kod=m.error_code, hata=HATA.get(int(m.error_code), f"Twilio hata {m.error_code}"))
                    print("  ! teslim edilemedi:", x["kisi"], x["hata"])
    json.dump({"guncellendi": datetime.now(TR).isoformat(timespec="seconds"), "kayit": l[-300:]}, open(KAYIT, "w"), ensure_ascii=False, indent=1)
    _gonderilen.clear()
