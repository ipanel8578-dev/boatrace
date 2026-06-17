#!/usr/bin/env python3
"""
出走表スクレイパー (GitHub Actions自動実行版)
今日開催している全場・全レースの出走表から、各選手の
全国勝率・当地勝率・モーター成績などを取得する。
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

OUTPUT_DIR = os.path.join("docs", "racers")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "template_racers.html")


def num(s):
    """文字列から数値部分を抽出。失敗したら空文字"""
    s = s.strip()
    m = re.search(r"-?\d+\.?\d*", s)
    return m.group(0) if m else ""


def parse_racelist(html, jcd, venue, hd, rno):
    """1レースの出走表をパースして6艇分のレコードを返す"""
    soup = BeautifulSoup(html, "html.parser")
    records = []

    # 出走表テーブル: class に is-w に近いものや、tbody が選手ごと
    # 各選手は1つの tbody にまとまっている
    tbodies = soup.find_all("tbody")
    for tb in tbodies:
        # 登録番号/級別が入った行を探す
        text = tb.get_text(" ", strip=True)
        # 登録番号(4桁) と 級別(A1/A2/B1/B2) が両方あるブロックのみ対象
        m_toban = re.search(r"(\d{4})\s*/\s*(A1|A2|B1|B2)", text)
        if not m_toban:
            continue

        toban = m_toban.group(1)
        rank = m_toban.group(2)

        # 枠番: tbody内の最初のtdに 1〜6 が入っている
        waku = ""
        first_td = tb.find("td")
        if first_td:
            wt = first_td.get_text(strip=True)
            if wt in ("1", "2", "3", "4", "5", "6"):
                waku = wt

        # 氏名: profileリンクのテキスト
        name = ""
        a = tb.find("a", href=re.compile(r"toban=\d+"))
        if a:
            name = a.get_text(strip=True)

        # 数値群を順に拾う: 全国勝率/2連/3連, 当地勝率/2連/3連, モーターNo/2連/3連, ボートNo/2連/3連
        # tbody内の数値セルを順番に集める
        cell_texts = [td.get_text(strip=True) for td in tb.find_all("td")]

        # 小数(X.XX) と パーセント的な数値を抽出
        floats = []
        for ct in cell_texts:
            if re.match(r"^\d{1,2}\.\d{2}$", ct):
                floats.append(ct)

        # 全国: 勝率,2連率,3連率 / 当地: 勝率,2連率,3連率 の最初の6個を期待
        rec = {
            "場名": venue, "場コード": jcd, "開催日": hd, "レース": "{}R".format(rno),
            "枠": waku, "登録番号": toban, "級別": rank, "氏名": name,
        }

        # F数/L数/平均ST を抽出
        f_match = re.search(r"F(\d+)", text)
        l_match = re.search(r"L(\d+)", text)
        rec["F数"] = f_match.group(1) if f_match else ""
        rec["L数"] = l_match.group(1) if l_match else ""

        # 全国・当地の勝率群（最初に出てくる X.XX 系を割り当て）
        # ページ構造上: 全国勝率,全国2連,全国3連,当地勝率,当地2連,当地3連 の順
        labels = ["全国勝率", "全国2連率", "全国3連率", "当地勝率", "当地2連率", "当地3連率"]
        for i, lab in enumerate(labels):
            rec[lab] = floats[i] if i < len(floats) else ""

        records.append(rec)

    return records


def find_open_date_and_scrape(jcd, venue):
    """開催日を探し、その日の全レースをスクレイプ"""
    today = datetime.date.today()
    candidates = [0, -1, 1, -2, 2, -3, 3]
    for sign in candidates:
        d = today + datetime.timedelta(days=sign)
        hd = d.strftime("%Y%m%d")
        # まず1Rで開催確認
        url = "https://www.boatrace.jp/owpc/pc/race/racelist?rno=1&jcd={}&hd={}".format(jcd, hd)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12)
            if resp.status_code != 200:
                continue
            recs = parse_racelist(resp.text, jcd, venue, hd, 1)
            if not recs:
                continue
            # 開催確認OK → 全12レース取得
            all_recs = list(recs)
            for rno in range(2, 13):
                u = "https://www.boatrace.jp/owpc/pc/race/racelist?rno={}&jcd={}&hd={}".format(rno, jcd, hd)
                try:
                    r = requests.get(u, headers=HEADERS, timeout=12)
                    if r.status_code == 200:
                        rr = parse_racelist(r.text, jcd, venue, hd, rno)
                        all_recs.extend(rr)
                except Exception:
                    pass
                time.sleep(0.4)
            return hd, all_recs
        except Exception:
            continue
        time.sleep(0.3)
    return None, []


def main():
    print("出走表スクレイパー (自動実行)")
    print("実行日時:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()

    all_records = []
    for jcd, name in VENUES.items():
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
    updated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
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
