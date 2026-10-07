"""Bildirim işleri — GitHub Actions, 15 dakikada bir (saha_uyari.yml). Konuya göre alıcı: n8n/bildirim_ayar.json.

  plan        yarının 24 saati Pi planında (cihaz_yonetimi_durum.json) belli olunca: grafik (PNG) + çalış/uyut saatleri
  pay         F2Pool dünün gelirini yazınca: BTC, 16/13 pay, çalışma, enerji, çalışmayan/eksik çalışan cihazlar
  cihaz       madenci 60 dk'dır ağda yok · bekçi onaramadı · takılı (hash 0) 60 dk
  ges_gunluk  her akşam 20:30'dan sonra: santral bazında üretim, inverter sayısı, üretmeyen/düşük inverter
  ges         gündüz üretmeyen inverter (30 dk), kritik santral uyarısı, FusionSolar kritik alarmı
  sistem      saha verisi gelmiyor (Pi/internet), cihaz yönetimi durdu, kaynak verisi alınamıyor, PTF yayınlanmadı
Anlık konularda her sorun başlayınca bir kez, düzelince bir kez haber verilir. Durum: n8n/bildirim_durum.json.
Elle deneme (gönderim yok, yalnız çıktı):  python bildirim_isler.py --kuru
"""
import json, math, os, statistics, subprocess, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone

import bildirim as B
from bildirim import TR, oku

KURU = "--kuru" in sys.argv
ORNEK = False          # panelden "örnek mesajlar" istenince: zaman/gönderildi kontrolleri atlanır
DURUM = "n8n/bildirim_durum.json"
RAW = "https://raw.githubusercontent.com/ekinciomer-ai/epias-ptf/main/"
DAG_BAS, DAG = "2026-09-14", (16, 13)
GUN = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
SANTRAL = {"Tek Yıldız-1 GES": "Sera-1", "Tek Yıldız-2 GES": "Sera-2", "Darilmaz Ges": "Darılmaz (YD)",
           "HG YATIRIM AŞ": "HG Yatırım (Anka)", "Aksaray_GES (AKS_Sapmaz)": "Aksaray (AE)"}
OSOS_YEDEK = {"Aksaray_GES (AKS_Sapmaz)": "AE", "Darilmaz Ges": "YD", "HG YATIRIM AŞ": "Anka", "Tek Yıldız-1 GES": "T1", "Tek Yıldız-2 GES": "T2"}
KAYNAK_AD = {"sungrow": "Sungrow (Darılmaz, HG)", "fusion": "FusionSolar (Sera-1/2)", "inavitas": "İnavitas (Aksaray)",
             "osos": "OSOS sayaçları", "epias": "EPİAŞ", "f2pool": "F2Pool"}
JTH = {"S21e Hyd": 17.5, "S19 XP+ Hyd": 21.5, "S19e XP Hyd": 34.5}


# ---------- yardımcılar ----------
def zaman(s):
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t.replace(tzinfo=TR) if t.tzinfo is None else t.astimezone(TR)


def tl(x, ondalik=0):
    s = f"{x:,.{ondalik}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def btc(x):
    return tl(x, 6) if x < 0.1 else tl(x, 4)


def isaret(x):
    return ("+" if x >= 0 else "−") + tl(abs(x))


def gun_ad(g):
    d = date.fromisoformat(g)
    return f"{d.day} {AY[d.month - 1]} {GUN[d.weekday()]}"


def gunes_saatleri(gun):
    n = gun.timetuple().tm_yday; g = 2 * math.pi / 365 * (n - 1)
    dek = 0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    la = math.radians(38.37)
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(dek)) - math.tan(la) * math.tan(dek)))
    og = (720 - 4 * 34.03 - eq) / 60 + 3
    return og - ha / 15, og + ha / 15


def araliklar(saatler):
    """[0,1,2,5,6] → '00–03 · 05–07'"""
    s = sorted(saatler); out = []; i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[j] + 1:
            j += 1
        out.append(f"{s[i]:02d}–{s[j] + 1:02d}"); i = j + 1
    return " · ".join(out) or "—"


def filo_kodlari():
    kim = oku("n8n/cihaz_kimlik.json", {}) or {}
    return kim, sorted(k for k, v in kim.items() if not v.get("not"))


