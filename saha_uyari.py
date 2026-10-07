"""Saha uyarısı — GitHub Actions (15 dk'da bir). WhatsApp (Twilio) ile haber verir, her sorun için bir kez
(başlayınca) ve düzelince bir kez. Durum: n8n/uyari_durum.json.
  pi_sessiz      : antminer_panel.json (Pi toplayıcı) 20 dk'dır güncellenmiyor → Pi / saha interneti / modem
  yonetim_durdu  : cihaz yönetimi 20 dk'dır karar yazmıyor
  bekci_basarisiz: bekçi bir cihazı onaramadı (n8n/bekci.json)
"""
import json, os
from datetime import datetime, timedelta, timezone

TR = timezone(timedelta(hours=3))
NUMARALAR = ["whatsapp:+905438703340", "whatsapp:+905443977380"]
GONDEREN = "whatsapp:+14155238886"


def oku(y):
    try:
        return json.load(open(y))
    except Exception:
        return None


def zaman(s):
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t.replace(tzinfo=TR) if t.tzinfo is None else t


def gonder(mesaj):
    print("UYARI:", mesaj)
    sid, tok = os.environ.get("TWILIO_SID"), os.environ.get("TWILIO_TOKEN")
    if not sid:
        return
    from twilio.rest import Client
    c = Client(sid, tok)
    for n in NUMARALAR:
        try:
            c.messages.create(body=mesaj, from_=GONDEREN, to=n)
        except Exception as e:
            print("twilio hata", n, e)


def main():
    simdi = datetime.now(TR)
    durum = oku("n8n/uyari_durum.json") or {}
    sorun = {}
    mad = oku("antminer_panel.json") or {}
    if mad.get("timestamp") and simdi - zaman(mad["timestamp"]) > timedelta(minutes=20):
        sorun["pi_sessiz"] = f"Saha verisi {int((simdi - zaman(mad['timestamp'])).total_seconds() // 60)} dk'dır gelmiyor (son {zaman(mad['timestamp']):%H:%M}). Pi, modem ya da saha interneti kontrol edilmeli."
    y = oku("n8n/cihaz_yonetimi_durum.json") or {}
    if y.get("guncellendi") and simdi - zaman(y["guncellendi"]) > timedelta(minutes=20) and "pi_sessiz" not in sorun:
        sorun["yonetim_durdu"] = f"Cihaz yönetimi {zaman(y['guncellendi']):%H:%M}'den beri karar vermiyor (mod {y.get('mod')})."
    b = oku("n8n/bekci.json") or {}
    son_b = durum.get("bekci_son", "")
    yeni = [o for o in b.get("olaylar") or [] if o.get("t", "") > son_b]
    for o in yeni:
        if o.get("sonuc") == "BAŞARISIZ":
            gonder(f"⚠️ AEMonitoring bekçi: {o['cihaz']} ({o['ip']}) {o['olay']} başarısız — {o.get('ayrinti','')}. Sahada bakılmalı.")
    if yeni:
        durum["bekci_son"] = max(o["t"] for o in yeni)
    aktif = durum.get("aktif", {})
    for k, m in sorun.items():
        if k not in aktif:
            gonder("⚠️ AEMonitoring: " + m); aktif[k] = simdi.isoformat(timespec="seconds")
    for k in list(aktif):
        if k not in sorun:
            gonder(f"✅ AEMonitoring: düzeldi ({k}, {zaman(aktif[k]):%H:%M}'den beri sürüyordu)."); aktif.pop(k)
    durum["aktif"], durum["kontrol"] = aktif, simdi.isoformat(timespec="seconds")
    json.dump(durum, open("n8n/uyari_durum.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
