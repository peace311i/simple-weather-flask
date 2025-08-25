import os
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request
from dotenv import load_dotenv
# ==== One Call 3.0 用 ここから ====
from typing import Optional

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
    """One Call 3.0: 現在+48時間(hourly)+7日間(daily) を取得"""
    if not API_KEY:
        raise RuntimeError("APIキーが読み込めていません（OWM_API_KEY）")

    url = "https://api.openweathermap.org/data/3.0/onecall"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": API_KEY,
        "units": "metric",
        "lang": "ja",
        # minutelyは使わないので除外。必要ならalertsも返せます
        "exclude": "minutely"
    }
    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    data = r.json()

    # タイムゾーンオフセット（秒）
    tz_offset = data.get("timezone_offset", 0)

    # 現在
    if "current" in data and "dt" in data["current"]:
        utc_dt = datetime.utcfromtimestamp(data["current"]["dt"])
        local_dt = utc_dt + timedelta(seconds=tz_offset)
        data["current"]["local_dt_txt"] = local_dt.strftime("%Y-%m-%d %H:%M")

    # 48時間
    for h in data.get("hourly", []):
        utc_dt = datetime.utcfromtimestamp(h["dt"])
        local_dt = utc_dt + timedelta(seconds=tz_offset)
        h["local_dt_txt"] = local_dt.strftime("%m/%d %H:%M")

    # 7日間（daily）: 日付と最高/最低
    for d in data.get("daily", []):
        utc_dt = datetime.utcfromtimestamp(d["dt"])
        local_dt = utc_dt + timedelta(seconds=tz_offset)
        d["local_dt_txt"] = local_dt.strftime("%Y-%m-%d (%a)")
        # 表示で使いやすいよう丸め
        if "temp" in d:
            d["temp"]["tmax"] = round(d["temp"].get("max", 0))
            d["temp"]["tmin"] = round(d["temp"].get("min", 0))

    return data

@app.route("/onecall")
def onecall():
    """?lat=..&lon=.. を受け取り、One Call 3.0 の結果をレンダリング"""
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return "lat/lon が必要です。ブラウザの位置情報からアクセスしてください。", 400

    try:
        data = fetch_onecall(lat, lon)
        place = fetch_place_name(lat, lon) or data.get("timezone", "現在地")
        return render_template("onecall.html", data=data, place=place, lat=lat, lon=lon, error=None)
    except Exception as e:
        return render_template("onecall.html", data=None, place="現在地", lat=lat, lon=lon,
                               error=f"取得に失敗しました: {e}")
# ==== One Call 3.0 用 ここまで ====

# .env 読み込み
load_dotenv()
API_KEY = (os.getenv("OWM_API_KEY") or "").strip()
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Tokyo,JP")

app = Flask(__name__, static_url_path="/static", static_folder="static")

def fetch_weather(city: str):
    """OpenWeatherの5日/3時間予報を取得し、UTC→現地時間に変換した文字列を付与して返す"""
    if not API_KEY:
        raise RuntimeError("APIキーが読み込めていません（OWM_API_KEY）")

    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": city,
        "appid": API_KEY,
        "lang": "ja",
        "units": "metric",
        "cnt": 8  # 3時間刻み×8=24時間ぶん
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    # タイムゾーン（都市ごと）を使って UTC → 現地時間に変換
    tz_offset = data.get("city", {}).get("timezone", 0)  # 秒（例：Tokyoは 32400 = 9時間）
    for item in data.get("list", []):
        utc_dt = datetime.utcfromtimestamp(item["dt"])
        local_dt = utc_dt + timedelta(seconds=tz_offset)
        # テンプレートで使う表示用フィールドを追加
        item["local_dt_txt"] = local_dt.strftime("%Y-%m-%d %H:%M")

    # ★ここで順序を逆にする
    # data["list"] = list(reversed(data["list"]))
    # もしくは: data["list"] = data["list"][::-1]

    return data



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

# 動作確認用の簡易エンドポイント（任意）
@app.route("/ping")
def ping():
    return "pong"

if __name__ == "__main__":
    # 同一Wi-FiのiPhoneからも見たい場合は host="0.0.0.0"
    app.run(debug=True, host="127.0.0.1", port=5000)
