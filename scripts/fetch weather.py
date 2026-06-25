#!/usr/bin/env python3
"""
気象データ取得スクリプト（GitHub Actions自動実行版）
24場の座標で当日＋翌日の1時間ごと風速(m/s)・風向(deg)・天候を Open-Meteo から取得し、
docs/data/weather.json に出力する。締切時刻と時間で紐づけて使う。
※風向→向かい風/追い風の判定は各場「スタート→1M方位」確定後に行う（このJSONは生の風データを持つ）。
"""
import requests
import json
import datetime
import os

JST = datetime.timezone(datetime.timedelta(hours=9))
OUTPUT_DIR = os.path.join("docs", "data")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "weather.json")

# 24場の座標（jcd, 場名, 緯度, 経度）。風予報用なので数km精度で十分。
STADIUMS = [
    ("01", "桐生",   36.4205, 139.3320),
    ("02", "戸田",   35.8108, 139.6890),
    ("03", "江戸川", 35.6940, 139.8730),
    ("04", "平和島", 35.5790, 139.7460),
    ("05", "多摩川", 35.6620, 139.5090),
    ("06", "浜名湖", 34.7130, 137.6080),
    ("07", "蒲郡",   34.8200, 137.2200),
    ("08", "常滑",   34.8830, 136.8330),
    ("09", "津",     34.7330, 136.5230),
    ("10", "三国",   36.2210, 136.1490),
    ("11", "びわこ", 35.0480, 135.9020),
    ("12", "住之江", 34.6100, 135.4790),
    ("13", "尼崎",   34.7110, 135.4080),
    ("14", "鳴門",   34.1720, 134.6100),
    ("15", "丸亀",   34.2940, 133.7900),
    ("16", "児島",   34.4620, 133.7900),
    ("17", "宮島",   34.3030, 132.3110),
    ("18", "徳山",   34.0510, 131.8090),
    ("19", "下関",   33.9610, 130.9300),
    ("20", "若松",   33.9080, 130.8100),
    ("21", "芦屋",   33.9120, 130.6620),
    ("22", "福岡",   33.6010, 130.4010),
    ("23", "唐津",   33.4520, 129.9720),
    ("24", "大村",   32.9210, 129.9610),
]

API_URL = "https://api.open-meteo.com/v1/forecast"

# 16方位ラベル
DIRS16 = ["北","北北東","北東","東北東","東","東南東","南東","南南東",
          "南","南南西","南西","西南西","西","西北西","北西","北北西"]

def dir16(deg):
    if deg is None:
        return ""
    return DIRS16[int((deg % 360) / 22.5 + 0.5) % 16]

# WMO weather_code → 天候ラベル（簡易）
def weather_label(code):
    if code is None:
        return ""
    c = int(code)
    if c == 0: return "快晴"
    if c in (1, 2): return "晴"
    if c == 3: return "曇"
    if c in (45, 48): return "霧"
    if c in (51, 53, 55, 56, 57): return "霧雨"
    if c in (61, 63, 65, 66, 67): return "雨"
    if c in (71, 73, 75, 77): return "雪"
    if c in (80, 81, 82): return "にわか雨"
    if c in (85, 86): return "にわか雪"
    if c in (95, 96, 99): return "雷雨"
    return "—"


def fetch():
    lats = ",".join(str(s[2]) for s in STADIUMS)
    lons = ",".join(str(s[3]) for s in STADIUMS)
    params = {
        "latitude": lats,
        "longitude": lons,
        "hourly": "wind_speed_10m,wind_direction_10m,weather_code",
        "wind_speed_unit": "ms",
        "timezone": "Asia/Tokyo",
        "forecast_days": 2,   # 当日＋翌日（夜の翌日予習に対応）
    }
    r = requests.get(API_URL, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    # 複数地点はJSON配列で返る。1地点だけならオブジェクト。
    return data if isinstance(data, list) else [data]


def build():
    blocks = fetch()
    if len(blocks) != len(STADIUMS):
        print(f"⚠ 返却地点数 {len(blocks)} が場数 {len(STADIUMS)} と不一致。indexずれ注意。")

    stadiums = {}
    for (jcd, name, lat, lon), blk in zip(STADIUMS, blocks):
        h = blk.get("hourly", {}) or {}
        times = h.get("time", []) or []
        ws = h.get("wind_speed_10m", []) or []
        wd = h.get("wind_direction_10m", []) or []
        wc = h.get("weather_code", []) or []
        rows = []
        for i, t in enumerate(times):
            spd = ws[i] if i < len(ws) else None
            deg = wd[i] if i < len(wd) else None
            code = wc[i] if i < len(wc) else None
            rows.append({
                "time": t,                                   # "YYYY-MM-DDTHH:00"（JST）
                "wind": round(spd, 1) if spd is not None else None,  # m/s
                "deg": int(deg) if deg is not None else None,        # 0-359（風が吹いてくる向き）
                "dir": dir16(deg),                                   # 16方位
                "wx": weather_label(code),                           # 天候ラベル
            })
        stadiums[jcd] = {"name": name, "hourly": rows}

    out = {
        "updated": datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "note": "Open-Meteo予報。風速はm/s、degは風が吹いてくる方位(0=北)。向かい風/追い風判定は各場のスタート方位確定後。",
        "stadiums": stadiums,
    }
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"weather.json 出力: {len(stadiums)}場 / 各{len(rows)}時間 / 更新 {out['updated']}")


if __name__ == "__main__":
    build()