def git_gonder(yollar, mesaj):
    if KURU:
        return True
    subprocess.run(["git", "config", "user.name", "aesun-bot"]); subprocess.run(["git", "config", "user.email", "aesun-bot@users.noreply.github.com"])
    subprocess.run(["git", "add", *yollar])
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return True
    subprocess.run(["git", "commit", "-qm", mesaj])
    for _ in range(4):
        if subprocess.run(["git", "pull", "--rebase", "--autostash", "-q"]).returncode == 0 and subprocess.run(["git", "push", "-q"]).returncode == 0:
            return True
        time.sleep(5)
    return False


def url_hazir(url, sure=90):
    t0 = time.time()
    while time.time() - t0 < sure:
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(6)
    return False


# ---------- anlık sorunlar (başlayınca / düzelince bir kez) ----------
class Sorunlar:
    def __init__(self, durum, simdi):
        self.d, self.simdi, self.gorulen, self.dondur = durum, simdi, {}, set()

    def var(self, anahtar, konu, metin, en_az_dk=0):
        """Koşul şu an var. en_az_dk boyunca kesintisiz sürerse bildirilir."""
        ilk = self.d.setdefault("aday", {}).setdefault(anahtar, self.simdi.isoformat(timespec="seconds"))
        if (self.simdi - zaman(ilk)) >= timedelta(minutes=en_az_dk):
            self.gorulen[anahtar] = (konu, metin)
        else:
            self.dondur.add(anahtar)          # aday: henüz bildirilmedi, ama aktifse düzelmiş sayılmasın

    def koru(self, onek):
        """Bu turda ölçülemeyen (ör. gece inverter) sorunları olduğu gibi bırak."""
        for k in list(self.d.get("aktif", {})):
            if k.startswith(onek):
                self.dondur.add(k)

    def bitir(self):
        aktif, aday = self.d.setdefault("aktif", {}), self.d.setdefault("aday", {})
        for k in list(aday):
            if k not in self.gorulen and k not in self.dondur:
                aday.pop(k)
        yeni, biten = {}, {}
        for k, (konu, m) in self.gorulen.items():
            if k not in aktif:
                aktif[k] = {"konu": konu, "bas": self.simdi.isoformat(timespec="seconds"), "metin": m}
                yeni.setdefault(konu, []).append(m)
        for k in list(aktif):
            if k not in self.gorulen and k not in self.dondur:
                a = aktif.pop(k)
                if isinstance(a, str):          # eski biçim (saha_uyari.py)
                    a = {"konu": "sistem", "bas": a, "metin": k}
                biten.setdefault(a["konu"], []).append(f"{a['metin'].split(' — ')[0]} ({zaman(a['bas']):%d.%m %H:%M}'den beri sürüyordu)")
        BAS = {"cihaz": "⛏️ Madenci", "ges": "☀️ GES", "sistem": "🖥️ Sistem"}
        for konu, l in yeni.items():
            B.gonder(konu, f"⚠️ *{BAS.get(konu, konu)} uyarısı*\n" + "\n".join("• " + x for x in l))
        for konu, l in biten.items():
            B.gonder(konu, f"✅ *{BAS.get(konu, konu)}: düzeldi*\n" + "\n".join("• " + x for x in l))


