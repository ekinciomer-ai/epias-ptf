"""
OSOS ENDEKS TAKIP - Excel Tabanli (v3)
=======================================
Her saat xx:05'te calisir:
  1. OSOS Load Profile sayfasini ac
  2. Her 3 tesisat icin:
     - Tesisat sec
     - "Son 2 Gun" tarih araligi
     - Filtrele
     - Islemler -> Excel'e aktar
     - Popup'ta xlsx linkine tikla -> indir
     - Parse: saatlik fark x carpan = kWh
  3. JSON'a yaz, GitHub'a push

Avantajlari:
  - HTML tablo scraping yok (kolon sirasi sasmaz)
  - Anomali olmaz (Excel temiz veri)
  - Veri eksik olsa bile sonraki cekisle telafi olur
"""

import json
import logging
import os
import sqlite3
import sys
import time
import urllib.request
import base64
from datetime import datetime, timedelta
from collections import defaultdict

import schedule
import openpyxl
from playwright.sync_api import sync_playwright

# ═══════════════════════════════════════════════════════
# KONFIGURASYON
# ═══════════════════════════════════════════════════════
OSOS_URL = "https://osos.meramedas.com.tr"
OTURUM_DOSYA = "oturum.json"
INDIRME_KLASORU = os.path.abspath(".")

ABONELIKLER = [
    {
        "ad": "Tekyildiz Saglik 1",
        "json_key": "tekyildiz_1",
        "tesisat_no": "11116344",
        "carpan": 1890.0,
    },
    {
        "ad": "Tekyildiz Saglik 2",
        "json_key": "tekyildiz_2",
        "tesisat_no": "11116968",
        "carpan": 1890.0,
    },
    {
        "ad": "Aksaray Enerji 3",
        "json_key": "aksaray_3",
        "tesisat_no": "11200108",
        "carpan": 3150.0,
    },
]

LOG_DOSYASI = "osos_log.txt"

# === GITHUB ===
GH_TOKEN  = os.environ.get("GH_TOKEN", "")
GH_REPO   = os.environ.get("GH_REPO", "ekinciomer-ai/epias-ptf")
GH_DOSYA  = "2026_osos_endeks.json"
GH_ENABLED = bool(GH_TOKEN)

# === OSOS OTOMATIK LOGIN ===
OSOS_KULLANICI = os.environ.get("OSOS_KULLANICI", "")
OSOS_SIFRE     = os.environ.get("OSOS_SIFRE", "")

# ═══════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DOSYASI, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# YARDIMCI FONKSIYONLAR
# ═══════════════════════════════════════════════════════
def tr_float(s):
    """OSOS Excel'den gelen sayisal degeri float'a cevirir.
    Hem '0.091' (Excel) hem '0,091' (HTML) formatlarini destekler.
    """
    if s is None: return 0.0
    if isinstance(s, (int, float)): return float(s)
    s = str(s).strip().replace(" ", "")
    if not s: return 0.0
    try:
        n, v = s.rfind("."), s.rfind(",")
        if n == -1 and v == -1: return float(s)
        if v > n: return float(s.replace(".", "").replace(",", "."))
        return float(s.replace(",", ""))
    except:
        return 0.0


# ═══════════════════════════════════════════════════════
# GITHUB JSON OKU/YAZ
# ═══════════════════════════════════════════════════════
def github_oku():
    """2026_osos_endeks.json'i GitHub'dan oku."""
    if not GH_ENABLED:
        log.warning("GH_TOKEN tanimli degil")
        return None
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_DOSYA}"
    log.info("  GitHub okuma: %s", url)
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log.info("2026_osos_endeks.json GitHub'da yok, yenisi olusturulacak")
            return {}, None
        log.warning("GitHub oku HTTPError: %s %s", e.code, e.reason)
        try:
            body = e.read().decode()[:300]
            log.warning("  Detay: %s", body)
        except:
            pass
        return None
    except Exception as e:
        log.warning("GitHub oku hatasi: %s", e)
        return None


