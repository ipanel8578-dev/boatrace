#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrapeKimarite.py
公式「競走成績（Kファイル）」から、選手別の
  ・決まり手率（まくり率・差し率ほか）
  ・前づけ傾向（艇番 − 進入コース）
を直近N日ぶん集計して racerKimarite.csv に出力する。

データ元：https://www1.mbrace.or.jp/od2/K/{YYYYMM}/k{YYMMDD}.lzh（公式が配布する正規DLファイル）
解凍：lhasa の `lha` コマンド。lhasa はオプションをコマンド letter に付ける流儀なので
     `lha e -q file` は不可（-q がアーカイブ名扱いになり失敗する）。`lha e file` を使う。
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

DAYS  = int(os.environ.get("KIMARITE_DAYS", "183"))
OUT   = os.environ.get("KIMARITE_OUT", "docs/players/racerKimarite.csv")
SLEEP = float(os.environ.get("KIMARITE_SLEEP", "1.0"))
BASE  = "https://www1.mbrace.or.jp/od2/K/{ym}/k{ymd}.lzh"
UA    = "Mozilla/5.0 (boatrace-data-tool; personal aggregation)"

KIMARITE_ORDER = ["まくり差し", "まくり", "差し", "逃げ", "抜き", "恵まれ"]
KIMARITE_COLS  = ["逃げ", "差し", "まくり", "まくり差し", "抜き", "恵まれ"]

JST = timezone(timedelta(hours=9))

# 失敗の詳細は最初の数件だけ詳しく出す（ログ汚染防止）
_diag = {"dl_bad": 0, "ext_fail": 0, "dl_bad_shown": 0, "ext_fail_shown": 0}
DIAG_MAX = 3


def looks_like_lzh(path):
    """lzhヘッダ（先頭付近に -lh5- などの方式IDがある）か簡易判定"""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
        return b"-lh" in head or b"-lz" in head
    except Exception:
        return False


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=40) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False  # 全休等。スキップ
        print(f"  [warn] HTTP {e.code}: {url}")
        return False
    except Exception as e:
        print(f"  [warn] download失敗: {url} ({e})")
        return False

    # DLできても中身がlzhでない（HTMLエラーページ等）場合を弾く
    if not looks_like_lzh(dest):
        _diag["dl_bad"] += 1
        if _diag["dl_bad_shown"] < DIAG_MAX:
            _diag["dl_bad_shown"] += 1
            try:
                with open(dest, "rb") as f:
                    head = f.read(60)
                print(f"  [diag] lzhでないDL: {url}\n         先頭60バイト: {head!r}")
            except Exception:
                pass
        return False
    return True


def extract_lzh(lzh_path, workdir):
    # lhasa: `lha e <archive>`（-q は付けない）。失敗時に実エラーを拾う。
    try:
        res = subprocess.run(
            ["lha", "e", lzh_path],
            cwd=workdir, capture_output=True, text=True,
        )
    except FileNotFoundError:
        sys.exit("[fatal] lha コマンドが無い。Actionで `sudo apt-get install -y lhasa` を入れること。")

    if res.returncode != 0:
        _diag["ext_fail"] += 1
        if _diag["ext_fail_shown"] < DIAG_MAX:
            _diag["ext_fail_shown"] += 1
            err = (res.stderr or res.stdout or "").strip().splitlines()
            print(f"  [diag] 解凍失敗 rc={res.returncode}: {lzh_path}")
            for ln in err[:3]:
                print(f"         {ln}")
        return []

    return glob.glob(os.path.join(workdir, "*.TXT")) + glob.glob(os.path.join(workdir, "*.txt"))


# ---- 選手行のパース ------------------------------------------------------
# 並び：着順 艇 登番 名前 ﾓｰﾀｰ ﾎﾞｰﾄ 展示 進入 ST ﾚｰｽﾀｲﾑ
def parse_player(line):
    s = re.sub(r"\s+", " ", line.replace("\u3000", " ")).strip()
    t = s.split(" ")
    if len(t) < 4:
        return None
    if not re.fullmatch(r"[1-6]", t[1]):
        return None
    tei = int(t[1])
    touban = t[2]
    if not re.fullmatch(r"\d{4}", touban):
        return None
    chaku = int(t[0]) if re.fullmatch(r"0?[1-6]", t[0]) else None
    course = None
    for k in range(3, len(t) - 1):
        if re.fullmatch(r"\d\.\d{1,2}", t[k]) and re.fullmatch(r"[1-6]", t[k + 1]):
            course = int(t[k + 1])
            break
    return {"tei": tei, "touban": touban, "chaku": chaku, "course": course}


