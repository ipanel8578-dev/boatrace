# -*- coding: utf-8 -*-
# 徳山(jcd=18) 3連単払戻 収集スクレイパー（公式競走成績配布版）
# mbrace.or.jp の競走成績配布(LZH)を1日1ファイル取得・解凍し、徳山の払戻金を抽出。
# スクレイピング不要。1日1ファイルなので安定。徳山非開催日は自動スキップ。
# 環境変数 YM 指定でその月のみ、DAYS 指定で遡る日数を変更可。
import io
import os
import re
import csv
import time
import datetime
import urllib.request

BASE = "http://www1.mbrace.or.jp/od2/K/"
OUT = os.path.join("docs", "payouts", "tokuyamaPayouts.csv")
SLEEP = 1.0  # サーバ負荷軽減（高速版）
DAYS_BACK = 365

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) boatrace-data-collector"

TOKU = "\u5fb3\u3000\u5c71\uff3b\u6210\u7e3e\uff3d"   # 徳　山［成績］
SEISEKI = "\uff3b\u6210\u7e3e\uff3d"                  # ［成績］
PAY = "\u6255\u623b\u91d1"                            # 払戻金
PAYLINE = re.compile(r"\s*(\d{1,2})R\s+(\d)-(\d)-(\d)\s+(\d+)")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read()
    except Exception:
        return None


def extract_tokuyama(txt):
    """SJISデコード済みテキストから徳山の (rno, combo, payout) を返す"""
    out = []
    in_toku = False
    in_pay = False
    for ln in txt.split("\n"):
        if SEISEKI in ln:
            in_toku = TOKU in ln
            in_pay = False
            continue
        if not in_toku:
            continue
        if PAY in ln:
            in_pay = True
            continue
        if in_pay:
            m = PAYLINE.match(ln)
            if m:
                rno = int(m.group(1))
                combo = m.group(2) + "-" + m.group(3) + "-" + m.group(4)
                payout = int(m.group(5))
                out.append((rno, combo, payout))
            elif out and not re.search(r"\d", ln):
                in_pay = False
    return out


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


def date_list():
    ym = os.environ.get("YM", "").strip()
    today = datetime.date.today()
    if ym:
        y, m = int(ym[0:4]), int(ym[4:6])
        d = datetime.date(y, m, 1)
        out = []
        while d.month == m and d <= today:
            out.append(d)
            d += datetime.timedelta(days=1)
        return out
    days = int(os.environ.get("DAYS", str(DAYS_BACK)))
    start = today - datetime.timedelta(days=days)
    out = []
    d = start
    while d <= today:
        out.append(d)
        d += datetime.timedelta(days=1)
    return out


def main():
    import lhafile
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    done = load_done()
    new_file = not os.path.exists(OUT)
    out = io.open(OUT, "a", encoding="utf-8", newline="")
    writer = csv.writer(out)
    if new_file:
        writer.writerow(["hd", "rno", "combo", "payout"])

    collected = 0
    days_with_data = 0
    for d in date_list():
        hd = d.strftime("%Y%m%d")
        # この日が既に全レース取得済みならスキップ
        if (hd, "1") in done and (hd, "12") in done:
            continue
        yyyymm = d.strftime("%Y%m")
        yymmdd = d.strftime("%y%m%d")
        url = "{0}{1}/k{2}.lzh".format(BASE, yyyymm, yymmdd)
        raw = fetch(url)
        time.sleep(SLEEP)
        if not raw or len(raw) < 100:
            continue
        # LZH解凍
        tmp = "/tmp/k%s.lzh" % yymmdd
        open(tmp, "wb").write(raw)
        try:
            a = lhafile.Lhafile(tmp)
            name = a.infolist()[0].filename
            data = a.read(name)
        except Exception:
            continue
        txt = data.decode("shift_jis", "ignore")
        rows = extract_tokuyama(txt)
        if rows:
            days_with_data += 1
        for rno, combo, payout in rows:
            if (hd, str(rno)) in done:
                continue
            writer.writerow([hd, rno, combo, payout])
            out.flush()
            collected += 1

    out.close()
    print("collected:", collected, "days_with_tokuyama:", days_with_data)


if __name__ == "__main__":
    main()
