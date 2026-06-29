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
SLEEP = 1.0

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def fetch(hd, rno):
    url = "{0}?rno={1}&jcd={2}&hd={3}".format(BASE, rno, JCD, hd)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return raw.decode("utf-8", "ignore")
        except Exception:
            time.sleep(2.0)
    return None


# HTML実体参照を正規化
def normalize(html):
    html = html.replace("&yen;", "\uffe5").replace("&#165;", "\uffe5")
    html = html.replace("\uff13", "3")  # 全角3 -> 半角
    return html


# 3連単: 「3連単」の後、最初に現れる X-X-X を組番、その後最初の数字列(>=3桁)を払戻とする
COMBO = re.compile(r"3\u9023\u5358(.*?)(\d)-(\d)-(\d)(.*)", re.S)
# 払戻金は ¥ 有無に関わらず、組番の後で最初に出る3桁以上の数字（カンマ込み）
MONEY = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,})")


def parse_payout(html):
    if html is None:
        return None
    html = normalize(html)
    m = COMBO.search(html)
    if not m:
        return None
    combo = m.group(2) + "-" + m.group(3) + "-" + m.group(4)
    after = m.group(5)
    mm = MONEY.search(after)
    if not mm:
        return None
    yen = int(mm.group(1).replace(",", ""))
    # 妥当性: 100円以上(=最低配当ありうる) かつ 1000万未満
    if yen < 100 or yen > 9999999:
        return None
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
    fetched_ok = 0      # HTMLが取れた回数
    parse_fail = 0      # 取れたがパース失敗した回数
    sample_dumped = False
    while d <= today:
        hd = d.strftime("%Y%m%d")
        for rno in range(1, 13):
            if (hd, str(rno)) in done:
                continue
            html = fetch(hd, rno)
            time.sleep(SLEEP)
            if html:
                fetched_ok += 1
            res = parse_payout(html)
            if res is None:
                # 取れているのにパース不能な最初の1件だけHTML冒頭を出す
                if html and not sample_dumped and ("3\u9023\u5358" in html):
                    print("=== SAMPLE (3rentan found but parse failed) hd=%s rno=%d ===" % (hd, rno))
                    idx = html.find("3\u9023\u5358")
                    print(html[idx:idx + 300])
                    print("=== END SAMPLE ===")
                    sample_dumped = True
                if html:
                    parse_fail += 1
                continue
            combo, yen = res
            writer.writerow([hd, rno, combo, yen])
            out.flush()
            collected += 1
        d += datetime.timedelta(days=1)

    out.close()
    print("collected:", collected, "fetched_ok:", fetched_ok, "parse_fail:", parse_fail)


if __name__ == "__main__":
    main()
