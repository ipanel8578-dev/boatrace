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
KIM    = sys.argv[4] if len(sys.argv) > 4 else "docs/players/racerKimarite.csv"

INTOP = {'大村':63,'徳山':62,'芦屋':64,'尼崎':62,'下関':60,'常滑':58,'住之江':55,'丸亀':56,
         '児島':55,'唐津':56,'若松':55,'宮島':54,'浜名湖':54,'三国':53,'蒲郡':54,'福岡':52,
         '鳴門':52,'びわこ':51,'多摩川':54,'平和島':50,'戸田':49,'津':54,'桐生':53,'江戸川':48}
CONFIRMED = {'尼崎','徳山','芦屋','下関','大村','常滑'}
MAKURI = {'戸田','江戸川','びわこ','平和島'}
K = '①②③④⑤⑥'

# --- 場特性の1行目（24場・断定しない範囲で水面の傾向のみ）---
# in天国(it>=58)/狭水面まくり場(MAKURI)/差し場を軸に、記者の1行目を作る。
NARROW = {'戸田','平和島','江戸川'}          # 狭い・インが残りにくい
SASHI  = {'常滑','蒲郡','児島','鳴門','丸亀'}  # うねり・差しが効きやすい傾向
def ba_line(ba, it):
    if ba in NARROW:
        return f"{ba}はインが残りにくい狭水面で、まくりの土壌がある。"
    if it >= 60:
        return f"{ba}はイン有利の水面。外が崩すには相応の材料がいる。"
    if it >= 57:
        return f"{ba}はインがしっかり残りやすい水面。"
    if ba in SASHI:
        return f"{ba}はうねりで差しが効きやすく、内の一角にも目が向く。"
    if it <= 50:
        return f"{ba}はインが盤石とは言えず、外の仕掛けが通りやすい。"
    return f"{ba}は極端に偏らない水面で、スタートの流れがものを言う。"

