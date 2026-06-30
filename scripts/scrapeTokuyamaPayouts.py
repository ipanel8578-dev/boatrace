# -*- coding: utf-8 -*-
# 徳山(jcd=18) 3連単払戻 収集スクレイパー（完成版）
# 1) 過去12ヶ月の月間スケジュールから徳山の開催初日を自動抽出
# 2) 各節を初日+6日展開して開催候補日を作る
# 3) 候補日の各レース結果を取得。返ってきたページが徳山(jcd=18)か検証してから採用
# 環境変数 YM 指定でその月だけ処理も可能（手動回収用）
import io
import os
import re
import csv
import time
import datetime
import urllib.request

JCD = 18
RESULT = "https://www.boatrace.jp/owpc/pc/race/raceresult"
SCHED = "https://www.boatrace.jp/owpc/pc/race/monthlyschedule"
OUT = os.path.join("docs", "payouts", "tokuyamaPayouts.csv")
SLEEP = 0.4
MONTHS_BACK = 12

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception:
            if attempt == 0:
                time.sleep(0.6)
    return None


SCHED_HD = re.compile(r"jcd=18&hd=(\d{8})")


def kaisai_first_days(ym):
    html = get("{0}?ym={1}".format(SCHED, ym))
    if not html:
        return []
    return sorted(set(SCHED_HD.findall(html)))


def normalize(html):
    return html.replace("&yen;", "\uffe5").replace("&#165;", "\uffe5").replace("\uff13", "3")


COMBO = re.compile(r"3\u9023\u5358(.*?)(\d)-(\d)-(\d)(.*)", re.S)
MONEY = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,})")
# 返ってきたページが徳山のものか判定（徳山リンクが本文にあるか）
IS_TOKUYAMA = re.compile(r"jcd=18&hd=")


def parse_payout(html, hd):
    if html is None:
        return None
    html = normalize(html)
    # 別場ページが返ってきた場合を弾く: 徳山(jcd=18)のページか
    # 結果ページのパンくず/ナビに jcd=18 が含まれる。日付一致までは求めない。
    if "jcd=18" not in html:
        return None
    m = COMBO.search(html)
    if not m:
        return None
    combo = m.group(2) + "-" + m.group(3) + "-" + m.group(4)
    mm = MONEY.search(m.group(5))
    if not mm:
        return None
    yen = int(mm.group(1).replace(",", ""))
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


def months_list():
    ym = os.environ.get("YM", "").strip()
    if ym:
        return [ym]
    today = datetime.date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(MONTHS_BACK + 1):
        out.append("%04d%02d" % (y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return out


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    done = load_done()
    new_file = not os.path.exists(OUT)
    out = io.open(OUT, "a", encoding="utf-8", newline="")
    writer = csv.writer(out)
    if new_file:
        writer.writerow(["hd", "rno", "combo", "payout"])

    today = datetime.date.today()

    # 開催候補日を作る
    candidates = set()
    for ym in months_list():
        for s in kaisai_first_days(ym):
            time.sleep(SLEEP)
            d0 = datetime.date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
            for off in range(0, 7):  # 初日+6日
                d = d0 + datetime.timedelta(days=off)
                if d <= today:
                    candidates.add(d.strftime("%Y%m%d"))

    collected = 0
    dbg = 0
    for hd in sorted(candidates):
        day_hit = 0
        for rno in range(1, 13):
            if (hd, str(rno)) in done:
                day_hit += 1
                continue
            html = get("{0}?rno={1}&jcd={2}&hd={3}".format(RESULT, rno, JCD, hd))
            time.sleep(SLEEP)
            # 最初の8リクエストの状況をログ
            if dbg < 8:
                if html is None:
                    print("DBG hd=%s rno=%d : html=None(取得失敗)" % (hd, rno))
                else:
                    has18 = "jcd=18" in html
                    has3 = "3\u9023\u5358" in html
                    print("DBG hd=%s rno=%d : len=%d jcd18=%s 3rentan=%s" % (hd, rno, len(html), has18, has3))
                dbg += 1
            res = parse_payout(html, hd)
            if res is None:
                # 1R・2Rとも取れなければその候補日は非開催とみなしスキップ
                if rno == 2 and day_hit == 0:
                    break
                continue
            combo, yen = res
            writer.writerow([hd, rno, combo, yen])
            out.flush()
            collected += 1
            day_hit += 1

    out.close()
    print("collected:", collected, "candidate_days:", len(candidates))


if __name__ == "__main__":
    main()
