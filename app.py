import os
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request
from dotenv import load_dotenv
from typing import Optional

# ======================
# 初期設定
# ======================
load_dotenv()
API_KEY = (os.getenv("OWM_API_KEY") or "").strip()
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Tokyo,JP")

app = Flask(__name__, static_url_path="/static", static_folder="static")

# ======================
# 従来の5日間/3時間ごと予報
# ======================
def fetch_weather(city: str):
    """OpenWeatherの5日/3時間予報を取得し、UTC→現地時間に変換"""
    if not API_KEY:
        raise RuntimeError("APIキーが読み込めていません（OWM_API_KEY）")

    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": city,
        "appid": API_KEY,
        "lang": "ja",
        "units": "metric",
        "cnt": 8
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    # タイムゾーン調整
    tz_offset = data.get("city", {}).get("timezone", 0)
    for item in data.get("list", []):
        utc_dt = datetime.utcfromtimestamp(item["dt"])
        local_dt = utc_dt + timedelta(seconds=tz_offset)
        item["local_dt_txt"] = local_dt.strftime("%Y-%m-%d %H:%M")

    # 昇順（APIが元々昇順なので逆順処理しない）
    return data

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
# One Call 3.0: 現在+48時間+7日間予報
# ======================
def fetch_place_name(lat: float, lon: float) -> Optional[str]:
    """逆ジオコーディングで地名を取得（簡易; 1件だけ）"""
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

def fetch_onecall(lat: float, lon: float):
    """One Call 3.0: 現在+48時間(hourly)+7日間(daily)"""
    if not API_KEY:
        raise RuntimeError("APIキーが読み込めていません（OWM_API_KEY）")

    url = "https://api.openweathermap.org/data/3.0/onecall"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": API_KEY,
        "units": "metric",
        "lang": "ja",
        "exclude": "minutely"
    }
    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    data = r.json()

    tz_offset = data.get("timezone_offset", 0)

    # 現在
    if "current" in data and "dt" in data["current"]:
        utc_dt = datetime.utcfromtimestamp(data["current"]["dt"])
        local_dt = utc_dt + timedelta(seconds=tz_offset)
        data["current"]["local_dt_txt"] = local_dt.strftime("%Y-%m-%d %H:%M")

    # hourly: 昇順（そのまま）
    for h in data.get("hourly", []):
        utc_dt = datetime.utcfromtimestamp(h["dt"])
        local_dt = utc_dt + timedelta(seconds=tz_offset)
        h["local_dt_txt"] = local_dt.strftime("%m/%d %H:%M")

    # daily: 昇順（そのまま）
    for d in data.get("daily", []):
        utc_dt = datetime.utcfromtimestamp(d["dt"])
        local_dt = utc_dt + timedelta(seconds=tz_offset)
        d["local_dt_txt"] = local_dt.strftime("%Y-%m-%d (%a)")
        if "temp" in d:
            d["temp"]["tmax"] = round(d["temp"].get("max", 0))
            d["temp"]["tmin"] = round(d["temp"].get("min", 0))

    return data

@app.route("/onecall")
def onecall():
    """?lat=..&lon=.. を受け取り、One Call 3.0 の結果を表示"""
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return "lat/lon が必要です。", 400

    try:
        data = fetch_onecall(lat, lon)
        place = fetch_place_name(lat, lon) or data.get("timezone", "現在地")
        return render_template("onecall.html", data=data, place=place, lat=lat, lon=lon, error=None)
    except Exception as e:
        return render_template("onecall.html", data=None, place="現在地", lat=lat, lon=lon,
                               error=f"取得に失敗しました: {e}")


# ======================
# SW用: /sw.js をルートに置く
# ======================
@app.route("/sw.js")
def sw():
    return app.send_static_file("sw.js")


# ======================
# エントリーポイント
# ======================
if __name__ == "__main__":
    # 127.0.0.1 でローカル確認用
    app.run(debug=True, host="127.0.0.1", port=5000)
