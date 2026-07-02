# -*- coding: utf-8 -*-
"""
桐生払戻CSV → R別万舟率JSON集計
入力: docs/payouts/kiryuPayouts.csv （hd, rno, combo, payout）
出力: docs/payouts/kiryuManRate.json
  - byRace: R別（1〜12）の 総数 / 万舟数(1万円以上) / 万舟率(%) / 平均配当
  - top5: 最高配当TOP5（hd, rno, combo, payout）
  - frameContribution: 1着艇番別の出現数
  - overall: 全体件数・全体万舟率・平均配当
"""
import os
import csv
import json

SRC = "docs/payouts/kiryuPayouts.csv"
OUT = "docs/payouts/kiryuManRate.json"
MAN = 10000  # 万舟の閾値（1万円以上）


def main():
    rows = []
    with open(SRC, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append({
                "hd": row["hd"],
                "rno": int(row["rno"]),
                "combo": row["combo"],
                "payout": int(row["payout"]),
            })

    by_race = {}
    for i in range(1, 13):
        by_race[i] = {"total": 0, "man": 0, "sum": 0}
    frame = {str(i): 0 for i in range(1, 7)}

    for x in rows:
        rno = x["rno"]
        if rno not in by_race:
            by_race[rno] = {"total": 0, "man": 0, "sum": 0}
        by_race[rno]["total"] += 1
        by_race[rno]["sum"] += x["payout"]
        if x["payout"] >= MAN:
            by_race[rno]["man"] += 1
        first = x["combo"].split("-")[0]
        if first in frame:
            frame[first] += 1

    by_race_out = []
    for i in sorted(by_race.keys()):
        d = by_race[i]
        t = d["total"]
        by_race_out.append({
            "rno": i,
            "total": t,
            "man": d["man"],
            "manRate": round(d["man"] / t * 100, 1) if t else 0.0,
            "avgPayout": round(d["sum"] / t) if t else 0,
        })

    top5 = sorted(rows, key=lambda x: x["payout"], reverse=True)[:5]
    top5_out = [{"hd": x["hd"], "rno": x["rno"], "combo": x["combo"], "payout": x["payout"]} for x in top5]

    total = len(rows)
    man_total = sum(1 for x in rows if x["payout"] >= MAN)
    sum_total = sum(x["payout"] for x in rows)

    result = {
        "venue": "桐生",
        "jcd": "01",
        "manThreshold": MAN,
        "overall": {
            "total": total,
            "man": man_total,
            "manRate": round(man_total / total * 100, 1) if total else 0.0,
            "avgPayout": round(sum_total / total) if total else 0,
        },
        "byRace": by_race_out,
        "frameContribution": frame,
        "top5": top5_out,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("wrote", OUT, "total", total, "manRate", result["overall"]["manRate"])


if __name__ == "__main__":
    main()