def sistem_ve_cihaz(S, simdi, durum):
    mad = oku("antminer_panel.json", {}) or {}
    pi_sessiz = False
    if mad.get("timestamp"):
        dk = (simdi - zaman(mad["timestamp"])).total_seconds() / 60
        if dk > 20:
            pi_sessiz = True
            S.var("pi_sessiz", "sistem", f"Saha verisi gelmiyor — son kayıt {zaman(mad['timestamp']):%H:%M}. Pi, modem ya da saha interneti kontrol edilmeli.")
    y = oku("n8n/cihaz_yonetimi_durum.json", {}) or {}
    if not pi_sessiz and y.get("guncellendi") and simdi - zaman(y["guncellendi"]) > timedelta(minutes=40):   # durum değişmezse Pi 30 dk'da bir yazar
        S.var("yonetim_durdu", "sistem", f"Cihaz yönetimi karar vermiyor — son karar {zaman(y['guncellendi']):%H:%M} (mod {y.get('mod')}).")
    son = oku("n8n/aesun_son.json", {}) or {}
    for r in son.get("son") or []:
        if (r.get("ardisik_hata") or 0) >= 4 and r.get("kaynak") in KAYNAK_AD:
            S.var("kaynak:" + r["kaynak"], "sistem", f"{KAYNAK_AD[r['kaynak']]} verisi alınamıyor — {r.get('ardisik_hata')} denemedir hata: {str(r.get('hata_mesaji') or '')[:80]}")
    # bekçi onaramadı (olay bazlı, bir kez)
    b = oku("n8n/bekci.json", {}) or {}
    son_b = durum.get("bekci_son", "")
    yeni = [o for o in b.get("olaylar") or [] if o.get("t", "") > son_b]
    kotu = [o for o in yeni if o.get("sonuc") == "BAŞARISIZ"]
    if kotu:
        B.gonder("cihaz", "⚠️ *⛏️ Bekçi onaramadı*\n" + "\n".join(f"• {o['cihaz']} ({o['ip']}): {o['olay']} — {o.get('ayrinti', '')}" for o in kotu) + "\nSahada bakılmalı.")
    if yeni:
        durum["bekci_son"] = max(o["t"] for o in yeni)
    if pi_sessiz:
        S.koru("cihaz:")                       # saha verisi yokken cihazlar hakkında hüküm verme
        return
    kim, kodlar = filo_kodlari()
    gorunen = set()
    for d in mad.get("devices") or []:
        if not (d.get("online") or d.get("sleeping")):
            continue
        w = str(d.get("actual_worker") or "").split(".")[-1]
        if not w:
            w = next((k for k, v in kim.items() if v.get("son_ip") == d.get("ip")), "")
        gorunen.add(w)
    for w in kodlar:
        if w not in gorunen:
            v = kim.get(w, {})
            S.var("cihaz:yok:" + w, "cihaz", f"{w} ağda yok — seri {v.get('serial', '?')}, son IP {v.get('son_ip', '?')}. Kapalı, kablosu çıkmış ya da IP değişmiş olabilir.", 60)
    det = oku("n8n/cihaz_detay.json", {}) or {}
    for s in ((det.get("bekci") or {}).get("sorunlu") or []):
        if s.get("sorun") == "takili" and (s.get("sure_dk") or 0) >= 60:
            S.var("cihaz:takili:" + s["cihaz"], "cihaz", f"{s['cihaz']} açık ama hash vermiyor ({s['sure_dk']} dk) — bekçi yeniden başlatmayı denedi.")
        elif s.get("sorun") == "takili":
            S.koru("cihaz:takili:" + s["cihaz"])


def ges_anlik(S, simdi, durum):
    dog, bat = gunes_saatleri(simdi.date())
    saat = simdi.hour + simdi.minute / 60
    son = oku("n8n/aesun_son.json", {}) or {}
    for u in son.get("uyarilar") or []:
        if u.get("seviye") == "kritik":
            S.var("ges:uyari:" + str(u.get("baslik"))[:60], "ges", f"{u.get('baslik')} — {u.get('detay', '')}"[:200])
    fs = oku("n8n/fusionsolar_son.json", {}) or {}
    for a in fs.get("alarmlar") or []:
        if any(x in str(a.get("seviye", "")).lower() for x in ("kritik", "critical", "major", "önemli")):
            S.var("ges:fsalarm:" + f"{a.get('cihaz')}|{a.get('alarm')}"[:80], "ges", f"FusionSolar alarmı: {a.get('alarm')} — {a.get('tesis', '')} {a.get('cihaz', '')}".strip())
    if not (dog + 1.5 <= saat <= bat - 1.5):
        S.koru("ges:inv:")
        return
    for r in son.get("son") or []:
        if r.get("kaynak") not in ("sungrow", "fusion", "inavitas"):
            continue
        invs = [i for i in r.get("inverterler") or [] if isinstance(i.get("guc_kw"), (int, float))]
        if len(invs) < 3:
            S.koru("ges:inv:" + r["ad"] + "|")
            continue
        med = statistics.median(i["guc_kw"] for i in invs)
        if med < 5:
            S.koru("ges:inv:" + r["ad"] + "|")
            continue
        ad = SANTRAL.get(r["ad"], r["ad"])
        for i in invs:
            if i["guc_kw"] <= 0.1:
                S.var("ges:inv:" + r["ad"] + "|" + str(i.get("ad")), "ges",
                      f"{ad} {i.get('ad')} üretmiyor — diğer inverterler ~{tl(med)} kW (seri {i.get('sn') or '?'})", 30)


