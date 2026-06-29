# -*- coding: utf-8 -*-
import io
import os
import csv
import json

CSV_PATH = os.path.join("docs", "payouts", "tokuyamaPayouts.csv")
OUT = os.path.join("docs", "payouts", "tokuyamaManRate.json")

MAN = 10000  # 万舟しきい値（10000円超）


def main():
    # rno -> [total, man_count, sum_payout, max_payout]
    stats = {}
    total_races = 0

    with io.open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 4:
                continue
            rno = int(row[1])
            payout = int(row[3])
            s = stats.setdefault(rno, [0, 0, 0, 0])
            s[0] += 1
            if payout > MAN:
                s[1] += 1
            s[2] += payout
            if payout > s[3]:
                s[3] = payout
            total_races += 1

    races = []
    for rno in range(1, 13):
        if rno not in stats:
            continue
        total, man, ssum, smax = stats[rno]
        races.append({
            "rno": rno,
            "races": total,
            "manCount": man,
            "manRate": round(man / total * 100, 1) if total else 0.0,
            "avgPayout": round(ssum / total) if total else 0,
            "maxPayout": smax,
        })

    out = {
        "stadium": "徳山",
        "jcd": 18,
        "threshold": MAN,
        "totalRaces": total_races,
        "races": races,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False, indent=2))

    print("total races:", total_races)


if __name__ == "__main__":
    main()
