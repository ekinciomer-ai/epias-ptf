#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OSOS EXCEL OTOMATIK INDIRME — Raspberry Pi icin Playwright iskeleti
====================================================================
Amac: 3 sayacin (T1=11116344, T2=11116968, A3=11200108) profil Excel'lerini
OSOS portalindan otomatik indirip /home/pi/otocoin/osos_gelen/ klasorune koymak.
Sonrasinda mevcut parse mantigi (Claude oturumundaki) bu dosyalari isler.

KURULUM (Pi'da bir kez):
    pip install playwright --break-system-packages
    playwright install chromium
    # Pi 32-bit ise chromium sorun cikarirsa: sudo apt install chromium-browser
    # ve asagida channel="chromium" yerine executable_path verin.

CRON (her gece 23:30):
    30 23 * * * cd /home/pi/otocoin && python3 osos_indir.py >> osos_indir.log 2>&1

DOLDURULACAK YERLER — !!! ile isaretli:
    1. PORTAL_URL          : OSOS portal giris adresi
    2. KULLANICI / SIFRE   : ortam degiskeninden okunur (asagiya yazmayin!)
    3. Selector'lar        : portalda F12 > Elements ile bulunur (asagida rehber var)

SELECTOR BULMA REHBERI:
    Portala girin, F12 acin, login kutusuna sag tik > Inspect.
    input etiketinin id'si varsa  -> "#kullaniciAdi"
    name'i varsa                  -> "input[name='username']"
    Bulduklarinizi asagidaki SEC sozlugune yazin, bana gonderin, kalanini tamamlarim.
"""

import os
import sys
import time
import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ════════════════ AYARLAR ════════════════
PORTAL_URL = "!!!_OSOS_PORTAL_GIRIS_ADRESI_!!!"      # ornek: https://osos.xxxedas.com.tr/login
KULLANICI  = os.environ.get("OSOS_KULLANICI", "")     # export OSOS_KULLANICI=... (.bashrc veya cron env)
SIFRE      = os.environ.get("OSOS_SIFRE", "")

INDIRME_KLASORU = Path("/home/pi/otocoin/osos_gelen")

SAYACLAR = [
    {"ad": "tekyildiz_1", "tesisat": "11116344"},
    {"ad": "tekyildiz_2", "tesisat": "11116968"},
    {"ad": "aksaray_3",   "tesisat": "11200108"},
]

# Kac gunluk profil cekilsin (bugunden geriye)
GUN_SAYISI = 3

# Portal selector'lari — F12 ile bulup doldurun
SEC = {
    "login_kullanici": "!!!",   # ornek: "#username" veya "input[name='j_username']"
    "login_sifre":     "!!!",   # ornek: "#password"
    "login_buton":     "!!!",   # ornek: "button[type='submit']"
    "sayac_arama":     "!!!",   # tesisat no girilen kutu
    "tarih_baslangic": "!!!",
    "tarih_bitis":     "!!!",
    "excel_buton":     "!!!",   # "Excel'e Aktar" / indir butonu
}
# ═════════════════════════════════════════


def log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def kontrol():
    eksik = []
    if "!!!" in PORTAL_URL:
        eksik.append("PORTAL_URL")
    if not KULLANICI or not SIFRE:
        eksik.append("OSOS_KULLANICI / OSOS_SIFRE ortam degiskenleri")
    eksik += [f"SEC['{k}']" for k, v in SEC.items() if v == "!!!"]
    if eksik:
        log("EKSIK AYARLAR: " + ", ".join(eksik))
        log("Bu alanlari doldurmadan script calismaz. Rehber dosya basindadir.")
        sys.exit(1)


def indir():
    INDIRME_KLASORU.mkdir(parents=True, exist_ok=True)
    bugun = datetime.date.today()
    baslangic = bugun - datetime.timedelta(days=GUN_SAYISI)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        page.set_default_timeout(30000)

        # ── 1) GIRIS ──
        log(f"Portala gidiliyor: {PORTAL_URL}")
        page.goto(PORTAL_URL)
        page.fill(SEC["login_kullanici"], KULLANICI)
        page.fill(SEC["login_sifre"], SIFRE)
        page.click(SEC["login_buton"])
        page.wait_for_load_state("networkidle")
        log("Giris yapildi")

        # ── 2) HER SAYAC ICIN PROFIL EXCEL'I ──
        for s in SAYACLAR:
            try:
                log(f"{s['ad']} ({s['tesisat']}) cekiliyor...")

                # Sayac secimi — portal akisina gore uyarlanacak:
                page.fill(SEC["sayac_arama"], s["tesisat"])
                page.keyboard.press("Enter")
                page.wait_for_load_state("networkidle")

                # Tarih araligi
                page.fill(SEC["tarih_baslangic"], baslangic.strftime("%d.%m.%Y"))
                page.fill(SEC["tarih_bitis"], bugun.strftime("%d.%m.%Y"))

                # Excel indir
                with page.expect_download() as dl:
                    page.click(SEC["excel_buton"])
                dosya = dl.value
                hedef = INDIRME_KLASORU / f"{s['tesisat']}_{bugun:%Y%m%d}.xlsx"
                dosya.save_as(hedef)
                log(f"  -> kaydedildi: {hedef.name}")
                time.sleep(2)  # portali yormamak icin

            except PWTimeout:
                log(f"  !! {s['ad']} icin zaman asimi — selector veya akis kontrol edilmeli")
            except Exception as e:
                log(f"  !! {s['ad']} hata: {e}")

        browser.close()
    log("Bitti.")


if __name__ == "__main__":
    kontrol()
    indir()