def find_kimarite(line):
    for k in KIMARITE_ORDER:
        if k in line:
            return k
    return ""


def is_separator(line):
    body = line.replace("-", "").strip()
    return len(line) > 10 and body == "" and "-" in line


def parse_text(lines, agg, stats):
    n = len(lines)
    for i in range(n):
        if not is_separator(lines[i]):
            continue
        players = []
        for p in range(1, 7):
            if i + p >= n:
                break
            pr = parse_player(lines[i + p])
            if pr:
                players.append(pr)
        if len(players) < 3:
            continue
        stats["races"] += 1
        kim = find_kimarite(lines[i - 1]) if i - 1 >= 0 else ""
        kotei = ("進入固定" in lines[i - 2]) if i - 2 >= 0 else False
        if kim:
            stats["kim_ok"] += 1
        for pr in players:
            a = agg.setdefault(pr["touban"], {
                "races": 0, "wins": 0, "mz_den": 0, "mz_sum": 0, "mz_hit": 0,
                "in1": 0, "y_makuri": 0, "y_sashi": 0, "y_mz": 0,
                **{c: 0 for c in KIMARITE_COLS},
            })
            if pr["course"] is not None:
                a["races"] += 1
                if not kotei:
                    diff = pr["tei"] - pr["course"]
                    a["mz_den"] += 1
                    a["mz_sum"] += diff
                    if diff >= 2:
                        a["mz_hit"] += 1
            # やられ系（1コース進入ベース）：自分が①番手で逃げ切れず、外/内に決められた回数
            if pr["course"] == 1:
                a["in1"] += 1
                if kim == "まくり":
                    a["y_makuri"] += 1
                elif kim == "差し":
                    a["y_sashi"] += 1
                elif kim == "まくり差し":
                    a["y_mz"] += 1
            if pr["chaku"] == 1:
                a["wins"] += 1
                if kim in KIMARITE_COLS:
                    a[kim] += 1


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
            got = False
            for txt in extract_lzh(lzh, wd):
                got = True
                with open(txt, encoding="cp932", errors="replace") as f:
                    parse_text(f.readlines(), agg, stats)
            if got:
                stats["days_ok"] += 1
            shutil.rmtree(wd, ignore_errors=True)
            time.sleep(SLEEP)
    finally:
        shutil.rmtree(workroot, ignore_errors=True)

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    header = ["登録番号", "集計開始", "集計終了", "出走数", "1着数"] + KIMARITE_COLS + \
             ["まくり率", "差し率", "前づけ平均", "前づけ率",
              "イン進入数", "さされ率", "まくられ率", "まくりさされ率"]
    rows = []
    for tb in sorted(agg.keys()):
        a = agg[tb]
        wins = a["wins"]; mz_den = a["mz_den"]
        makuri_rate = round(a["まくり"] / wins * 100, 1) if wins else ""
        sashi_rate  = round(a["差し"]  / wins * 100, 1) if wins else ""
        mz_avg      = round(a["mz_sum"] / mz_den, 2) if mz_den else ""
        mz_rate     = round(a["mz_hit"] / mz_den * 100, 1) if mz_den else ""
        in1 = a["in1"]
        sasare_rate     = round(a["y_sashi"]  / in1 * 100, 1) if in1 else ""
        makurare_rate   = round(a["y_makuri"] / in1 * 100, 1) if in1 else ""
        mzsasare_rate   = round(a["y_mz"]     / in1 * 100, 1) if in1 else ""
        rows.append([
            tb, str(start), str(today - timedelta(days=1)),
            a["races"], wins,
            *[a[c] for c in KIMARITE_COLS],
            makuri_rate, sashi_rate, mz_avg, mz_rate,
            in1, sasare_rate, makurare_rate, mzsasare_rate,
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
    print(f"DL不正(非lzh)  : {_diag['dl_bad']}")
    print(f"解凍失敗        : {_diag['ext_fail']}")
    print(f"出力           : {OUT}")
    if stats["races"] == 0:
        sys.exit("[fatal] レースを1件も拾えていない。上の[diag]で原因(DL不正/解凍失敗)を確認。")
    if kim_pct < 80:
        print("[warn] 決まり手取得率が低い。find_kimarite の走査行を実ファイルで要確認。")


if __name__ == "__main__":
    main()