def github_yaz(data, sha=None):
    """2026_osos_endeks.json'i GitHub'a yaz."""
    if not GH_ENABLED:
        log.info("GH_TOKEN yok, push atlandi")
        return False
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_DOSYA}"
    icerik_str = json.dumps(data, ensure_ascii=False, indent=2)
    icerik_b64 = base64.b64encode(icerik_str.encode("utf-8")).decode("ascii")
    
    payload = {
        "message": f"OSOS endeks guncellemesi {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": icerik_b64
    }
    if sha:
        payload["sha"] = sha
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="PUT",
        headers={
            "Authorization": f"token {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            log.info("GitHub push BASARILI: %s", GH_DOSYA)
            return True
    except Exception as e:
        log.error("GitHub yaz hatasi: %s", e)
        return False


# ═══════════════════════════════════════════════════════
# OTURUM YONETIMI
# ═══════════════════════════════════════════════════════
def manuel_giris_ve_kaydet():
    print("\n" + "="*60)
    print("MANUEL GIRIS MODU")
    print("Tarayici acilacak. Giris yapip ana sayfaya gelin.")
    print("="*60 + "\n")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto(OSOS_URL + "/", timeout=30000)
        input("Giris yapip ENTER basin...")
        cookies = context.cookies()
        with open(OTURUM_DOSYA, "w", encoding="utf-8") as f:
            json.dump(cookies, f)
        log.info("Oturum kaydedildi: %d cookie", len(cookies))
        browser.close()


def otomatik_giris():
    """OSOS_KULLANICI ve OSOS_SIFRE ile headless tarayicidan otomatik giris."""
    if not OSOS_KULLANICI or not OSOS_SIFRE:
        log.error("OTOMATIK GIRIS YAPILAMADI: OSOS_KULLANICI veya OSOS_SIFRE env tanimli degil")
        return False
    
    log.info("Otomatik giris deneniyor...")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.goto(OSOS_URL + "/", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            
            try:
                page.fill('input[name="UserName"], input#UserName', OSOS_KULLANICI, timeout=8000)
                page.fill('input[name="Password"], input#Password', OSOS_SIFRE)
                page.click('button[type="submit"], input[type="submit"]', timeout=5000)
            except Exception:
                page.fill('input[type="text"]', OSOS_KULLANICI, timeout=8000)
                page.fill('input[type="password"]', OSOS_SIFRE)
                page.keyboard.press("Enter")
            
            page.wait_for_load_state("networkidle", timeout=20000)
            page.wait_for_timeout(2000)
            
            if "WiringDashboard" in page.url or "MainPage" in page.url or "Home" in page.url:
                cookies = context.cookies()
                with open(OTURUM_DOSYA, "w", encoding="utf-8") as f:
                    json.dump(cookies, f)
                log.info("Otomatik giris BASARILI: %d cookie kaydedildi", len(cookies))
                browser.close()
                return True
            else:
                log.error("Otomatik giris BASARISIZ: URL=%s", page.url)
                browser.close()
                return False
    except Exception as e:
        log.error("Otomatik giris hatasi: %s", e)
        return False


def oturum_yukle(context):
    try:
        with open(OTURUM_DOSYA, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        context.add_cookies(cookies)
        log.info("Oturum yuklendi: %d cookie", len(cookies))
        return True
    except FileNotFoundError:
        log.error("Oturum dosyasi yok!")
        return False


def oturum_gecerli_mi(page):
    page.goto(OSOS_URL + "/WiringDashboard/Index", timeout=20000)
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(1500)
    return "Login" not in page.url and "Account" not in page.url


# ═══════════════════════════════════════════════════════
# EXCEL INDIRME (TEK TESISAT)
# ═══════════════════════════════════════════════════════
def excel_indir(page, abone):
    """OSOS Load Profile sayfasindan abone icin Son 2 Gun Excel'ini indirir.
    Donus: indirilen Excel'in tam yolu, veya None.
    """
    tesisat = abone["tesisat_no"]
    log.info("  Excel indiriliyor: %s (%s)", abone["ad"], tesisat)
    
    # Load Profile sayfasina git
    page.goto(OSOS_URL + "/LoadProfile/Index", timeout=30000)
    page.wait_for_load_state("networkidle", timeout=20000)
    page.wait_for_timeout(3000)
    
    # Tesisat sec
    try:
        page.click('span[aria-labelledby="select2-Wiring_Id-container"]', timeout=8000)
        page.wait_for_timeout(800)
        page.fill('input.select2-search__field', tesisat)
        page.wait_for_timeout(1500)
        page.click(f'li.select2-results__option:has-text("{tesisat}")', timeout=5000)
        page.wait_for_timeout(800)
    except Exception as e:
        log.error("  Tesisat secimi hatasi: %s", e)
        return None
    
    # "Son 2 Gun" tarih araligi
    try:
        page.click("input#ProfileDateTime")
        page.wait_for_timeout(1000)
        page.click('li[data-range-key="Son 2 Gün"], li:has-text("Son 2 Gün")', timeout=5000)
        page.wait_for_timeout(1000)
    except Exception as e:
        log.error("  Son 2 Gun secimi hatasi: %s", e)
        return None
    
    # Filtrele
    try:
        page.click('button:has-text("Filtrele")', timeout=5000)
    except:
        page.keyboard.press("Enter")
    page.wait_for_load_state("networkidle", timeout=20000)
    page.wait_for_timeout(3000)
    
    # ISLEMLER butonu - HOVER yap (tıklama değil)
    islemler_bulundu = False
    for b in page.locator('button:visible, a:visible').all():
        try:
            t = b.inner_text().strip().upper()
            if t in ("ISLEMLER", "İSLEMLER", "İŞLEMLER"):
                b.hover()  # Hover yapinca menu acilir
                islemler_bulundu = True
                log.info("  ISLEMLER hover yapildi")
                break
        except:
            continue
    
    if not islemler_bulundu:
        log.error("  ISLEMLER butonu bulunamadi!")
        return None
    
    page.wait_for_timeout(1500)
    
    # Disa Aktar - HOVER yap (alt menu acmak icin)
    try:
        disa_aktar = page.locator(':text("Dışa Aktar")').first
        disa_aktar.hover()
        page.wait_for_timeout(1500)
        log.info("  Disa Aktar hover yapildi")
    except Exception as e:
        log.warning("  Disa Aktar hover hatasi: %s", e)
    
    # Excel'e aktar - JavaScript ile direkt click (gorunur olmasa bile)
    try:
        # Once element var mi kontrol et
        excel_btn = page.locator('a#excelExport-datatable-table-1').first
        if excel_btn.count() == 0:
            excel_btn = page.locator('a[id^="excelExport"]').first
        
        # JavaScript ile click - visibility kontrolu yok
        page.evaluate("""
            (() => {
                const btn = document.querySelector('a#excelExport-datatable-table-1') 
                         || document.querySelector('a[id^="excelExport"]');
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            })()
        """)
        page.wait_for_timeout(2000)
        log.info("  Excel'e aktar JS click yapildi")
    except Exception as e:
        log.error("  Excel'e aktar bulunamadi: %s", e)
        return None
    
    # Popup'taki .xlsx linkini bekle (120 saniye)
    log.info("  Popup link bekleniyor...")
    excel_path = None
    
    for i in range(60):
        try:
            # Strateji 1: a[href*=".xlsx"]
            for sel in ['a[href*=".xlsx"]', '.toast a', '.notification a', '.alert a',
                       'a:has-text(".xlsx")', 'button:has-text(".xlsx")']:
                try:
                    locator = page.locator(sel).first
                    if locator.count() > 0:
                        with page.expect_download(timeout=15000) as dl_info:
                            locator.click(force=True)
                        download = dl_info.value
                        excel_path = os.path.join(
                            INDIRME_KLASORU,
                            f"osos_{tesisat}.xlsx"
                        )
                        download.save_as(excel_path)
                        log.info("  INDIRILDI: %s", excel_path)
                        return excel_path
                except:
                    continue
            
            # Strateji 2: text icinde .xlsx olan parent'in <a>'sini bul
            if i > 5:
                elems = page.locator(':has-text(".xlsx")').all()
                for e in elems[:5]:
                    try:
                        ic_a = e.locator('a').all()
                        for a in ic_a:
                            try:
                                with page.expect_download(timeout=10000) as dl_info:
                                    a.click(force=True)
                                download = dl_info.value
                                excel_path = os.path.join(
                                    INDIRME_KLASORU,
                                    f"osos_{tesisat}.xlsx"
                                )
                                download.save_as(excel_path)
                                log.info("  INDIRILDI (parent): %s", excel_path)
                                return excel_path
                            except:
                                continue
                    except:
                        continue
        except:
            pass
        
        time.sleep(2)
        if i % 10 == 0 and i > 0:
            log.info("  ... %d/%d saniye", i*2, 60*2)
    
    log.error("  Excel link bulunamadi (timeout)")
    return None


# ═══════════════════════════════════════════════════════
# EXCEL PARSE -> SAATLIK AGREGE
# ═══════════════════════════════════════════════════════
def excel_parse(excel_path, abone):
    """Excel'i okur, saatlik cekis_fark ve veris_fark toplamlarini doner.
    Donus: dict {saat_dt: {"cekis_kwh": x, "veris_kwh": y}}
    """
    sonuc = {}
    try:
        wb = openpyxl.load_workbook(excel_path, read_only=False)
        ws = wb.active
        
        saatlik = defaultdict(lambda: {"c": 0.0, "v": 0.0, "n": 0})
        
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or row[0] is None:
                continue
            try:
                if isinstance(row[0], datetime):
                    dt = row[0]
                else:
                    dt = datetime.strptime(str(row[0]).strip(), "%d.%m.%Y %H:%M:%S")
            except:
                continue
            
            saat_dt = dt.replace(minute=0, second=0, microsecond=0)
            c = tr_float(row[2]) if len(row) > 2 else 0
            v = tr_float(row[4]) if len(row) > 4 else 0
            saatlik[saat_dt]["c"] += c
            saatlik[saat_dt]["v"] += v
            saatlik[saat_dt]["n"] += 1
        
        wb.close()
        
        # carpan uygula
        carpan = abone["carpan"]
        for saat_dt, d in saatlik.items():
            sonuc[saat_dt] = {
                "cekis_kwh": round(d["c"] * carpan, 3),
                "veris_kwh": round(d["v"] * carpan, 3),
                "periyot": d["n"]
            }
        
        log.info("  Parse: %d saat, toplam %.2f cekis kWh, %.2f veris kWh",
                 len(sonuc),
                 sum(d["cekis_kwh"] for d in sonuc.values()),
                 sum(d["veris_kwh"] for d in sonuc.values()))
        return sonuc
    except Exception as e:
        log.error("  Excel parse hatasi: %s", e, exc_info=True)
        return {}


# ═══════════════════════════════════════════════════════
# JSON GUNCELLEME
# ═══════════════════════════════════════════════════════
def json_guncelle(abone, saatlik_veri):
    """Saatlik veriyi 2026_osos_endeks.json'a yazar (GitHub'da)."""
    if not saatlik_veri:
        return False
    
    # Mevcut JSON oku
    result = github_oku()
    if result is None:
        log.error("  GitHub okuma basarisiz, json guncellenmedi")
        return False
    
    data, sha = result
    if data is None:
        data = {}
    
    json_key = abone["json_key"]
    if json_key not in data:
        data[json_key] = {
            "tesisat_no": abone["tesisat_no"],
            "carpan": abone["carpan"],
            "veri": {}
        }
    
    eklenen = 0
    for saat_dt, d in saatlik_veri.items():
        tarih_str = saat_dt.strftime("%Y-%m-%d")
        # Saat anahtari "00", "01", ..., "23" (frontend'in bekledigi format)
        saat_str = f"{saat_dt.hour:02d}"
        
        if tarih_str not in data[json_key]["veri"]:
            data[json_key]["veri"][tarih_str] = {}
        
        # Frontend cekis/veris bekliyor (cekis_kwh degil)
        data[json_key]["veri"][tarih_str][saat_str] = {
            "cekis": d["cekis_kwh"],
            "veris": d["veris_kwh"]
        }
        eklenen += 1
    
    # GitHub'a yaz
    if github_yaz(data, sha):
        log.info("  JSON guncellendi: %s (%d saat eklendi/guncellendi)", json_key, eklenen)
        return True
    return False


# ═══════════════════════════════════════════════════════
# ANA FONKSIYON
# ═══════════════════════════════════════════════════════
def tum_aboneleri_oku():
    """3 abone icin Excel indir + parse + GitHub'a yaz."""
    log.info("==== Excel Tabanli Veri Cekimi ====")
    
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                accept_downloads=True
            )
            
            if not oturum_yukle(context):
                browser.close()
                if otomatik_giris():
                    log.info("Otomatik giris yapildi, tekrar deneniyor...")
                    return tum_aboneleri_oku()
                else:
                    log.error("Otomatik giris basarisiz!")
                    return
            
            page = context.new_page()
            
            if not oturum_gecerli_mi(page):
                log.warning("Oturum dolmus, otomatik giris deneniyor...")
                browser.close()
                if otomatik_giris():
                    return tum_aboneleri_oku()
                else:
                    log.error("Otomatik giris basarisiz!")
                    return
            
            log.info("Oturum gecerli.")
            
            for abone in ABONELIKLER:
                log.info("-> %s", abone["ad"])
                try:
                    excel_path = excel_indir(page, abone)
                    if excel_path and os.path.exists(excel_path):
                        saatlik = excel_parse(excel_path, abone)
                        if saatlik:
                            json_guncelle(abone, saatlik)
                except Exception as e:
                    log.error("  Hata [%s]: %s", abone["ad"], e, exc_info=True)
                time.sleep(3)
            
            browser.close()
    except Exception as e:
        log.error("Genel hata: %s", e, exc_info=True)
    
    log.info("==== Cekim Tamamlandi ====\n")


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════
def github_token_test():
    """GitHub token'in gercekten gecerli olup olmadigini test eder."""
    if not GH_ENABLED:
        return False
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={"Authorization": f"token {GH_TOKEN}"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            log.info("GitHub token GECERLI - kullanici: %s", data.get("login"))
            return True
    except urllib.error.HTTPError as e:
        if e.code == 401:
            log.error("GitHub token GECERSIZ (401 Bad credentials)")
            log.error("Yeni token al: https://github.com/settings/tokens")
        else:
            log.error("GitHub token test hatasi: %s", e)
        return False
    except Exception as e:
        log.error("GitHub baglanti hatasi: %s", e)
        return False


def main():
    log.info("=" * 60)
    log.info("OSOS Endeks Takip - Excel Tabanli (v3)")
    log.info("=" * 60)
    log.info("GitHub senkron: %s", "AKTIF" if GH_ENABLED else "KAPALI")
    log.info("Hedef dosya   : %s", GH_DOSYA)
    log.info("Tarayici      : Chrome (Playwright)")
    log.info("Yontem        : OSOS Excel raporu (Son 2 Gun)")
    log.info("=" * 60)
    
    # Token gercekten calisiyor mu test et
    if GH_ENABLED:
        if not github_token_test():
            log.error("=" * 60)
            log.error("KRITIK: GitHub token gecersiz!")
            log.error("baslat_osos.bat icindeki GH_TOKEN'i yenile.")
            log.error("Script devam edecek ama JSON GitHub'a yazilmayacak.")
            log.error("=" * 60)
    
    if len(sys.argv) > 1 and sys.argv[1] == "--giris":
        manuel_giris_ve_kaydet()
        return
    
    # Ilk cekim hemen
    tum_aboneleri_oku()
    
    # Zamanlayici: her saat xx:05
    schedule.every().hour.at(":05").do(tum_aboneleri_oku)
    
    log.info("Zamanlayici aktif - her saat xx:05'te calisacak")
    log.info("Durdurmak icin: CTRL+C")
    
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Durduruldu (CTRL+C)")
    except Exception as e:
        log.error("KRITIK HATA: %s", e, exc_info=True)
