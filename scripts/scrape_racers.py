#!/usr/bin/env python3
"""
出走表スクレイパー (GitHub Actions自動実行版) v3
各選手は1つの<tr>に横並び。tdの位置で項目を特定する。
td構成: [枠, 写真, 登録番号/級別/氏名/支部/年齢体重, F/L/平均ST,
         全国(勝率/2連/3連), 当地(勝率/2連/3連), モーター, ボート, ...]
docs/racers/ に index.html と racers_today.csv を出力。
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import time
import re
import datetime
import os

VENUES = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島",
    "05": "多摩川", "06": "浜名湖", "07": "蒲郡", "08": "常滑",
    "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
    "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島",
    "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
    "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

JST = datetime.timezone(datetime.timedelta(hours=9))


def target_date():
    """対象とする開催日を返す。GitHub ActionsはUTCなのでJSTに直して判定する。
    JSTで18時以降の夜の実行は翌日分を予習対象にする。日中の実行は当日分。"""
    now = datetime.datetime.now(JST)
    if now.hour >= 18:
        return now.date() + datetime.timedelta(days=1)
    return now.date()

OUTPUT_DIR = os.path.join("docs", "racers")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "template_racers.html")


def cell_decimals(td):
    """td内の小数(X.XX)を出現順に返す"""
    return re.findall(r"\d+\.\d+", td.get_text(" ", strip=True))


def parse_deadlines(soup):
    """ページ上部の「締切予定時刻」行から12レース分のHH:MMを返す"""
    for tr in soup.find_all("tr"):
        txt = tr.get_text(" ", strip=True)
        if "締切予定時刻" in txt:
            return re.findall(r"\d{1,2}:\d{2}", txt)[:12]
    return []


def parse_racelist(html, jcd, venue, hd, rno):
    soup = BeautifulSoup(html, "html.parser")
    records = []

    # このレースの締切予定時刻（締切行の rno 番目）
    deadlines = parse_deadlines(soup)
    deadline = deadlines[rno - 1] if len(deadlines) >= rno else ""

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 8:
            continue
        tr_text = tr.get_text(" ", strip=True)
        m = re.search(r"(\d{4})\s*/\s*(A1|A2|B1|B2)", tr_text)
        if not m:
            continue

        toban = m.group(1)
        rank = m.group(2)

        # 氏名: profileリンクのうち、テキストが数字でない(=写真リンクでない)もの
        name = ""
        for a in tr.find_all("a", href=re.compile(r"toban=\d+")):
            txt = a.get_text(strip=True)
            if txt and not txt.isdigit():
                name = txt
                break

        # 枠番は後で出現順に振るため、ここでは仮置き
        waku = ""

        # F数/L数/平均ST
        f_match = re.search(r"F\s*(\d+)", tr_text)
        l_match = re.search(r"L\s*(\d+)", tr_text)
        f_num = f_match.group(1) if f_match else ""
        l_num = l_match.group(1) if l_match else ""

        # 「登録番号/級別/氏名」のtdを探す → その次から F/L, 全国, 当地 と並ぶ
        # tobanを含むtdのindexを特定
        info_idx = None
        for i, td in enumerate(tds):
            if re.search(r"\d{4}\s*/\s*(A1|A2|B1|B2)", td.get_text(" ", strip=True)):
                info_idx = i
                break

        zen = ["", "", ""]   # 全国 勝率/2連/3連
        toti = ["", "", ""]  # 当地 勝率/2連/3連
        avg_st = ""
        shibu = home = age = ""  # 支部/出身地/年齢
        if info_idx is not None:
            # 支部/出身/年齢: セル例「3388 / A1 今垣 光太郎 福井/石川 56歳/52.0kg」
            # 空白は消さず、漢字ランの区切りとして使う（名前と支部が混ざるのを防ぐ）
            info_text = tds[info_idx].get_text(" ", strip=True)
            mm = re.search(r"([一-龥]+)\s*/\s*([一-龥]+)\s*(\d+)\s*歳", info_text)
            if mm:
                shibu, home, age = mm.group(1), mm.group(2), mm.group(3)
            # info_idx+1 = F/L/平均ST列, +2 = 全国, +3 = 当地 を期待
            if info_idx + 1 < len(tds):
                fl_dec = cell_decimals(tds[info_idx + 1])
                # 平均STは 0.XX
                for d in fl_dec:
                    if re.match(r"^0\.\d+$", d) or re.match(r"^\d\.\d{2}$", d):
                        avg_st = d
                        break
            if info_idx + 2 < len(tds):
                zd = cell_decimals(tds[info_idx + 2])
                for j in range(min(3, len(zd))):
                    zen[j] = zd[j]
            if info_idx + 3 < len(tds):
                td_ = cell_decimals(tds[info_idx + 3])
                for j in range(min(3, len(td_))):
                    toti[j] = td_[j]

        rec = {
            "場名": venue, "場コード": jcd, "開催日": hd, "レース": "{}R".format(rno),
            "枠": waku, "登録番号": toban, "級別": rank, "氏名": name,
            "F数": f_num, "L数": l_num, "平均ST": avg_st,
            "全国勝率": zen[0], "全国2連率": zen[1], "全国3連率": zen[2],
            "当地勝率": toti[0], "当地2連率": toti[1], "当地3連率": toti[2],
            "支部": shibu, "出身": home, "年齢": age, "締切時刻": deadline,
        }
        records.append(rec)

    # 枠番を出現順に振り直す（この関数は1レース分なので、出現順=枠順）
    for i, rec in enumerate(records):
        rec["枠"] = str(i + 1)

    return records


def get_open_venues(hd):
    """「本日のレース」一覧から本日開催している場コードの集合を返す。
    非開催場はこの一覧に並ばないため、すり替わり（リダイレクトで別場の直近データ）を防げる。
    取得できなければ None を返し、呼び出し側は従来どおり全場を試す。"""
    url = "https://www.boatrace.jp/owpc/pc/race/index?hd={}".format(hd)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        if resp.status_code != 200:
            return None
        # 一覧テーブルの各行に jcd=XX&hd=該当日 が埋まっている。該当日のものだけ拾う。
        found = set(re.findall(r"jcd=(\d{2})&hd=" + re.escape(hd), resp.text))
        return found if found else None
    except Exception:
        return None


def find_open_date_and_scrape(jcd, venue):
    # 本日のみを対象にする。非開催場の前回/次節データを誤って拾わないため、
    # 過去日(-1等)や先の日付は探さない。本日のページに出走表が無ければ「開催なし」。
    today = target_date()
    candidates = [0]
    for sign in candidates:
        d = today + datetime.timedelta(days=sign)
        hd = d.strftime("%Y%m%d")
        url = "https://www.boatrace.jp/owpc/pc/race/racelist?rno=1&jcd={}&hd={}".format(jcd, hd)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12)
            if resp.status_code != 200:
                continue
            recs = parse_racelist(resp.text, jcd, venue, hd, 1)
            if not recs:
                continue
            all_recs = list(recs)
            # 2R〜12Rを並列取得（直列＋sleepがボトルネックだったため）。
            # 1場あたり最大6並列。レース順は後で関係ないが、枠番は各レース内で振るため問題なし。
            def fetch_race(rno):
                u = "https://www.boatrace.jp/owpc/pc/race/racelist?rno={}&jcd={}&hd={}".format(rno, jcd, hd)
                try:
                    r = requests.get(u, headers=HEADERS, timeout=12)
                    if r.status_code == 200:
                        return parse_racelist(r.text, jcd, venue, hd, rno)
                except Exception:
                    pass
                return []
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=6) as ex:
                for recs_r in ex.map(fetch_race, range(2, 13)):
                    all_recs.extend(recs_r)
            return hd, all_recs
        except Exception:
            continue
        time.sleep(0.3)
    return None, []


def main():
    print("出走表スクレイパー v3 (自動実行)")
    print("実行日時:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()
    today_hd = target_date().strftime("%Y%m%d")
    open_venues = get_open_venues(today_hd)
    if open_venues:
        print("本日開催場: {} 場 ({})".format(len(open_venues), " ".join(sorted(open_venues))))
    else:
        print("開催場リスト取得失敗 → 全場を試行（従来動作）")
    print()
    all_records = []
    for jcd, name in VENUES.items():
        # 開催場リストが取れていて、そこに無い場はスキップ（非開催のすり替わりを防止）
        if open_venues is not None and jcd not in open_venues:
            print("[{}] {} ... 非開催（スキップ）".format(jcd, name))
            continue
        print("[{}] {} ...".format(jcd, name), end=" ", flush=True)
        hd, records = find_open_date_and_scrape(jcd, name)
        if not records:
            print("開催なし")
            continue
        all_records.extend(records)
        print("OK ({} 名 / {})".format(len(records), hd))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not all_records:
        print("\n本日開催の出走表が取得できませんでした。")
        if os.path.exists(os.path.join(OUTPUT_DIR, "index.html")):
            return

    df = pd.DataFrame(all_records)
    df.to_csv(os.path.join(OUTPUT_DIR, "racers_today.csv"), index=False, encoding="utf-8-sig")
    print("\nCSV保存: {}/racers_today.csv ({}件)".format(OUTPUT_DIR, len(df)))

    cols = [str(c) for c in df.columns.tolist()]
    data = df.fillna("").values.tolist()
    updated = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    data_json = json.dumps(
        {"columns": cols, "data": data, "venues": dict(VENUES), "updated": updated},
        ensure_ascii=False, default=str,
    )
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    html = template.replace("__DATA_PLACEHOLDER__", data_json)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("ビューワー保存: {}/index.html".format(OUTPUT_DIR))
    print("完了!")


if __name__ == "__main__":
    main()
