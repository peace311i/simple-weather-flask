import os
import requests
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, render_template, request
from dotenv import load_dotenv
from typing import Optional, List, Dict, Any

# ======================
# 初期設定
# ======================
load_dotenv()
API_KEY = (os.getenv("OWM_API_KEY") or "").strip()
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Tokyo,JP")

app = Flask(__name__, static_url_path="/static", static_folder="static")

# ======================
# 従来の5日/3時間ごと（都市名指定）
# ======================
def fetch_weather(city: str):
    """OpenWeatherの5日/3時間予報（都市名）を取得し、UTC→現地時間に変換（昇順のまま）"""
    if not API_KEY:
        raise RuntimeError("APIキーが読み込めていません（OWM_API_KEY）")

    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": city,
        "appid": API_KEY,
        "lang": "ja",
        "units": "metric",
        "cnt": 8  # 24時間分（3h×8）
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    tz_offset = data.get("city", {}).get("timezone", 0)  # 秒
    for item in data.get("list", []):
        utc_dt = datetime.utcfromtimestamp(item["dt"])
        local_dt = utc_dt + timedelta(seconds=tz_offset)
        item["local_dt_txt"] = local_dt.strftime("%Y-%m-%d %H:%M")

    return data  # 昇順のまま

@app.route("/", methods=["GET", "POST"])
def index():
    city = DEFAULT_CITY
    error = None
    data = None
    if request.method == "POST":
        city = request.form.get("city") or DEFAULT_CITY
    try:
        data = fetch_weather(city)
    except Exception as e:
        error = f"天気情報の取得に失敗しました: {e}"
    return render_template("index.html", data=data, city=city, error=error)

# ======================
# 現在＋48時間＋5日要約（緯度経度でOne Call非依存）
# ======================
def fetch_place_name(lat: float, lon: float) -> Optional[str]:
    """逆ジオで地名を取得（簡易）"""
    try:
        url = "https://api.openweathermap.org/geo/1.0/reverse"
        params = {"lat": lat, "lon": lon, "limit": 1, "appid": API_KEY}
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        arr = r.json()
        if arr:
            name = arr[0].get("local_names", {}).get("ja") or arr[0].get("name")
            country = arr[0].get("country")
            return f"{name}, {country}" if name and country else (name or country)
    except Exception:
        pass
    return None

def fetch_current(lat: float, lon: float) -> Dict[str, Any]:
    """現在の天気（/weather）"""
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"lat": lat, "lon": lon, "appid": API_KEY, "units": "metric", "lang": "ja"}
    r = requests.get(url, params=params, timeout=8)
    r.raise_for_status()
    data = r.json()

    tz_offset = data.get("timezone", 0)
    if "dt" in data:
        utc_dt = datetime.utcfromtimestamp(data["dt"])
        local_dt = utc_dt + timedelta(seconds=tz_offset)
        data["local_dt_txt"] = local_dt.strftime("%Y-%m-%d %H:%M")
    return data

def fetch_forecast(lat: float, lon: float) -> Dict[str, Any]:
    """3時間ごとの5日予報（/forecast）"""
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {"lat": lat, "lon": lon, "appid": API_KEY, "units": "metric", "lang": "ja"}
    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    data = r.json()

    tz_offset = data.get("city", {}).get("timezone", 0)
    for item in data.get("list", []):
        utc_dt = datetime.utcfromtimestamp(item["dt"])
        local_dt = utc_dt + timedelta(seconds=tz_offset)
        item["local_dt_txt"] = local_dt.strftime("%m/%d %H:%M")
        item["local_date"] = local_dt.date().isoformat()
    data["tz_offset"] = tz_offset
    return data

def build_hourly_48(forecast: Dict[str, Any]) -> List[Dict[str, Any]]:
    """3時間刻みの予報から、先頭48時間（最大16件）を切り出し（昇順のまま）"""
    return forecast.get("list", [])[:16]  # 3h×16=48h

