# -*- coding: utf-8 -*-
"""
桐生（jcd=01）3連単払戻データ収集スクレイパー
mbrace公式競走成績配布（LZH）方式。徳山高速版と同設定。
出力: docs/payouts/kiryuPayouts.csv （列: hd, rno, combo, payout）

環境変数:
  YM   … 'YYYYMM' 指定でその月のみ収集（未指定なら今日から遡る）
  DAYS … 遡る日数（未指定なら365）
"""
import os
import re
import csv
import time
import datetime
import urllib.request

import lhafile

BASE = "http://www1.mbrace.or.jp/od2/K/{ym}/k{ymd}.lzh"
OUT = "docs/payouts/kiryuPayouts.csv"

KIRYU = "\u6850\u3000\u751f\uff3b\u6210\u7e3e\uff3d"   # 桐　生［成績］（全角スペース有り・現物確認済み）
SEISEKI = "\uff3b\u6210\u7e3e\uff3d"                  # ［成績］
PAY = "\u6255\u623b\u91d1"                            # 払戻金
PAYLINE = re.compile(r"\s*(\d{1,2})R\s+(\d)-(\d)-(\d)\s+(\d+)")

SLEEP = 1.0
TIMEOUT = 8


def fetch_lzh(d):
    ym = d.strftime("%Y%m")
    ymd = d.strftime("%y%m%d")
    url = BASE.format(ym=ym, ymd=ymd)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def parse_kiryu(raw):
    tmp = "_tmp_kiryu.lzh"
    with open(tmp, "wb") as f:
        f.write(raw)
    a = lhafile.Lhafile(tmp)
    data = a.read(a.infolist()[0].filename)
    txt = data.decode("shift_jis", "ignore")
    os.remove(tmp)
    out = []
    in_t = False
    in_p = False
    for ln in txt.split("\n"):
        if SEISEKI in ln:
            in_t = KIRYU in ln
            in_p = False
            continue
        if not in_t:
            continue
        if PAY in ln:
            in_p = True
            continue
        if in_p:
            m = PAYLINE.match(ln)
            if m:
                rno = int(m.group(1))
                combo = m.group(2) + "-" + m.group(3) + "-" + m.group(4)
                payout = int(m.group(5))
                out.append((rno, combo, payout))
            elif out and not re.search(r"\d", ln):
                in_p = False
    return out


def load_done():
    done = set()
    rows = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            r = csv.reader(f)
            header = next(r, None)
            for row in r:
                if len(row) >= 4:
                    rows.append(row)
                    done.add((row[0], row[1]))
    return done, rows


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    done, rows = load_done()

    ym = os.environ.get("YM", "").strip()
    if ym:
        y = int(ym[:4]); mo = int(ym[4:6])
        start = datetime.date(y, mo, 1)
        if mo == 12:
            nxt = datetime.date(y + 1, 1, 1)
        else:
            nxt = datetime.date(y, mo + 1, 1)
        days = [start + datetime.timedelta(d) for d in range((nxt - start).days)]
    else:
        n = int(os.environ.get("DAYS", "365"))
        today = datetime.date.today()
        days = [today - datetime.timedelta(d) for d in range(1, n + 1)]

    got = 0
    for d in days:
        hd = d.strftime("%Y%m%d")
        if (hd, "1") in done:
            continue
        try:
            raw = fetch_lzh(d)
            recs = parse_kiryu(raw)
        except Exception as e:
            print("skip", hd, repr(e))
            time.sleep(SLEEP)
            continue
        if recs:
            for rno, combo, payout in recs:
                rows.append([hd, str(rno), combo, str(payout)])
            got += len(recs)
            print("ok", hd, len(recs))
        time.sleep(SLEEP)

    rows.sort(key=lambda x: (x[0], int(x[1])))
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hd", "rno", "combo", "payout"])
        w.writerows(rows)
    print("done. new records:", got, "total:", len(rows))


if __name__ == "__main__":
    main()
