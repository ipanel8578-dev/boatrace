# -*- coding: utf-8 -*-
"""
荒れ指数ビルダー。買い目・予想は出さない。
各レースで「荒れ条件がいくつ揃ったか」を加点して可視化するだけ。

入力(すべてリポジトリ内の既存ファイル):
  docs/racers/racers_today.csv  出走表(級別/当地勝率/平均ST/締切時刻/登録番号)
  docs/motor/motors_all.csv     モーター2連対率(場×登番)
  docs/data/weather.json        3時間ごと風予報(場×時刻)
入力(定数): 24場の荒れ度・1コース1着率(stadium由来・不変)
出力:
  docs/data/arare.json          場×R の score / level / factors
"""
import csv
import json
import os
import re
import datetime

# --- 24場 定数(stadium由来。動かないのでハードコード) ---
STADIUM = {
    "01": ("桐生", "中", 53), "02": ("戸田", "高", 45), "03": ("江戸川", "高", 48),
    "04": ("平和島", "高", 49), "05": ("多摩川", "中", 55), "06": ("浜名湖", "中", 55),
    "07": ("蒲郡", "低", 57), "08": ("常滑", "中", 58), "09": ("津", "中", 56),
    "10": ("三国", "中", 56), "11": ("びわこ", "高", 52), "12": ("住之江", "低", 58),
    "13": ("尼崎", "低", 62), "14": ("鳴門", "高", 50), "15": ("丸亀", "低", 57),
    "16": ("児島", "中", 57), "17": ("宮島", "中", 58), "18": ("徳山", "低", 62),
    "19": ("下関", "低", 60), "20": ("若松", "高", 56), "21": ("芦屋", "低", 64),
    "22": ("福岡", "高", 54), "23": ("唐津", "中", 56), "24": ("大村", "低", 63),
}

RACERS = os.path.join("docs", "racers", "racers_today.csv")
MOTORS = os.path.join("docs", "motor", "motors_all.csv")
WEATHER = os.path.join("docs", "data", "weather.json")
OUT = os.path.join("docs", "data", "arare.json")

# 荒れ度 -> 点
ARARE_PT = {"高": 2, "中": 1, "低": 0}


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_motor_map(rows):
    """(場コード, 登録番号) -> モーター2連対率(float)"""
    mp = {}
    for r in rows:
        jcd = str(r.get("場コード", "")).zfill(2)
        toban = str(r.get("登録番号", "")).strip()
        v = fnum(r.get("モーター2連対率"))
        if jcd and toban and v is not None:
            mp[(jcd, toban)] = v
    return mp


def load_wind_map(path):
    """場コード -> {hh(int): wind(float)} 当日分。無ければ空。"""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    today = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=9))
    ).strftime("%Y-%m-%d")
    out = {}
    for jcd, s in d.get("stadiums", {}).items():
        hh = {}
        for h in s.get("hourly", []):
            t = h.get("time", "")
            if t.startswith(today) and len(t) >= 13:
                hh[int(t[11:13])] = h.get("wind")
        out[str(jcd).zfill(2)] = hh
    return out


def wind_at(wind_map, jcd, deadline):
    """締切'HH:MM'の時のwind。無ければNone。"""
    m = re.match(r"(\d{1,2}):", str(deadline or ""))
    if not m:
        return None
    hh = int(m.group(1))
    hh_map = wind_map.get(jcd, {})
    if hh in hh_map:
        return hh_map[hh]
    # 近い正時にフォールバック
    for delta in (1, -1, 2, -2):
        if hh + delta in hh_map:
            return hh_map[hh + delta]
    return None


