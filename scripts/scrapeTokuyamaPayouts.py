# -*- coding: utf-8 -*-
import io
import os
import re
import csv
import time
import datetime
import urllib.request

JCD = 18  # tokuyama
BASE = "https://www.boatrace.jp/owpc/pc/race/raceresult"
OUT = os.path.join("docs", "payouts", "tokuyamaPayouts.csv")
SLEEP = 1.0  # seconds between requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) boatrace-data-collector"


def fetch(hd, rno):
    url = "{0}?rno={1}&jcd={2}&hd={3}".format(BASE, rno, JCD, hd)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception:
            time.sleep(2.0)
    return None


# 3連単の払戻金を抜く。行の構造: 3連単 | 1-2-3 | ¥12,340 | 人気
PAT = re.compile(r"3\u9023\u5358.*?(\d-\d-\d).*?\uffe5([\d,]+)", re.S)


def parse_payout(html):
    if html is None:
        return None
    # 結果が無い日（未開催）は組番が出ない
    m = PAT.search(html)
    if not m:
        return None
    combo = m.group(1)
    yen = int(m.group(2).replace(",", ""))
    return combo, yen


def load_done():
    done = set()
    if os.path.exists(OUT):
        with io.open(OUT, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) >= 2:
                    done.add((row[0], row[1]))
    return done


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    done = load_done()

    new_file = not os.path.exists(OUT)
    out = io.open(OUT, "a", encoding="utf-8", newline="")
    writer = csv.writer(out)
    if new_file:
        writer.writerow(["hd", "rno", "combo", "payout"])

    today = datetime.date.today()
    start = today - datetime.timedelta(days=365)

    d = start
    collected = 0
    while d <= today:
        hd = d.strftime("%Y%m%d")
        for rno in range(1, 13):
            if (hd, str(rno)) in done:
                continue
            html = fetch(hd, rno)
            time.sleep(SLEEP)
            res = parse_payout(html)
            if res is None:
                # 1Rで結果なし＝その日は未開催の可能性が高い→残りRを飛ばす
                if rno == 1:
                    break
                continue
            combo, yen = res
            writer.writerow([hd, rno, combo, yen])
            out.flush()
            collected += 1
        d += datetime.timedelta(days=1)

    out.close()
    print("collected:", collected)


if __name__ == "__main__":
    main()