# --- 検証用 引き算スコア（標準化＋等重み・仮置き）---
# 重み・閾値は検証ログのスコア相関を見てから調整する。
LV = {'A1': 4, 'A2': 3, 'B1': 2, 'B2': 1}
TH_KATA = 0.09    # スコア >= +0.09 → 堅め
TH_HARAN = -0.09  # スコア <= -0.09 → 波乱（間は混戦）

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

    # --- 検証スコア用 正規化（当日全出走者でmin-max・等重み）---
    def loc_or_nat(r):
        l = f(r['当地勝率']); return l if l > 0 else f(r['全国勝率'])
    _lv = [LV.get(r['級別'], 1) for r in rac]
    _loc = [loc_or_nat(r) for r in rac]
    _st = [f(r['平均ST']) for r in rac]
    _mtp = [v for v in (mkey.get((r['場コード'], r['登録番号']), 0.0) for r in rac) if v > 0]
    lv_lo, lv_hi = (min(_lv), max(_lv)) if _lv else (1, 4)
    loc_lo, loc_hi = (min(_loc), max(_loc)) if _loc else (0.0, 1.0)
    st_lo, st_hi = (min(_st), max(_st)) if _st else (0.1, 0.3)
    mt_lo, mt_hi = (min(_mtp), max(_mtp)) if _mtp else (0.0, 1.0)
    def _nz(v, lo, hi): return (v - lo) / (hi - lo) if hi > lo else 0.5
    def total_power(r):
        parts = [_nz(LV.get(r['級別'], 1), lv_lo, lv_hi),
                 _nz(loc_or_nat(r), loc_lo, loc_hi),
                 1 - _nz(f(r['平均ST']), st_lo, st_hi)]  # STは速い(小)ほど良い→反転
        mv = mkey.get((r['場コード'], r['登録番号']), 0.0)
        if mv > 0: parts.append(_nz(mv, mt_lo, mt_hi))
        return sum(parts) / len(parts)

    # 図鑑の決まり手CSVから やられ系（さされ・まくられ・まくりさされ）を読む。
    # 旧フォーマット（列が無い）やファイル欠損でも落ちないようにする。
    def fr(x):
        try:
            return float(x)
        except Exception:
            return None
    yarare = {}
    try:
        for k in load_csv(KIM):
            in1 = k.get('イン進入数', '')
            try:
                in1 = int(in1)
            except Exception:
                in1 = 0
            yarare[k['登録番号']] = {
                'さされ率': fr(k.get('さされ率', '')),
                'まくられ率': fr(k.get('まくられ率', '')),
                'まくりさされ率': fr(k.get('まくりさされ率', '')),
                'イン数': in1,
                'まくり率': fr(k.get('まくり率', '')),
                '差し率': fr(k.get('差し率', '')),
            }
    except Exception:
        yarare = {}
    # 場ごと0%率でモーター使用可否
    zero = defaultdict(lambda: [0, 0])
    for m in mot:
        zero[m['場名']][1] += 1
        if f(m['モーター2連対率']) == 0: zero[m['場名']][0] += 1
    motok = {k: (z/t < 0.4) for k, (z, t) in zero.items()}

    for r in rac:
        r['_mtr'] = mkey.get((r['場コード'], r['登録番号']), 0.0)

    # 決まり手タイプ（まくり型/差し型/標準）。データ欠損はNone。
    def kim_type(toban):
        y = yarare.get(toban, {})
        mk = y.get('まくり率'); sa = y.get('差し率')
        if mk is None and sa is None: return None
        mk = mk or 0.0; sa = sa or 0.0
        if mk >= 25 and mk >= sa + 8: return 'makuri'
        if sa >= 30 and sa >= mk + 8: return 'sashi'
        return None

    races = defaultdict(list)
    for r in rac:
        races[(r['場名'], r['レース'])].append(r)

    out_races = []
    pred_list = []
    for (ba, rc), bo in races.items():
        if len(bo) != 6: continue
        bo.sort(key=lambda b: int(b['枠']))
        # --- 検証ログ：①総合力 − ④総合力（標準化・等重み）---
        diff = round(total_power(bo[0]) - total_power(bo[3]), 3)
        if diff >= TH_KATA:
            verdict, hero = '堅め', 1
        elif diff <= TH_HARAN:
            verdict, hero = '波乱', 4
        else:
            verdict, hero = '混戦', 4
        pred_list.append({'場名': ba, '場コード': bo[0]['場コード'], 'レース': rc,
                          '判定': verdict, '主役艇': hero, 'スコア': diff})
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
        # イン天国(it>=60)では当地/機力の見劣り単独で①不安にしない（B級のみ不安）
        if it >= 60:
            in_weak = (in1['級別'] in ('B1', 'B2'))
        else:
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

        # --- 見立て見出し（scoreトーン×主役、断定しない） ---
        # score(diff)で①中心/難解/外主役のトーンを決め、その上に主役艇名を乗せる。
        o4 = sorted([t for t in threats if t['w'] >= 4], key=lambda x: x['w'])
        inn = sorted([t for t in threats if t['w'] < 4], key=lambda x: x['w'])
        head_w = None
        if in_strong and diff >= TH_KATA:
            headline = f"①{nm(in1['氏名'])}中心。外の一発をどこまで測るか"
        elif in_weak and diff <= TH_HARAN and o4:
            headline = f"イン薄く外が主役。{K[o4[0]['w']-1]}{o4[0]['nm']}のまくりが本線候補"
            head_w = o4[0]['w']
        elif in_strong:
            headline = f"①{nm(in1['氏名'])}の逃げが軸。外の一発をどこまで測るか"
        elif in_weak and o4:
            headline = f"①に不安、{K[o4[0]['w']-1]}{o4[0]['nm']}のまくりが主役候補"
            head_w = o4[0]['w']
        elif in_weak and inn:
            headline = f"①に不安、{K[inn[0]['w']-1]}{inn[0]['nm']}の差しが突け入る一戦"
            head_w = inn[0]['w']
        elif in_weak:
            headline = "①に不安、外の仕掛け待ちで波乱含み"
        elif o4:
            headline = f"①の出方ひとつ、{K[o4[0]['w']-1]}{o4[0]['nm']}のまくりと連動"
            head_w = o4[0]['w']
        else:
            headline = "軸を絞りにくい難解戦。展示のSで傾きを見たい"

        # --- 展開の筋（記者文型：場特性→①〜したい〜だが→主役決まり手×場特性→死角）---
        tenkai = []
        # 〔場〕1行目に場特性（実装テーブルA①）
        tenkai.append(ba_line(ba, it))

        # 〔軸＋死角〕①を「〜したい〜だが」で（実装テーブルA②：級別×機力×当地で分岐）
        m1 = '機力は場上位' if hi(mt[0]) else '機力は場下位' if lo(mt[0]) else ('機力は場平均並み' if use_m and mt[0] > 0 else '')
        in_f = int(in1['F数']) >= 1
        in_kt = kim_type(in1['登録番号'])
        if in_strong:
            extra = ""
            if ba in NARROW or (it >= 60):
                extra = "水面もイン向きで、"
            tenkai.append(f"逃げたい①{nm(in1['氏名'])}はA級・当地巧者{('で'+m1) if m1 else ''}。{extra}②③が壁を作れば主導権は譲りにくい。")
        elif in_weak:
            why = []
            if not inA: why.append('格')
            if il > 0 and il < ina: why.append('当地')
            if in_lo: why.append('機力')
            reason = '・'.join(why) if why else '総合力'
            fnote = '（F持ちで踏み込みにくく）' if in_f else ''
            tenkai.append(f"逃げたい①{nm(in1['氏名'])}だが{reason}で見劣り{fnote}、押し切りには不安。先マイを許さなければ外に主導権が渡る。")
        else:
            tenkai.append(f"逃げたい①{nm(in1['氏名'])}は標準評価{('（'+m1+'）') if m1 else ''}。Sが決まれば逃げ、遅れれば外に付け入る隙が生まれる。")

        # 〔主役〕見出しの主役艇を先頭に、次点はST順（見出しと展開のズレを防ぐ）
        th_sorted = sorted(threats, key=lambda t: (t['st'] if t['st'] > 0 else 9, t['w']))
        if head_w is not None:
            head_t = [t for t in threats if t['w'] == head_w]
            rest = [t for t in th_sorted if t['w'] != head_w]
            th2 = (head_t + rest)[:2]
        else:
            th2 = th_sorted[:2]
        toban_by_w = {int(b['枠']): b['登録番号'] for b in bo}
        for idx, t in enumerate(th2):
            role = '外枠のダッシュ勢' if t['w'] >= 4 else '内寄りの一角'
            ex = []
            if t['local_out']: ex.append('当地巧者')
            if t['a_out']: ex.append('A級')
            if t['mhi']: ex.append('機力上位')
            if t['st'] > 0 and t['st'] <= 0.15: ex.append('鋭ST')
            exs = ('（'+'・'.join(ex)+'）') if ex else ''
            kt = kim_type(toban_by_w.get(t['w'], ''))
            # 決まり手タイプ×場特性の噛み合い一言＋言い切る決まり手をタイプで決める
            fit = ''
            if t['w'] >= 4:
                # 外枠の基本はまくりだが、差し型ならまくり差しに寄せる
                base_kim = 'まくり差し' if kt == 'sashi' else 'まくり'
                if kt == 'makuri':
                    if ba in NARROW: fit = 'まくり型で狭水面と噛み合い、'
                    elif it >= 58:   fit = 'まくり型だが差しの利く水面で割り引きたく、'
                    else:            fit = 'まくり型の持ち味を出しやすく、'
                elif kt == 'sashi':
                    fit = '差し型で、内が動いた隙を突く形なら、'
            else:
                base_kim = '差し・まくり差し'
                if kt == 'sashi':
                    fit = '差し型が水を得やすく、'
                elif kt == 'makuri':
                    fit = 'まくり型で一発の破壊力があり、'
            lead = '主役は' if idx == 0 else 'これに次ぐのが'
            tenkai.append(f"{lead}{K[t['w']-1]}{t['nm']}{exs}。{fit}Sが決まれば{base_kim}の主役になりうる。")

        # 〔死角〕必ず1つ（実装テーブルA④：F・級・機力から。同文を避け条件で散らす）
        saten = None
        f_out = [t for t in threats if t['w'] >= 4 and int(bo[t['w']-1]['F数']) >= 1]
        f_in  = [b for b in bo if int(b['枠']) in (2,3) and int(b['F数']) >= 1]
        o4top = o4[0] if o4 else None
        o4kt = kim_type(toban_by_w.get(o4top['w'], '')) if o4top else None
        if f_out:
            t = f_out[0]
            saten = f"死角は{K[t['w']-1]}のF。慎重Sならまくり不発で①が残る目も出てくる。"
        elif f_in:
            saten = f"死角は内のF。慎重Sは外を後押しもするが、手堅く回れば①が立つ余地も残る。"
        elif in_strong:
            saten = "①がSを決め先マイすれば、地力で押し切る本線も濃い。"
        elif any(t['mhi'] for t in threats if t['w'] < 4):
            mb = next(t for t in threats if t['w'] < 4 and t['mhi'])
            saten = f"警戒は{K[mb['w']-1]}。機力上位で差し・まくり差しに動け、外の隙に連へ食い込む。"
        elif in_weak:
            # ①不安時の死角を、弱点理由×外主役の決まり手で分岐（同文回避）
            wl = []
            if not inA: wl.append('格')
            if il > 0 and il < ina: wl.append('当地')
            if in_lo: wl.append('機力')
            if o4top and o4kt == 'makuri' and ba in NARROW:
                saten = f"死角は⑥までの一気。狭水面で{K[o4top['w']-1]}のまくりが決まれば、内は総崩れの目もある。"
            elif o4top and o4kt == 'makuri':
                saten = f"死角は{K[o4top['w']-1]}の握り込み。まくりが決まりきれば内の粘りごと連れ去る一撃もある。"
            elif o4top and o4kt == 'sashi':
                saten = f"死角は{K[o4top['w']-1]}の差し損じ。踏み込みが甘ければ①が粘り込む展開に振れる。"
            elif in_lo:
                saten = "死角は①の船足。伸びが戻れば見立てほど脆くはなく、逃げ残りも一考。"
            elif '格' in wl and '当地' not in wl:
                saten = "死角は①の地元利。格は下でもSさえ五分なら、押し切って波乱を消す目も残る。"
            elif '当地' in wl:
                saten = "死角は①の当地慣れ。水面相性が出れば数字以上に粘り、連の一角に残る目も。"
            else:
                saten = "死角は①の粘り。Sが五分なら外の攻めが不発になり、①残しもある。"
        elif any(t['w'] >= 4 for t in threats):
            saten = "死角は外の仕掛け。Sが一枚決まれば隊形が乱れ、内の信頼は一気に揺らぐ。"
        else:
            saten = "内が壁を作れば波及は内で収まり、荒れの芽は限られる。"
        tenkai.append(saten)

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
            y = yarare.get(b['登録番号'], {})
            boats.append({
                '枠': w, '登録番号': b['登録番号'], '支部': b.get('支部',''), '級別': b['級別'], '氏名': nm(b['氏名']),
                '全国勝率': round(nat, 2), '当地勝率': round(loc, 2),
                '機力': round(mv, 1) if (use_m and mv > 0) else None, '機力評価': mev,
                'F': int(b['F数']) >= 1, '鋭ST': st > 0 and st <= 0.15,
                '当地優位': loc > 0 and loc > nat,
                'さされ率': y.get('さされ率'), 'まくられ率': y.get('まくられ率'),
                'まくりさされ率': y.get('まくりさされ率'), 'イン数': y.get('イン数')
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
    # 壁時計（JST）が今日になっている開催日のときだけ当日を書き換える。
    # 出走表が夜に翌日分へ更新されても、当日タブを前倒しで繰り上げない。
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y%m%d')
    if kaisai != today:
        print(f"SKIP: 開催日{kaisai} != 本日{today}（当日を保持）")
        return
    import os
    out_dir = os.path.dirname(OUT)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    prev_path = os.path.join(out_dir, 'highlights_prev.json') if out_dir else 'highlights_prev.json'
    prev2_path = os.path.join(out_dir, 'highlights_prev2.json') if out_dir else 'highlights_prev2.json'
    try:
        with open(OUT, 'r', encoding='utf-8') as pf:
            old_doc = json.load(pf)
        if old_doc.get('開催日') and old_doc.get('開催日') != kaisai:
            if os.path.exists(prev_path):
                os.replace(prev_path, prev2_path)
            with open(prev_path, 'w', encoding='utf-8') as pf:
                json.dump(old_doc, pf, ensure_ascii=False, separators=(',', ':'))
    except FileNotFoundError:
        pass
    except Exception:
        pass
    with open(OUT, 'w', encoding='utf-8') as fp:
        json.dump(doc, fp, ensure_ascii=False, separators=(',', ':'))
    print(f"OK: {len(out_races)}レース → {OUT}")

    # --- 検証ログ：予測を確定保存（結果を見る前・一度書いたら動かさない）---
    # 公開highlights.jsonには判定/主役艇を入れず、非公開predictions/にだけ残す。
    if pred_list:
        os.makedirs('predictions', exist_ok=True)
        pred_path = os.path.join('predictions', f'{kaisai}.json')
        if os.path.exists(pred_path):
            print(f"PRED skip: {pred_path} 既存（予測は動かさない）")
        else:
            pred_doc = {'開催日': kaisai, '生成時刻': doc['生成時刻'],
                        '閾値': {'堅め': TH_KATA, '波乱': TH_HARAN},
                        '予測': pred_list}
            with open(pred_path, 'w', encoding='utf-8') as pf:
                json.dump(pred_doc, pf, ensure_ascii=False, separators=(',', ':'))
            print(f"PRED: {len(pred_list)}レース → {pred_path}")

if __name__ == '__main__':
    main()
