"""
fusion_solar.py
===============
Aksaray Enerji - Huawei FusionSolar Northbound API veri çekme worker'ı.

ÇALIŞTIRMA YERLERİ:
  - Railway: cron job veya endpoint olarak
  - GitHub Actions: scheduled workflow
  - Lokal: manuel test

ÇIKTI:
  - fusion_data.json (panele beslenir)
  - GitHub'a otomatik push edebilir (GH_TOKEN varsa)

ENVIRONMENT VARIABLES:
  FUSION_USER       - API kullanıcı adı (default: aksaray_api10)
  FUSION_PASS       - API şifresi (zorunlu)
  FUSION_BASE_URL   - Base URL (default: https://sg5.fusionsolar.huawei.com)
  GH_TOKEN          - GitHub push için (opsiyonel)
  GH_REPO           - Repo path (default: ekinciomer-ai/epias-ptf)
"""

import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
import base64

# ============ AYARLAR ============
USER = os.environ.get("FUSION_USER", "aksaray_api10")
PASS = os.environ.get("FUSION_PASS", "Ae2026api!")
BASE_URL = os.environ.get("FUSION_BASE_URL", "https://sg5.fusionsolar.huawei.com")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_REPO = os.environ.get("GH_REPO", "ekinciomer-ai/epias-ptf")
OUTPUT_FILE = "fusion_data.json"
# =================================


class FusionAPI:
    """Minimal Huawei FusionSolar Northbound API client (sadece urllib kullanır)."""

    def __init__(self, user, password, base_url):
        self.user = user
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.xsrf_token = None
        self.cookies = {}

    def _request(self, path, body=None, retry_login=True):
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        if self.xsrf_token:
            headers["XSRF-TOKEN"] = self.xsrf_token
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())

        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                # Cookie'leri yakala
                set_cookies = r.headers.get_all("Set-Cookie") or []
                for sc in set_cookies:
                    pair = sc.split(";")[0]
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        self.cookies[k.strip()] = v.strip()
                        if k.strip().upper() == "XSRF-TOKEN":
                            self.xsrf_token = v.strip()
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            try:
                data = json.loads(body)
                # Session bitmiş, yeniden login
                if retry_login and data.get("failCode") == 305:
                    self.login()
                    return self._request(path, body, retry_login=False)
            except:
                pass
            raise Exception(f"HTTP {e.code}: {body}")

    def login(self):
        self.xsrf_token = None
        self.cookies = {}
        r = self._request(
            "/thirdData/login",
            {"userName": self.user, "systemCode": self.password},
            retry_login=False
        )
        if not r.get("success"):
            raise Exception(f"Login failed: {r}")
        return r

    def get_stations(self):
        r = self._request("/thirdData/getStationList", {})
        return r.get("data", []) if r.get("success") else []

    def get_devices(self, station_code):
        r = self._request("/thirdData/getDevList", {"stationCodes": station_code})
        return r.get("data", []) if r.get("success") else []

    def get_realtime_kpi(self, dev_ids, dev_type_id=1):
        ids_str = ",".join(str(i) for i in dev_ids)
        r = self._request("/thirdData/getDevRealKpi",
                          {"devIds": ids_str, "devTypeId": dev_type_id})
        return r.get("data", []) if r.get("success") else []

    def get_station_daily(self, station_code, collect_time_ms):
        r = self._request("/thirdData/getKpiStationDay",
                          {"stationCodes": station_code, "collectTime": collect_time_ms})
        return r.get("data", []) if r.get("success") else []

    def get_station_monthly(self, station_code, collect_time_ms):
        r = self._request("/thirdData/getKpiStationMonth",
                          {"stationCodes": station_code, "collectTime": collect_time_ms})
        return r.get("data", []) if r.get("success") else []


def github_push(filepath, repo, token, message="🌞 fusion data update"):
    """GitHub API ile dosyayı repo'ya push eder."""
    if not token:
        print("⚠️  GH_TOKEN yok, GitHub push atlanıyor")
        return False

    with open(filepath, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    api_url = f"https://api.github.com/repos/{repo}/contents/{filepath}"

    # Önce mevcut SHA'yı al (update için gerekli)
    sha = None
    try:
        req = urllib.request.Request(api_url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            sha = json.loads(r.read()).get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"⚠️  SHA alınamadı: {e}")

    payload = {"message": message, "content": content}
    if sha:
        payload["sha"] = sha

    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json"
        },
        method="PUT"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"✅ GitHub push OK: {filepath}")
            return True
    except urllib.error.HTTPError as e:
        print(f"❌ GitHub push fail: {e.code} {e.read().decode()}")
        return False