def eval_race(boats, jcd, motor_map, wind):
    """1レース(枠順6艇のdict list)を採点。score, factors を返す。"""
    factors = []
    score = 0

    name, arare, in1 = STADIUM.get(jcd, ("", "低", 60))

    # 1) 場の荒れ度
    pt = ARARE_PT.get(arare, 0)
    if pt:
        score += pt
        factors.append("{}は荒れ度{}の水面".format(name, arare))

    # 枠順で引く
    by_waku = {}
    for b in boats:
        w = str(b.get("枠", "")).strip()
        if w.isdigit():
            by_waku[int(w)] = b

    b1 = by_waku.get(1)
    b4 = by_waku.get(4)

    # 2) 締切時刻帯の風
    if wind is not None:
        if wind >= 5:
            score += 2
            factors.append("締切時刻帯の風{:.1f}m(強風)".format(wind))
        elif wind >= 3:
            score += 1
            factors.append("締切時刻帯の風{:.1f}m(やや強い)".format(wind))

    # 3) 1号艇(イン)の信頼度の低さ
    if b1:
        rank1 = str(b1.get("級別", "")).strip()
        if rank1 in ("B1", "B2"):
            score += 1
            factors.append("1号艇が{}(インの格が軽い)".format(rank1))
        # 当地勝率が6艇中で下位(下から2番以内)
        locs = [(int(str(b.get("枠")).strip()), fnum(b.get("当地勝率")))
                for b in boats if str(b.get("枠", "")).strip().isdigit()]
        vals = [v for _, v in locs if v is not None]
        v1 = fnum(b1.get("当地勝率"))
        if v1 is not None and len(vals) >= 4:
            rank_low = sorted(vals)[:2]  # 下位2値
            if v1 in rank_low:
                score += 1
                factors.append("1号艇の当地勝率が節内でも下位")

    # 4) カド4号艇の攻め鋭さ(平均STが6艇中最速)
    if b4:
        sts = [(int(str(b.get("枠")).strip()), fnum(b.get("平均ST")))
               for b in boats if str(b.get("枠", "")).strip().isdigit()]
        st_vals = [(w, v) for w, v in sts if v is not None]
        st4 = fnum(b4.get("平均ST"))
        if st4 is not None and st_vals:
            fastest = min(v for _, v in st_vals)
            if st4 <= fastest:
                score += 1
                factors.append("4号艇のスタートが6艇中最速(カドの一撃)")

    # 5) モーター機力のちぐはぐ(1号艇の機力が6艇平均未満 & 外3艇に最高機)
    if b1:
        mrows = []
        for b in boats:
            w = str(b.get("枠", "")).strip()
            toban = str(b.get("登録番号", "")).strip()
            v = motor_map.get((jcd, toban))
            if w.isdigit() and v is not None:
                mrows.append((int(w), v))
        if len(mrows) >= 5:
            m1 = dict(mrows).get(1)
            avg = sum(v for _, v in mrows) / len(mrows)
            top_w = max(mrows, key=lambda x: x[1])[0]
            if m1 is not None and m1 < avg and top_w in (4, 5, 6):
                score += 1
                factors.append("1号艇の機力が平均以下で外に上位機")

    return score, factors


def level_of(score):
    if score >= 5:
        return "高"
    if score >= 3:
        return "中"
    return "低"


def main():
    racers = load_csv(RACERS)
    motor_map = load_motor_map(load_csv(MOTORS))
    wind_map = load_wind_map(WEATHER)

    # 場×R でまとめる
    races = {}
    for r in racers:
        jcd = str(r.get("場コード", "")).zfill(2)
        rno = re.sub(r"\D", "", str(r.get("レース", "")))
        if not jcd or not rno:
            continue
        races.setdefault((jcd, rno), []).append(r)

    out = {}
    for (jcd, rno), boats in races.items():
        boats.sort(key=lambda b: int(str(b.get("枠", "0")).strip() or 0))
        deadline = str(boats[0].get("締切時刻", "")).strip()
        wind = wind_at(wind_map, jcd, deadline)
        score, factors = eval_race(boats, jcd, motor_map, wind)
        key = "{}_{}".format(jcd, rno)
        out[key] = {
            "jcd": jcd,
            "venue": STADIUM.get(jcd, ("",))[0],
            "rno": int(rno),
            "score": score,
            "level": level_of(score),
            "factors": factors,
            "deadline": deadline,
            "wind": round(wind, 1) if wind is not None else None,
        }

    payload = {
        "generated": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))
        ).isoformat(timespec="minutes"),
        "note": "荒れ条件が揃った数の目安。買い目・予想ではありません。",
        "max_score": 8,
        "races": out,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("arare.json 出力 {}レース".format(len(out)))


if __name__ == "__main__":
    main()