def build_daily_summary(forecast: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    3時間予報を日ごとに集約して、最高/最低・降水確率（最大5日分）などを要約
    One Call の 7日相当には満たないが実用的な日次要約を作る
    """
    by_day: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for it in forecast.get("list", []):
        by_day[it["local_date"]].append(it)

    days = sorted(by_day.keys())  # 昇順
    summary = []
    for d in days[:5]:  # 最大5日分
        items = by_day[d]
        temps = [x["main"]["temp"] for x in items if "main" in x and "temp" in x["main"]]
        tmax = round(max(temps)) if temps else None
        tmin = round(min(temps)) if temps else None
        # 降水確率（pop）は0..1、平均を%表示に
        pops = [x.get("pop", 0) for x in items]
        pop_pct = round(100 * sum(pops) / len(pops)) if pops else 0
        # 代表天気（最初の要素で）
        wx = items[0]["weather"][0] if items and items[0].get("weather") else {"main": "", "description": "", "icon": "01d"}
        # 代表時刻（正午に近いものがあれば選ぶ／なければ先頭）
        def hour_of(it): 
            return int(it["local_dt_txt"].split()[1].split(":")[0])
        rep = sorted(items, key=lambda x: abs(hour_of(x) - 12))[0] if items else None

        summary.append({
            "date_txt": d,                 # 例: 2025-08-25
            "tmax": tmax,
            "tmin": tmin,
            "pop_pct": pop_pct,
            "weather": wx,
            "icon": wx.get("icon", "01d"),
            "rep_time": rep["local_dt_txt"] if rep else "",
            "wind_speed": round(sum(x.get("wind", {}).get("speed", 0) for x in items)/len(items), 1) if items else 0.0
        })
    return summary  # 昇順（日付古→新）

def fetch_current_and_forecast(lat: float, lon: float) -> Dict[str, Any]:
    """現在＋48h（時間）＋5日要約（日）を合成して返す"""
    if not API_KEY:
        raise RuntimeError("APIキーが読み込めていません（OWM_API_KEY）")

    cur = fetch_current(lat, lon)
    fc = fetch_forecast(lat, lon)

    hourly48 = build_hourly_48(fc)            # 昇順
    daily5 = build_daily_summary(fc)           # 昇順
    place = fetch_place_name(lat, lon) or f"{fc.get('city', {}).get('name','現在地')}"

    return {
        "place": place,
        "current": cur,
        "hourly": hourly48,
        "daily": daily5,
        "tz_offset": fc.get("tz_offset", 0)
    }

@app.route("/onecall")
def onecall():
    """
    One Call ではなく /weather + /forecast を使った現在＋48時間＋5日要約の画面。
    使い方: /onecall?lat=35.6812&lon=139.7671
    """
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return "lat/lon が必要です。", 400

    try:
        data = fetch_current_and_forecast(lat, lon)
        # onecall.html をそのまま使うための最低限の互換データ形状に寄せる
        # current / hourly / daily を参照できればOK
        adapted = {
            "current": {
                "local_dt_txt": data["current"].get("local_dt_txt"),
                "temp": data["current"].get("main", {}).get("temp"),
                "feels_like": data["current"].get("main", {}).get("feels_like"),
                "humidity": data["current"].get("main", {}).get("humidity"),
                "pressure": data["current"].get("main", {}).get("pressure"),
                "wind_speed": data["current"].get("wind", {}).get("speed"),
                "clouds": data["current"].get("clouds", {}).get("all"),
                "uvi": data["current"].get("uvi"),  # /weather にはないことが多いので None になる
                "weather": data["current"].get("weather", [{"main":"", "description":"", "icon":"01d"}])
            },
            "hourly": data["hourly"],   # /forecast の各要素（local_dt_txt, main, wind, weather, pop など）
            "daily": [
                {
                    "local_dt_txt": d["date_txt"],
                    "temp": {"tmax": d["tmax"], "tmin": d["tmin"]},
                    "pop": d["pop_pct"]/100.0,
                    "wind_speed": d["wind_speed"],
                    "weather": [d["weather"]],
                    "icon": d["icon"]
                } for d in data["daily"]
            ]
        }
        place = data["place"]
        return render_template("onecall.html", data=adapted, place=place, lat=lat, lon=lon, error=None)
    except Exception as e:
        return render_template("onecall.html", data=None, place="現在地", lat=lat, lon=lon,
                               error=f"取得に失敗しました: {e}")

# ======================
# SW: /sw.js をルートで配信（Scopeを/に）
# ======================
@app.route("/sw.js")
def sw():
    return app.send_static_file("sw.js")

# ======================
# エントリーポイント
# ======================
if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