def collect_all():
    """Tüm verileri toplar ve fusion_data.json'a yazar."""
    print(f"🌞 FusionSolar veri toplama başladı | {datetime.now().isoformat()}")
    api = FusionAPI(USER, PASS, BASE_URL)

    # 1. Login
    print("🔐 Login...")
    api.login()
    print("✅ Login OK")

    # 2. Tesisler
    print("🏭 Tesisler...")
    stations = api.get_stations()
    print(f"   {len(stations)} tesis")

    # 3. Tüm cihazlar
    print("📡 Cihazlar...")
    all_devices = []
    for s in stations:
        devs = api.get_devices(s["stationCode"])
        for d in devs:
            d["stationName"] = s["stationName"]
            d["stationCode"] = s["stationCode"]
            all_devices.append(d)
    inverters = [d for d in all_devices if d.get("devTypeId") == 1]
    print(f"   {len(all_devices)} cihaz, {len(inverters)} inverter")

    # 4. Anlık veri (18 inverter)
    print("⚡ Anlık veriler...")
    dev_ids = [d["id"] for d in inverters]
    realtime_raw = api.get_realtime_kpi(dev_ids) if dev_ids else []

    inverter_data = []
    station_totals = {}  # stationCode -> {power, day, lifetime}
    total_power = 0.0
    total_day = 0.0
    total_lifetime = 0.0

    for kpi in realtime_raw:
        dev_id = kpi.get("devId")
        items = kpi.get("dataItemMap", {}) or {}
        info = next((d for d in inverters if str(d["id"]) == str(dev_id)), None)
        if not info:
            continue

        active_power = float(items.get("active_power") or 0)
        day_cap = float(items.get("day_cap") or 0)
        total_cap = float(items.get("total_cap") or 0)
        run_state = items.get("run_state", -1)

        total_power += active_power
        total_day += day_cap
        total_lifetime += total_cap

        st = info["stationCode"]
        if st not in station_totals:
            station_totals[st] = {"power": 0, "day": 0, "lifetime": 0,
                                  "name": info["stationName"], "count": 0}
        station_totals[st]["power"] += active_power
        station_totals[st]["day"] += day_cap
        station_totals[st]["lifetime"] += total_cap
        station_totals[st]["count"] += 1

        inverter_data.append({
            "devId": dev_id,
            "devName": info["devName"],
            "stationName": info["stationName"],
            "stationCode": info["stationCode"],
            "activePower_kW": round(active_power, 2),
            "dayEnergy_kWh": round(day_cap, 2),
            "totalEnergy_kWh": round(total_cap, 2),
            "runState": run_state,
            "temperature": items.get("temperature"),
            "efficiency": items.get("efficiency"),
        })

    print(f"   Anlık: {total_power:.1f} kW | Bugün: {total_day:.1f} kWh")

    # 5. Günlük saatlik üretim (her tesis için)
    print("📊 Günlük üretim...")
    now = datetime.now()
    today_start_ms = int(datetime(now.year, now.month, now.day).timestamp() * 1000)

    daily_data = {}
    for s in stations:
        daily = api.get_station_daily(s["stationCode"], today_start_ms)
        # Saat bazında pivota dönüştür: { "00": {power, ...}, "01": {...} }
        hourly = {}
        for entry in daily:
            ct = entry.get("collectTime", 0)
            dt = datetime.fromtimestamp(ct / 1000)
            hour_key = f"{dt.hour:02d}"
            items = entry.get("dataItemMap", {}) or {}
            hourly[hour_key] = {
                "power_kW": float(items.get("inverter_power") or 0),
                "production_kWh": float(items.get("product_power") or 0),
                "radiation": float(items.get("radiation_intensity") or 0),
            }
        daily_data[s["stationCode"]] = {
            "stationName": s["stationName"],
            "date": now.strftime("%Y-%m-%d"),
            "hourly": hourly,
        }

    # 6. Aylık günlük üretim
    print("📅 Aylık üretim...")
    month_start_ms = int(datetime(now.year, now.month, 1).timestamp() * 1000)
    monthly_data = {}
    for s in stations:
        monthly = api.get_station_monthly(s["stationCode"], month_start_ms)
        daily_breakdown = {}
        for entry in monthly:
            ct = entry.get("collectTime", 0)
            dt = datetime.fromtimestamp(ct / 1000)
            day_key = dt.strftime("%Y-%m-%d")
            items = entry.get("dataItemMap", {}) or {}
            daily_breakdown[day_key] = {
                "production_kWh": float(items.get("product_power") or 0),
            }
        monthly_data[s["stationCode"]] = {
            "stationName": s["stationName"],
            "month": now.strftime("%Y-%m"),
            "daily": daily_breakdown,
        }

    # 7. Bundle oluştur
    bundle = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "station_count": len(stations),
            "inverter_count": len(inverter_data),
            "total_power_kW": round(total_power, 2),
            "total_day_kWh": round(total_day, 2),
            "total_lifetime_kWh": round(total_lifetime, 2),
            "total_capacity_MW": round(sum(s.get("capacity", 0) for s in stations), 4),
        },
        "stations": [
            {
                "code": s["stationCode"],
                "name": s["stationName"],
                "capacity_MW": s.get("capacity", 0),
                "address": s.get("stationAddr", ""),
                "current_power_kW": round(station_totals.get(s["stationCode"], {}).get("power", 0), 2),
                "day_energy_kWh": round(station_totals.get(s["stationCode"], {}).get("day", 0), 2),
                "lifetime_kWh": round(station_totals.get(s["stationCode"], {}).get("lifetime", 0), 2),
                "inverter_count": station_totals.get(s["stationCode"], {}).get("count", 0),
            }
            for s in stations
        ],
        "inverters": sorted(inverter_data, key=lambda x: (x["stationName"], x["devName"])),
        "daily": daily_data,
        "monthly": monthly_data,
    }

    # 8. Yaz
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)
    print(f"💾 {OUTPUT_FILE} kaydedildi")

    # 9. GitHub'a push
    if GH_TOKEN:
        github_push(OUTPUT_FILE, GH_REPO, GH_TOKEN)

    return bundle


if __name__ == "__main__":
    try:
        bundle = collect_all()
        s = bundle["summary"]
        print("\n" + "=" * 60)
        print(f"📊 ÖZET")
        print(f"   • Tesis:        {s['station_count']}")
        print(f"   • Inverter:     {s['inverter_count']}")
        print(f"   • Anlık güç:    {s['total_power_kW']} kW")
        print(f"   • Bugünkü:      {s['total_day_kWh']} kWh")
        print(f"   • Ömür boyu:    {s['total_lifetime_kWh']:.0f} kWh")
        print(f"   • Kapasite:     {s['total_capacity_MW']} MW")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ HATA: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
