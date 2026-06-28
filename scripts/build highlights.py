#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_highlights.py
出走表CSV＋モーターCSVを読み、本日の見どころ・展開文を計算して highlights.json に出力する。
ロジックは tenkai_logic.json の方針に準拠（買い目・確率・勝者断定・内心推測は出さない）。
使い方:
  python build_highlights.py [racers_csv] [motors_csv] [out_json]
  省略時: docs/racers/racers_today.csv  docs/motor/motors_all.csv  docs/highlights/highlights.json
"""
import csv, json, sys, datetime
from collections import defaultdict

RACERS = sys.argv[1] if len(sys.argv) > 1 else "docs/racers/racers_today.csv"
MOTORS = sys.argv[2] if len(sys.argv) > 2 else "docs/motor/motors_all.csv"
OUT    = sys.argv[3] if len(sys.argv) > 3 else "docs/highlights/highlights.json"

INTOP = {'大村':63,'徳山':62,'芦屋':64,'尼崎':62,'下関':60,'常滑':58,'住之江':55,'丸亀':56,
         '児島':55,'唐津':56,'若松':55,'宮島':54,'浜名湖':54,'三国':53,'蒲郡':54,'福岡':52,
         '鳴門':52,'びわこ':51,'多摩川':54,'平和島':50,'戸田':49,'津':54,'桐生':53,'江戸川':48}
CONFIRMED = {'尼崎','徳山','芦屋','下関','大村','常滑'}
MAKURI = {'戸田','江戸川','びわこ','平和島'}
K = '①②③④⑤⑥'

def f(x):
    try: return float(x)
    except: return 0.0

def nm(s): return s.replace('\u3000', '')

def load_csv(path):
    with open(path, encoding='utf-8-sig') as fp:
        return list(csv.DictReader(fp))

def main():
    rac = load_csv(RACERS)
    try:
        mot = load_csv(MOTORS)
    except Exception:
        mot = []
    mkey = {(m['場コード'], m['登録番号']): f(m['モーター2連対率']) for m in mot}
    # 場ごと0%率でモーター使用可否
    zero = defaultdict(lambda: [0, 0])
    for m in mot:
        zero[m['場名']][1] += 1
        if f(m['モーター2連対率']) == 0: zero[m['場名']][0] += 1
    motok = {k: (z/t < 0.4) for k, (z, t) in zero.items()}

    for r in rac:
        r['_mtr'] = mkey.get((r['場コード'], r['登録番号']), 0.0)

    races = defaultdict(list)
    for r in rac:
        races[(r['場名'], r['レース'])].append(r)

    out_races = []
    for (ba, rc), bo in races.items():
        if len(bo) != 6: continue
        bo.sort(key=lambda b: int(b['枠']))
        it = INTOP.get(ba, 53)
        use_m = motok.get(ba, True)
        mt = [b['_mtr'] for b in bo]
        valid = [v for v in mt if v > 0]
        mavg = sum(valid)/len(valid) if valid else None
        hi = lambda v: use_m and mavg and v > 0 and v > mavg+5
        lo = lambda v: use_m and mavg and v > 0 and v < mavg-5

        in1 = bo[0]; il = f(in1['当地勝率']); ina = f(in1['全国勝率'])
        inA = in1['級別'] in ('A1', 'A2')
        in_lo = lo(mt[0])
        in_strong = inA and il > ina and il > 0 and not in_lo
        in_weak = (in1['級別'] in ('B1', 'B2')) or (il > 0 and il < ina) or in_lo

        seeds = 0
        if in_weak: seeds += 1
        threats = []; out_hi = False
        for i, b in enumerate(bo):
            w = int(b['枠']); lv = b['級別']; loc = f(b['当地勝率']); nat = f(b['全国勝率']); st = f(b['平均ST'])
            a_out = w >= 4 and lv in ('A1', 'A2')
            local_out = w >= 3 and loc > 0 and loc > nat
            if a_out or local_out:
                seeds += 1
                threats.append({'w': w, 'lv': lv, 'st': st, 'a_out': a_out,
                                'local_out': local_out, 'mhi': hi(mt[i]), 'nm': nm(b['氏名'])})
            if w >= 4 and hi(mt[i]): out_hi = True
        if in_lo and out_hi: seeds += 1
        if it >= 60: seeds = max(0, seeds-1)
        elif it <= 50: seeds += 1
        if ba in MAKURI: seeds += 1

        # --- 見立て見出し（断定しない） ---
        o4 = sorted([t for t in threats if t['w'] >= 4], key=lambda x: x['w'])
        inn = sorted([t for t in threats if t['w'] < 4], key=lambda x: x['w'])
        if in_strong:
            headline = f"①{nm(in1['氏名'])}の逃げが軸。外の一発をどこまで測るか"
        elif in_weak and o4:
            headline = f"①に不安、{K[o4[0]['w']-1]}{o4[0]['nm']}のまくりが主役候補"
        elif in_weak and inn:
            headline = f"①に不安、{K[inn[0]['w']-1]}{inn[0]['nm']}の差しが突け入る一戦"
        elif in_weak:
            headline = "①に不安、外の仕掛け待ちで波乱含み"
        elif o4:
            headline = f"①の出方ひとつ、{K[o4[0]['w']-1]}{o4[0]['nm']}のまくりと連動"
        else:
            headline = "①の先マイが軸、こじれれば内の差しが浮上"

        # --- 展開の筋（複数併置） ---
        tenkai = []
        m1 = '機力は場上位' if hi(mt[0]) else '機力は場下位' if lo(mt[0]) else ('機力は場平均並み' if use_m and mt[0] > 0 else '')
        in_f = int(in1['F数']) >= 1
        if in_strong:
            tenkai.append(f"①{nm(in1['氏名'])}はA級・当地巧者{('で'+m1) if m1 else ''}。②③が壁を作れば逃げの軸として信頼度は高い構図。")
        elif in_weak:
            why = []
            if not inA: why.append('格')
            if il > 0 and il < ina: why.append('当地')
            if in_lo: why.append('機力')
            tenkai.append(f"①{nm(in1['氏名'])}は{'・'.join(why)}で見劣り{('（F持ちで踏み込みにくい）') if in_f else ''}。先マイを許さなければ外に主導権が渡る余地。")
        else:
            tenkai.append(f"①{nm(in1['氏名'])}は標準評価{('（'+m1+'）') if m1 else ''}。スタートが決まれば逃げ、遅れれば外に付け入る隙。")
        th2 = sorted(threats, key=lambda t: (t['st'] if t['st'] > 0 else 9, t['w']))[:2]
        for t in th2:
            role = '外枠のダッシュ勢' if t['w'] >= 4 else '内寄りの一角'
            kim = 'まくり' if t['w'] >= 4 else '差し・まくり差し'
            ex = []
            if t['local_out']: ex.append('当地巧者')
            if t['a_out']: ex.append('A級')
            if t['mhi']: ex.append('機力上位')
            if t['st'] > 0 and t['st'] <= 0.15: ex.append('鋭ST')
            tenkai.append(f"{K[t['w']-1]}{t['nm']}は{role}（{'・'.join(ex)}）。スタートが決まれば{kim}の主役になりうる。")
        if not threats and not in_weak:
            tenkai.append("外に目立った脅威は乏しく、隊形どおりなら波乱の芽は薄い。")
        if in_weak or any(t['w'] >= 4 for t in threats):
            tenkai.append("スタートが揃えば①主導、内が遅れれば外まくり——の二択で見たい一戦。")

        # --- 波及の連鎖 ---
        out4 = any(t['w'] >= 4 for t in threats)
        if in_strong or (not in_weak and not out4):
            suji = "①が先マイを決めれば②③が続く筋。壁が崩れない限り波及は内で収まる。"
        elif out4:
            suji = "外が仕掛ければ②③は外に張られ、空いた内を⑤や逃げ残りの①が拾う波及。外決着なら内の連は薄れる。"
        else:
            suji = "②が差し込めば①は先頭を譲っても2着に残りやすく、③が続く形。"

        boats = []
        for b in bo:
            w = int(b['枠']); loc = f(b['当地勝率']); nat = f(b['全国勝率']); st = f(b['平均ST']); mv = b['_mtr']
            mev = 'na'
            if use_m and mv > 0:
                mev = 'hi' if hi(mv) else 'lo' if lo(mv) else 'mid'
            boats.append({
                '枠': w, '登録番号': b['登録番号'], '支部': b.get('支部',''), '級別': b['級別'], '氏名': nm(b['氏名']),
                '全国勝率': round(nat, 2), '当地勝率': round(loc, 2),
                '機力': round(mv, 1) if (use_m and mv > 0) else None, '機力評価': mev,
                'F': int(b['F数']) >= 1, '鋭ST': st > 0 and st <= 0.15,
                '当地優位': loc > 0 and loc > nat
            })

        out_races.append({
            '場名': ba, '場コード': bo[0]['場コード'], 'レース': rc,
            '締切時刻': bo[0].get('締切時刻', ''),
            '波乱': seeds, 'イン堅': in_strong, 'モーター使用': use_m, 'イン1着率': it,
            '艇': boats, '見立て': headline, '展開': tenkai, '波及': suji
        })

    kaisai = rac[0]['開催日'] if rac else ''
    doc = {
        '生成時刻': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec='seconds'),
        '開催日': kaisai,
        '確定イン率場': sorted(CONFIRMED),
        'レース数': len(out_races),
        'レース': out_races
    }
    import os
    out_dir = os.path.dirname(OUT)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    prev_path = os.path.join(out_dir, 'highlights_prev.json') if out_dir else 'highlights_prev.json'
    try:
        with open(OUT, 'r', encoding='utf-8') as pf:
            old_doc = json.load(pf)
        if old_doc.get('開催日') and old_doc.get('開催日') != kaisai:
            with open(prev_path, 'w', encoding='utf-8') as pf:
                json.dump(old_doc, pf, ensure_ascii=False, separators=(',', ':'))
    except FileNotFoundError:
        pass
    except Exception:
        pass
    with open(OUT, 'w', encoding='utf-8') as fp:
        json.dump(doc, fp, ensure_ascii=False, separators=(',', ':'))
    print(f"OK: {len(out_races)}レース → {OUT}")

if __name__ == '__main__':
    main()