# ---------- yarının planı ----------
def plan_grafik(gun, sat, dosya):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 15})
    fig, ax = plt.subplots(figsize=(10.8, 9.0), dpi=100)
    x = list(range(24))
    for s in sat:
        h = s["h"]
        renk = "#FFE9A8" if s["gunes"] else ("#D7F2DF" if s["calis"] else "#E6E9EE")
        ax.axvspan(h - 0.5, h + 0.5, color=renk, lw=0)
    ax.plot(x, [s["maliyet"] for s in sat], color="#D92D20", lw=4, marker="o", ms=6, label="Enerji maliyeti")
    ax.plot(x, [s["gelir"] for s in sat], color="#6D28D9", lw=4, ls="--", label="BTC geliri")
    ax.set_xlim(-0.5, 23.5)
    ax.set_xticks(range(0, 24, 2)); ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)])
    ax.set_ylabel("₺ / saat (tüm filo)")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: tl(v)))
    ax.grid(axis="y", color="#FFFFFF", lw=1.5)
    for k in ("top", "right"):
        ax.spines[k].set_visible(False)
    ust = max(max(s["maliyet"] for s in sat), max(s["gelir"] for s in sat))
    ax.set_ylim(0, ust * 1.18)
    for s in sat:                                           # her saatin üstünde karar harfi
        ax.text(s["h"], ust * 1.1, "G" if s["gunes"] else ("Ç" if s["calis"] else "U"), ha="center", va="center", fontsize=13,
                fontweight="bold", color="#9A6B00" if s["gunes"] else ("#1E7A3C" if s["calis"] else "#667085"))
    cs = sum(1 for s in sat if s["calis"])
    net = sum(s["gelir"] - s["maliyet"] for s in sat if s["calis"])
    fig.suptitle(f"{gun_ad(gun)} · {cs} saat çalış · net {isaret(net)} ₺", fontsize=22, fontweight="bold", x=0.03, ha="left", y=0.975)
    ax.set_title("Maliyet (kırmızı) gelirin (mor) üstündeyse cihazlar uyur; güneşte ve kısa aralarda çalışır", fontsize=13, color="#475467", loc="left", pad=12)
    ax.legend(handles=[Patch(color="#D7F2DF", label="Ç çalış"), Patch(color="#E6E9EE", label="U uyut"), Patch(color="#FFE9A8", label="G güneş (çalış)"),
                       Line2D([], [], color="#D92D20", lw=4, label="Enerji maliyeti"), Line2D([], [], color="#6D28D9", lw=4, ls="--", label="BTC geliri")],
              loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3, frameon=False, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    fig.savefig(dosya, facecolor="white")
    plt.close(fig)


def plan_isi(simdi, durum):
    yarin = (simdi + timedelta(days=1)).strftime("%Y-%m-%d")
    gd = durum.setdefault("gonderildi", {})
    if gd.get("plan") == yarin and not ORNEK:
        return
    y = oku("n8n/cihaz_yonetimi_durum.json", {}) or {}
    pl = {p["t"][11:13]: p for p in y.get("plan") or [] if p.get("t", "").startswith(yarin) and p.get("ptf") is not None and p.get("karar")}
    kaynak = "Pi planı"
    if len(pl) < 24:
        ep = oku("n8n/epias_gecmis.json", {}) or {}
        pt = (ep.get("ptf") or {}).get(yarin)
        # Pi verisi yoksa (saha kapalı) 17:00'den sonra aynı kuralla burada hesapla
        if not (pt and len(pt) == 24 and (ORNEK or (simdi.hour >= 17 and simdi - zaman(y.get("guncellendi", "2000-01-01")) > timedelta(minutes=30)))):
            if simdi.hour >= 17 and not (pt and len(pt) == 24) and gd.get("ptf_bekleme") != yarin:
                B.gonder("sistem", f"🕔 Yarının ({gun_ad(yarin)}) PTF'si hâlâ yayınlanmadı ({simdi:%H:%M}). Yayınlanınca plan gönderilecek.")
                gd["ptf_bekleme"] = yarin
            return
        a = y.get("ayarlar") or {}
        yk, kat, kw = y.get("yekdem") or 0, a.get("maliyet_carpani") or 1.035, a.get("cihaz_guc_kw") or 5.59
        gel = (y.get("hashprice_btc_th_gun") or 0) * (a.get("cihaz_th") or 285) / 24 * (y.get("btc_try") or 0)
        dog, bat = gunes_saatleri(date.fromisoformat(yarin))
        pi_pl, pl = pl, {}
        for h, p in enumerate(pt):
            gunes = (dog + 1.0) <= h and (h + 1) <= (bat - 1.0)
            m = (p + yk) / 1000 * kat * kw
            pl[f"{h:02d}"] = pi_pl.get(f"{h:02d}") or {"ptf": p, "maliyet": m, "gelir": gel, "karar": "calis" if gunes or gel >= m else "uyut", "gunes_tahmini": gunes}
        kaynak = "Pi planı" if len(pi_pl) == 24 else "kural (Pi verisi yok)" if not pi_pl else f"{len(pi_pl)} saat Pi planı, kalanı aynı kural"
    _, kodlar = filo_kodlari()
    n = len(kodlar) or 28
    sat = []
    for h in range(24):
        p = pl[f"{h:02d}"]
        sat.append({"h": h, "ptf": p["ptf"], "gunes": bool(p.get("gunes_tahmini")), "calis": p["karar"] == "calis",
                    "kisa": p["karar"] == "calis" and p.get("karar_ham") == "uyut" and not p.get("gunes_tahmini"),
                    "maliyet": p["maliyet"] * n, "gelir": p["gelir"] * n})
    cal = [s["h"] for s in sat if s["calis"]]
    uyu = [s["h"] for s in sat if not s["calis"]]
    gun_ = [s["h"] for s in sat if s["gunes"]]
    gelir = sum(s["gelir"] for s in sat if s["calis"]); enerji = sum(s["maliyet"] for s in sat if s["calis"])
    kacinilan = sum(s["maliyet"] - s["gelir"] for s in sat if not s["calis"])
    ptfs = [s["ptf"] for s in sat]
    metin = (f"📅 *Yarın {gun_ad(yarin)} — plan*\n"
             f"✅ Çalış: {araliklar(cal)} ({len(cal)} saat)\n"
             f"😴 Uyut: {araliklar(uyu)} ({len(uyu)} saat)\n"
             + (f"☀️ Güneş: {araliklar(gun_)}\n" if gun_ else "")
             + f"💰 Beklenen net: *{isaret(gelir - enerji)} ₺* (gelir {tl(gelir)} − enerji {tl(enerji)})\n"
             + (f"ℹ️ {araliklar([s['h'] for s in sat if s['kisa']])}: maliyet biraz yüksek ama kısa uyku + yeniden ısınma daha pahalı, çalışmaya devam\n" if any(s["kisa"] for s in sat) else "")
             + (f"🛡️ Uyutarak kaçınılan zarar: {tl(kacinilan)} ₺\n" if kacinilan > 0 else "")
             + f"PTF ort. {tl(sum(ptfs) / 24)} (en düşük {tl(min(ptfs))}, en yüksek {tl(max(ptfs))}) · filo {n} cihaz"
             + ("" if kaynak == "Pi planı" else f"\n_{kaynak}_"))
    gorsel = None
    try:
        os.makedirs("n8n/wp", exist_ok=True)
        yol = f"n8n/wp/plan_{yarin}.png"
        plan_grafik(yarin, sat, yol)
        if KURU:
            print("grafik:", yol)
        elif git_gonder([yol], f"Plan grafiği {yarin}") and url_hazir(RAW + yol):
            gorsel = RAW + yol
    except Exception as e:
        print("grafik hatası:", e)
    B.gonder("plan", metin, gorsel)
    gd["plan"] = yarin


# ---------- madencilik günlük raporu ve pay ----------
def gun_saatleri_utc(g):
    d0 = datetime.fromisoformat(g + "T00:00").replace(tzinfo=TR)
    return [(d0 + timedelta(hours=h)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00") for h in range(24)]


def pay_isi(simdi, durum):
    gel = oku("arsiv_f2pool_gelir.json", {}) or {}
    gunler = sorted(g for g in gel if len(g) == 10 and g[:2] == "20" and g >= DAG_BAS and (gel[g] or {}).get("btc") is not None)
    gd = durum.setdefault("gonderildi", {})
    if not gunler:
        return
    if ORNEK:
        gd["pay"] = gunler[-2] if len(gunler) > 1 else ""
    elif not gd.get("pay"):
        gd["pay"] = gunler[-2] if len(gunler) > 1 else gunler[-1]   # ilk çalıştırmada yalnız en son günü gönder
    bek = [g for g in gunler if g > gd["pay"]]
    if not bek:
        return
    g = bek[0]
    r = gel[g]
    fy = (oku("arsiv_btc_fiyat.json", {}) or {}).get("gun", {}).get(g) or {}
    y = oku("n8n/cihaz_yonetimi_durum.json", {}) or {}
    ftry = fy.get("try") or y.get("btc_try") or 0
    fusd = fy.get("usd") or 0
    # cihaz saatlik (F2Pool arşivi, UTC anahtar)
    ay_dosya = {}
    sat = []
    for k in gun_saatleri_utc(g):
        a = ay_dosya.get(k[:7])
        if a is None:
            a = ay_dosya[k[:7]] = oku(f"arsiv_cihaz_{k[:7]}.json", {}) or {}
        sat.append({c: (v or {}).get("h") or 0 for c, v in (a.get(k) or {}).items()})
    veri = sum(1 for o in sat if o)
    calisan = [o for o in sat if sum(o.values()) > 0]
    kim, kodlar = filo_kodlari()
    s_cihaz = {c: sum(1 for o in calisan if o.get(c, 0) > 0) for c in set(kodlar) | {c for o in sat for c in o}}
    ort_h = {c: (sum(o.get(c, 0) for o in calisan if o.get(c, 0) > 0) / s_cihaz[c]) if s_cihaz[c] else 0 for c in s_cihaz}
    n_eff = (sum(s_cihaz.values()) / len(calisan)) if calisan else 0
    # enerji: Pi'nin saatlik ölçümü varsa o, yoksa hash × model verimi
    ss = (oku("n8n/saha_saatlik.json", {}) or {}).get("saat") or {}
    ep = oku("n8n/epias_gecmis.json", {}) or {}
    ptf = (ep.get("ptf") or {}).get(g) or []
    ykd = ((ep.get("yekdem") or {}).get(g[:7]) or {})
    yk = ykd.get("gercek") or ykd.get("ongoru") or y.get("yekdem") or 0
    kat = (y.get("ayarlar") or {}).get("maliyet_carpani") or 1.035
    enerji, kwh, kaynak = None, 0, ""
    if len(ptf) == 24:
        pi_s = [ss.get(f"{g} {h:02d}") for h in range(24)]
        if sum(1 for x in pi_s if x) >= 20:
            kws = [(x or {}).get("kw") or 0 for x in pi_s]; kaynak = "saha ölçümü"
        elif veri >= 20:
            kws = [sum(v * JTH.get((kim.get(c) or {}).get("model"), 17.5) / 1000 for c, v in o.items() if v > 0) for o in sat]; kaynak = "hash × verim"
        else:
            kws = None
        if kws:
            kwh = sum(kws)
            enerji = sum(k * (p + yk) / 1000 * kat for k, p in zip(kws, ptf))
    gelir_tl = r["btc"] * ftry
    a_, b_ = r["btc"] * DAG[0] / sum(DAG), r["btc"] * DAG[1] / sum(DAG)
    # ay toplamı (dağılım başlangıcından itibaren)
    ay_g = [x for x in gunler if x[:7] == g[:7] and x <= g]
    fyt = (oku("arsiv_btc_fiyat.json", {}) or {}).get("gun", {})
    ay_btc = sum(gel[x]["btc"] for x in ay_g)
    ay_tl = sum(gel[x]["btc"] * ((fyt.get(x) or {}).get("try") or ftry) for x in ay_g)
    # cihaz sorunları
    notlar = []
    model_med = {}
    for c, v in ort_h.items():
        m = (kim.get(c) or {}).get("model")
        if v > 0 and m:
            model_med.setdefault(m, []).append(v)
    model_med = {m: statistics.median(l) for m, l in model_med.items()}
    hs = len(calisan)
    for c in sorted(kodlar):
        s = s_cihaz.get(c, 0)
        if hs and s == 0:
            notlar.append(f"🔴 {c}: hiç çalışmadı")
        elif hs and s < 0.75 * hs:
            notlar.append(f"🟠 {c}: {s}/{hs} saat çalıştı")
        else:
            m = (kim.get(c) or {}).get("model"); med = model_med.get(m)
            if med and ort_h.get(c) and ort_h[c] < 0.85 * med:
                notlar.append(f"🟡 {c}: hash düşük (%{ort_h[c] / med * 100:.0f}, {tl(ort_h[c])} TH/s)")
    for c, v in sorted(kim.items()):
        if v.get("not"):
            notlar.append(f"⚪ {c}: {v['not']}")
    bek_ol = [o for o in (oku("n8n/bekci.json", {}) or {}).get("olaylar") or [] if o.get("t", "").startswith(g) and o.get("olay") != "düzeldi"]
    metin = (f"⛏️ *Madencilik — {gun_ad(g)}*\n"
             f"Gelir: *{btc(r['btc'])} BTC* ≈ {tl(gelir_tl)} ₺" + (f" (${tl(r['btc'] * fusd)})" if fusd else "") + "\n"
             + (f"Enerji ({kaynak}, PTF+YEKDEM): {tl(enerji)} ₺ · {tl(kwh)} kWh\nNet: *{isaret(gelir_tl - enerji)} ₺*\n" if enerji is not None else "")
             + f"Çalışma: {hs} saat · ort. {tl(n_eff, 1)} cihaz · {tl(r.get('hash_rate') or 0)} TH/s (24 saat ort.)\n"
             f"\n*Pay dağılımı*\n"
             f"• 16 cihaz: {btc(a_)} BTC ≈ {tl(a_ * ftry)} ₺\n"
             f"• 13 cihaz: {btc(b_)} BTC ≈ {tl(b_ * ftry)} ₺\n"
             f"{AY[int(g[5:7]) - 1]} toplamı ({len(ay_g)} gün): {btc(ay_btc)} BTC ≈ {tl(ay_tl)} ₺ → 16: {btc(ay_btc * 16 / 29)} · 13: {btc(ay_btc * 13 / 29)}\n"
             f"\n*Cihazlar* ({len(kodlar)} cihaz)\n"
             + ("\n".join(notlar) if notlar else "✅ Hepsi çalıştığı saatlerde tam çalıştı")
             + (f"\n🔧 Bekçi: {len(bek_ol)} işlem (" + ", ".join(f"{o['cihaz']} {o['olay'].split(' (')[0]} {'✓' if o.get('sonuc') == 'ok' else '✗'}" for o in bek_ol[:5]) + ")" if bek_ol else "")
             + ("" if veri >= 20 else f"\n_F2Pool saatlik verisi eksik ({veri}/24 saat)_"))
    B.gonder("pay", metin)
    gd["pay"] = g


# ---------- GES günlük ----------
def ges_gunluk_isi(simdi, durum):
    gd = durum.setdefault("gonderildi", {})
    bugun = simdi.strftime("%Y-%m-%d")
    if ORNEK:
        bugun = (simdi - timedelta(hours=6)).strftime("%Y-%m-%d")
    elif gd.get("ges_gunluk") == bugun or (simdi.hour, simdi.minute) < (20, 30):
        return
    son = oku("n8n/aesun_son.json", {}) or {}
    osos = {r["ad"]: r.get("gunluk_kwh") for r in son.get("son") or [] if r.get("kaynak") == "osos"}
    sat, top, sorun = [], 0, []
    for r in son.get("son") or []:
        if r.get("kaynak") not in ("sungrow", "fusion", "inavitas"):
            continue
        ad = SANTRAL.get(r["ad"], r["ad"])
        kwh = r.get("gunluk_kwh")
        not_ = ""
        if not kwh and osos.get(OSOS_YEDEK.get(r["ad"])):
            kwh, not_ = osos[OSOS_YEDEK[r["ad"]]], " (sayaç)"
        invs = r.get("inverterler") or []
        olc = [i for i in invs if isinstance(i.get("gunluk_kwh"), (int, float))]
        ek = r.get("ek") or {}
        kwp = f" · {tl(ek['kwh_kwp'], 2)} kWh/kWp" if isinstance(ek.get("kwh_kwp"), (int, float)) else ""
        if olc:
            med = statistics.median(i["gunluk_kwh"] for i in olc)
            ureten = [i for i in olc if i["gunluk_kwh"] > 0]
            inv = f" · {len(ureten)}/{len(invs)} inverter"
            for i in olc:
                if med > 50 and i["gunluk_kwh"] <= 0.5:
                    sorun.append(f"🔴 {ad} {i.get('ad')}: üretmedi")
                elif med > 50 and i["gunluk_kwh"] < 0.7 * med:
                    sorun.append(f"🟠 {ad} {i.get('ad')}: {tl(i['gunluk_kwh'])} kWh (diğerlerinin %{i['gunluk_kwh'] / med * 100:.0f}'i)")
        else:
            inv = f" · {len(invs)} inverter" if invs else ""
        top += kwh or 0
        sat.append(f"• {ad}: {tl(kwh) if kwh else '—'} kWh{not_}{kwp}{inv}")
    if not sat:
        return
    metin = (f"☀️ *GES — {gun_ad(bugun)}*\nToplam: *{tl(top)} kWh*\n" + "\n".join(sat)
             + ("\n\n" + "\n".join(sorun) if sorun else "\n✅ Tüm inverterler normal üretti"))
    B.gonder("ges_gunluk", metin)
    gd["ges_gunluk"] = bugun


# ---------- test mesajı (panelden kişi eklenince) ----------
def test_isi(durum):
    ay = B.ayar()
    istek = ay.get("test") or []
    if not istek:
        return False
    ad = {k["id"]: k["ad"] for k in ay.get("konular") or []}
    for k in ay.get("kisiler") or []:
        if k["anahtar"] in istek:
            l = k.get("konular") or []
            B.gonder("test", "👋 *AEMonitoring bildirim testi*\nBu numaraya şu konularda mesaj gelecek:\n"
                     + ("\n".join("• " + ad.get(x, x) for x in l) if l else "• (konu seçilmemiş)"), kisiler=[k])
    kalan = [x["anahtar"] for x in ((oku(B.KAYIT, {}) or {}).get("kayit") or [])[-len(istek) * 2:]
             if x.get("konu") == "test" and x.get("kod") in (63038, 63018)]       # sınır doldu: sonra tekrar dene
    ay["test"] = sorted(set(kalan))
    if not KURU:
        json.dump(ay, open(B.AYAR, "w"), ensure_ascii=False, indent=1)
    return True


def ornek_isi(simdi):
    """bildirim_ayar.json "ornek": [anahtar...] → o kişilere tüm konuların örnek mesajı (durum değişmez)."""
    global ORNEK
    import copy
    ay = B.ayar()
    hedef = [k for k in ay.get("kisiler") or [] if k["anahtar"] in (ay.get("ornek") or [])]
    if not hedef:
        return
    ORNEK = True
    asil = B.gonder
    B.gonder = lambda konu, metin, gorsel=None, kisiler=None: asil(konu, "🧪 *ÖRNEK* (" + konu + ")\n" + metin, gorsel, hedef)
    try:
        B.gonder("bilgi", "Aşağıda her konunun gerçek verilerle hazırlanmış örnek mesajı var. Anlık uyarılar (madenci, GES, sistem) yalnız sorun olunca gelir; örnekleri temsilidir.")
        d = copy.deepcopy(oku(DURUM) or {})
        for f, t in ((plan_isi, simdi - timedelta(days=1)), (pay_isi, simdi), (ges_gunluk_isi, simdi)):
            try:
                f(t, d)        # plan: yarınınki yoksa bugünün planı örnek gösterilir
            except Exception as e:
                import traceback; traceback.print_exc()
        B.gonder("cihaz", "⚠️ *⛏️ Madenci uyarısı*\n• 012 ağda yok — seri OLTTGBUBEAAAA00XX, son IP 192.168.0.108. Kapalı, kablosu çıkmış ya da IP değişmiş olabilir.")
        B.gonder("cihaz", "✅ *⛏️ Madenci: düzeldi*\n• 012 ağda yok (08.10 14:20'den beri sürüyordu)")
        B.gonder("ges", "⚠️ *☀️ GES uyarısı*\n• Sera-1 Inverter 4 üretmiyor — diğer inverterler ~85 kW")
        B.gonder("sistem", "⚠️ *🖥️ Sistem uyarısı*\n• Saha verisi gelmiyor — son kayıt 14:05. Pi, modem ya da saha interneti kontrol edilmeli.")
    finally:
        B.gonder, ORNEK = asil, False
    ay["ornek"] = []
    if not KURU:
        json.dump(ay, open(B.AYAR, "w"), ensure_ascii=False, indent=1)


def main():
    simdi = datetime.now(TR)
    if KURU:
        B._kayit = lambda o: None
        B._client = lambda: None
        if os.environ.get("SIMDI"):
            simdi = datetime.fromisoformat(os.environ["SIMDI"]).replace(tzinfo=TR)
    durum = oku(DURUM) or {}
    if not durum and oku("n8n/uyari_durum.json"):          # saha_uyari.py'den devral
        e = oku("n8n/uyari_durum.json")
        durum = {"aktif": {k: {"konu": "sistem", "bas": v, "metin": k} for k, v in (e.get("aktif") or {}).items()}, "bekci_son": e.get("bekci_son", "")}
    S = Sorunlar(durum, simdi)
    for ad, f in (("sistem/cihaz", lambda: sistem_ve_cihaz(S, simdi, durum)), ("ges", lambda: ges_anlik(S, simdi, durum))):
        try:
            f()
        except Exception as e:
            print(ad, "hatası:", e)
    S.bitir()
    for ad, f in (("plan", plan_isi), ("pay", pay_isi), ("ges_gunluk", ges_gunluk_isi)):
        if not (8 <= simdi.hour < 22):        # raporlar gece gönderilmez (anlık uyarılar her saat)
            break
        try:
            f(simdi, durum)
        except Exception as e:
            import traceback; traceback.print_exc(); print(ad, "hatası:", e)
    try:
        ornek_isi(simdi)
    except Exception as e:
        print("örnek hatası:", e)
    try:
        test_isi(durum)
    except Exception as e:
        print("test hatası:", e)
    B.teslim_kontrol()
    durum["kontrol"] = simdi.isoformat(timespec="seconds")
    if not KURU:
        json.dump(durum, open(DURUM, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
