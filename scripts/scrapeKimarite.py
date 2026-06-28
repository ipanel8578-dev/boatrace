#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrapeKimarite.py
公式「競走成績（Kファイル）」から、選手別の
  ・決まり手率（まくり率・差し率ほか）
  ・前づけ傾向（艇番 − 進入コース）
を直近N日ぶん集計して racerKimarite.csv に出力する。

データ元：https://www1.mbrace.or.jp/od2/K/{YYYYMM}/k{YYMMDD}.lzh（公式が配布する正規DLファイル）
        ※HTMLスクレイピングではなく公式配布ファイルなので規約問題なし。

実行環境：GitHub Actions（ubuntu）。解凍に lhasa（lha コマンド）を使う。
        ローカル確認時は環境変数で日数を絞ると速い（例 KIMARITE_DAYS=7）。

このスクリプトは boatrace.jp / mbrace へ実アクセスできない環境では検証していない。
初回Action実行後、出力CSVの集計件数とparse成功率（末尾ログ）を見て微調整する前提。
"""

import os
import re
import csv
import sys
import glob
import time
import shutil
import tempfile
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

# ---- 設定（環境変数で上書き可）-------------------------------------------
DAYS  = int(os.environ.get("KIMARITE_DAYS", "183"))          # 集計する日数（約6ヶ月）
OUT   = os.environ.get("KIMARITE_OUT", "docs/players/racerKimarite.csv")
SLEEP = float(os.environ.get("KIMARITE_SLEEP", "1.0"))        # DL間隔（秒）サーバ負荷配慮
BASE  = "https://www1.mbrace.or.jp/od2/K/{ym}/k{ymd}.lzh"
UA    = "Mozilla/5.0 (boatrace-data-tool; personal aggregation)"

# 決まり手は6種。長い語を先にして部分一致の取りこぼし・誤判定を防ぐ
KIMARITE_ORDER = ["まくり差し", "まくり", "差し", "逃げ", "抜き", "恵まれ"]
KIMARITE_COLS  = ["逃げ", "差し", "まくり", "まくり差し", "抜き", "恵まれ"]

JST = timezone(timedelta(hours=9))


# ---- ダウンロード ---------------------------------------------------------
def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=40) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False  # その日の配布が無い（全休等）→ スキップ
        print(f"  [warn] HTTP {e.code}: {url}")
        return False
    except Exception as e:
        print(f"  [warn] download失敗: {url} ({e})")
        return False


# ---- 解凍（lhasa の lha コマンド）----------------------------------------
def extract_lzh(lzh_path, workdir):
    try:
        subprocess.run(
            ["lha", "e", "-q", lzh_path],
            cwd=workdir, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        sys.exit("[fatal] lha コマンドが無い。Actionで `sudo apt-get install -y lhasa` を入れること。")
    except subprocess.CalledProcessError:
        print(f"  [warn] 解凍失敗: {lzh_path}")
        return []
    txts = glob.glob(os.path.join(workdir, "*.TXT")) + glob.glob(os.path.join(workdir, "*.txt"))
    return txts


# ---- 1行（選手行）のパース ------------------------------------------------
# 競走成績の選手行の並び：着順 艇 登番 名前 ﾓｰﾀｰ ﾎﾞｰﾄ 展示 進入 ST ﾚｰｽﾀｲﾑ
#   ・着順は "01".."06" か Ｆ/Ｌ/欠/失/不/転/落/妨 等（＝完走でない）
#   ・進入コースは「展示タイム(例 6.78)の直後にある単独の 1〜6」で特定する
def parse_player(line):
    s = re.sub(r"\s+", " ", line.replace("\u3000", " ")).strip()
    t = s.split(" ")
    if len(t) < 4:
        return None

    # 艇番（枠）1〜6
    m_tei = re.search(r"[1-6]", t[1]) if len(t) > 1 else None
    if not (len(t) > 1 and re.fullmatch(r"[1-6]", t[1])):
        return None
    tei = int(t[1])

    # 登録番号 4桁
    touban = t[2] if len(t) > 2 else ""
    if not re.fullmatch(r"\d{4}", touban):
        return None

    # 着順（完走のみ数値、それ以外は None）
    chaku = None
    if re.fullmatch(r"0?[1-6]", t[0]):
        chaku = int(t[0])

    # 進入コース：展示タイム(N.NN)直後の単独 1〜6
    course = None
    for k in range(3, len(t) - 1):
        if re.fullmatch(r"\d\.\d{1,2}", t[k]) and re.fullmatch(r"[1-6]", t[k + 1]):
            course = int(t[k + 1])
            break

    return {"tei": tei, "touban": touban, "chaku": chaku, "course": course}


# ---- 決まり手の抽出 -------------------------------------------------------
# 決まり手は区切り(----)の直前行に入る。レース名(2つ上)の誤検出を避けるため直前行のみ走査。
def find_kimarite(line):
    for k in KIMARITE_ORDER:
        if k in line:
            return k
    return ""


def is_separator(line):
    body = line.replace("-", "").strip()
    return len(line) > 10 and body == "" and "-" in line


# ---- 1日ぶんのテキストを集計に反映 ---------------------------------------
def parse_text(lines, agg, stats):
    n = len(lines)
    for i in range(n):
        if not is_separator(lines[i]):
            continue
        # 直後6行が選手行
        players = []
        for p in range(1, 7):
            if i + p >= n:
                break
            pr = parse_player(lines[i + p])
            if pr:
                players.append(pr)
        # 区切りの誤検出ガード：選手行が3つ以上取れた時だけレースとみなす
        if len(players) < 3:
            continue

        stats["races"] += 1

        # 決まり手（直前行）と 進入固定 フラグ（2つ上＝レース情報行）
        kim = find_kimarite(lines[i - 1]) if i - 1 >= 0 else ""
        kotei = ("進入固定" in lines[i - 2]) if i - 2 >= 0 else False
        if kim:
            stats["kim_ok"] += 1

        for pr in players:
            tb = pr["touban"]
            a = agg.setdefault(tb, {
                "races": 0, "wins": 0, "mz_den": 0, "mz_sum": 0, "mz_hit": 0,
                **{c: 0 for c in KIMARITE_COLS},
            })
            if pr["course"] is not None:
                a["races"] += 1
                if not kotei:                       # 進入固定レースは前づけ不可なので対象外
                    diff = pr["tei"] - pr["course"]  # 正＝枠より内側へ進入＝前づけ寄り
                    a["mz_den"] += 1
                    a["mz_sum"] += diff
                    if diff >= 2:
                        a["mz_hit"] += 1
            if pr["chaku"] == 1:
                a["wins"] += 1
                if kim in KIMARITE_COLS:
                    a[kim] += 1


# ---- メイン ---------------------------------------------------------------
def main():
    today = datetime.now(JST).date()
    start = today - timedelta(days=DAYS)
    print(f"集計対象：{start} 〜 {today - timedelta(days=1)}（{DAYS}日）")

    agg = {}
    stats = {"days_ok": 0, "races": 0, "kim_ok": 0}
    workroot = tempfile.mkdtemp(prefix="kimarite_")

    try:
        for d in range(1, DAYS + 1):
            day = today - timedelta(days=d)
            url = BASE.format(ym=day.strftime("%Y%m"), ymd=day.strftime("%y%m%d"))
            wd = tempfile.mkdtemp(dir=workroot)
            lzh = os.path.join(wd, "k.lzh")

            if not download(url, lzh):
                shutil.rmtree(wd, ignore_errors=True)
                time.sleep(SLEEP)
                continue

            for txt in extract_lzh(lzh, wd):
                with open(txt, encoding="cp932", errors="replace") as f:
                    parse_text(f.readlines(), agg, stats)
            stats["days_ok"] += 1
            shutil.rmtree(wd, ignore_errors=True)
            time.sleep(SLEEP)
    finally:
        shutil.rmtree(workroot, ignore_errors=True)

    # ---- CSV出力 ----
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    header = ["登録番号", "集計開始", "集計終了", "出走数", "1着数"] + KIMARITE_COLS + \
             ["まくり率", "差し率", "前づけ平均", "前づけ率"]
    rows = []
    for tb in sorted(agg.keys()):
        a = agg[tb]
        wins = a["wins"]
        mz_den = a["mz_den"]
        makuri_rate = round(a["まくり"] / wins * 100, 1) if wins else ""
        sashi_rate  = round(a["差し"]  / wins * 100, 1) if wins else ""
        mz_avg      = round(a["mz_sum"] / mz_den, 2) if mz_den else ""
        mz_rate     = round(a["mz_hit"] / mz_den * 100, 1) if mz_den else ""
        rows.append([
            tb, str(start), str(today - timedelta(days=1)),
            a["races"], wins,
            *[a[c] for c in KIMARITE_COLS],
            makuri_rate, sashi_rate, mz_avg, mz_rate,
        ])

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    kim_pct = (stats["kim_ok"] / stats["races"] * 100) if stats["races"] else 0
    print("---- 集計サマリ ----")
    print(f"取得できた日数 : {stats['days_ok']} / {DAYS}")
    print(f"パースしたレース: {stats['races']}（決まり手取得率 {kim_pct:.1f}%）")
    print(f"選手数         : {len(rows)}")
    print(f"出力           : {OUT}")
    if stats["races"] == 0:
        sys.exit("[fatal] レースを1件も拾えていない。DL/解凍/桁構造のいずれかを要確認。")
    if kim_pct < 80:
        print("[warn] 決まり手取得率が低い。find_kimarite の走査行（区切り直前行）を実ファイルで要確認。")


if __name__ == "__main__":
    main()
