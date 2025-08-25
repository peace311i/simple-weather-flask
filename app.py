import os
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request
from dotenv import load_dotenv

# .env 読み込み
load_dotenv()
API_KEY = (os.getenv("OWM_API_KEY") or "").strip()
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Tokyo,JP")

app = Flask(__name__)

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
    data["list"] = list(reversed(data["list"]))
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
