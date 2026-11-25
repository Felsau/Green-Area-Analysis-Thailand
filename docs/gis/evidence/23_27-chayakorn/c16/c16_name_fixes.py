"""C16 (week 4): proposed Thai-name fixes for green-area-backend/data/thailand.json (NL_NAME_1) and
thailand_districts.json (name_th) from the OCHA cod-ab-tha names. Read-only on every input; writes only --out.

Pairing (the C5 rules, as C9 used them; the C5 script is taken from tag C5 with `git show`, default rule):
  * province: c5.match(adm1_name1, adm1_name, system provinces, NL_NAME_1, name). Bangkok is not matched by the
    rule (its NL_NAME_1 is wrong); it is paired by PCODE TH10 and the row says so.
  * district: within the paired province, c5.match(adm2_name1, adm2_name, system districts, name_th, name).
  * one system row pairs with one OCHA row: when two OCHA rows reach the same system row the pair whose Thai name
    matches (match_by th) is kept and the other OCHA row is one-sided; a fix is never proposed from an
    English-only pair while a Thai pair exists for that system row.
Kinds: prefix (only the prefix จังหวัด/อำเภอ/เขต differs) · spelling (equal after the C5 Thai normalisation or
at most 2 characters apart) · wrong (anything else) · missing_in_system (OCHA row with no system row) ·
not_in_ocha (system row with no OCHA row). Nothing is guessed: unmatched rows are listed, not paired.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PREFIXES = ('จังหวัด', 'อำเภอ', 'เขต')


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def strip_prefix(s):
    for p in PREFIXES:
        if s.startswith(p):
            return s[len(p):]
    return s


def kind_of(current, proposed, norm_th):
    if current == proposed:
        return None
    if strip_prefix(current) == proposed:
        return 'prefix'
    if norm_th(current) == norm_th(proposed) or lev(strip_prefix(current), proposed) <= 2:
        return 'spelling'
    return 'wrong'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, required=True, help='green-area-backend/data')
    ap.add_argument('--c5-script', type=Path, required=True)
    ap.add_argument('--c9-dir', type=Path, required=True)
    ap.add_argument('--adm1', type=Path, required=True)
    ap.add_argument('--adm2', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--stats', type=Path, required=True)
    a = ap.parse_args()
    c5 = load_module(a.c5_script, 'c5_name_map')
    sys.path.insert(0, str(a.c9_dir))
    import c9_hdx_check as c9
    norm_th, norm_en = c5.make_norms(False)
    provs = [f['properties'] for f in json.load(open(a.data / 'thailand.json', encoding='utf-8'))['features']]
    dists = [f['properties'] for f in json.load(open(a.data / 'thailand_districts.json', encoding='utf-8'))['features']]
    adm1 = [p for p, _ in c9.read_layer(a.adm1)['rows']]
    adm2 = [p for p, _ in c9.read_layer(a.adm2)['rows']]
    rows, st = [], Counter()

    def add(file, en, field, current, proposed, pcode, kind, note):
        rows.append({'file': file, 'name_en': en, 'field': field, 'current': current, 'proposed': proposed,
                     'ocha_pcode': pcode, 'kind': kind, 'note': note})
        st[f'{file}:{kind}'] += 1

    # provinces
    pmap, used = {}, defaultdict(list)
    for o in adm1:
        hit, how, why = c5.match(o['adm1_name1'], o['adm1_name'], provs, lambda c: c.get('NL_NAME_1', ''),
                                 lambda c: c['name'], norm_th, norm_en)
        if hit is None and o['adm1_pcode'] == 'TH10':
            hit, how, why = next(p for p in provs if p['name'] == 'Bangkok Metropolis'), 'pcode', why
        if hit is not None:
            used[hit['name']].append((o, how, why))
    for name, pairs in used.items():
        assert len(pairs) == 1, (name, pairs)
        o, how, why = pairs[0]
        pmap[o['adm1_pcode']] = name
        sysp = next(p for p in provs if p['name'] == name)
        k = kind_of(sysp.get('NL_NAME_1', ''), o['adm1_name1'], norm_th)
        st['provinces_paired_' + how] += 1
        if k:
            note = {'pcode': 'จับคู่ด้วย PCODE TH10 (กฎ C5 จับไม่ได้เพราะ NL_NAME_1 ในระบบผิด)',
                    'en': 'จับคู่ด้วยชื่ออังกฤษ (' + why + ')'}.get(how, 'จับคู่ด้วยชื่อไทย')
            add('thailand.json', name + ' (NAME_1 ' + sysp.get('NAME_1', '') + ')', 'NL_NAME_1',
                sysp.get('NL_NAME_1', ''), o['adm1_name1'], o['adm1_pcode'], k, note)
    for p in provs:
        if p['name'] not in used:
            add('thailand.json', p['name'], 'NL_NAME_1', p.get('NL_NAME_1', ''), '', '', 'not_in_ocha', '')
    for o in adm1:
        if o['adm1_pcode'] not in pmap:
            add('thailand.json', o['adm1_name'], 'NL_NAME_1', '', o['adm1_name1'], o['adm1_pcode'], 'missing_in_system', '')
    # districts
    hits = defaultdict(list)          # system (province, name) -> [(ocha row, how, why)]
    one_sided = []
    for o in adm2:
        prov = pmap.get(o['adm1_pcode'])
        if prov is None:
            one_sided.append((o, 'province not paired'))
            continue
        cands = [d for d in dists if d['province'] == prov]
        hit, how, why = c5.match(o['adm2_name1'], o['adm2_name'], cands, lambda c: c.get('name_th', ''),
                                 lambda c: c['name'], norm_th, norm_en)
        if hit is None:
            one_sided.append((o, why))
        else:
            hits[(hit['province'], hit['name'])].append((o, how, why))
    for key, pairs in hits.items():
        if len(pairs) > 1:
            th = [x for x in pairs if x[1] == 'th']
            keep = th[0] if len(th) == 1 else None
            st['district_collisions'] += 1
            for x in pairs:
                if x is not keep:
                    one_sided.append((x[0], f'ชนกับแถวอื่นที่ระบบ {key[1]} (เก็บคู่ที่ชื่อไทยตรง)'))
            if keep is None:
                continue
            pairs[:] = [keep]
        o, how, why = pairs[0]
        d = next(x for x in dists if (x['province'], x['name']) == key)
        st['districts_paired_' + how] += 1
        k = kind_of(d.get('name_th', ''), o['adm2_name1'], norm_th)
        if k:
            note = 'จังหวัด ' + key[0] + ' · ' + ('จับคู่ด้วยชื่อไทย' if how == 'th' else 'จับคู่ด้วยชื่ออังกฤษ (' + why + ')')
            if key[0] == 'Bangkok Metropolis':
                note += ' · จังหวัดจับคู่ด้วย PCODE TH10'
            add('thailand_districts.json', d['name'], 'name_th', d.get('name_th', ''), o['adm2_name1'], o['adm2_pcode'], k, note)
    paired = set(hits)
    for d in dists:
        if (d['province'], d['name']) not in paired or not hits[(d['province'], d['name'])]:
            add('thailand_districts.json', d['name'], 'name_th', d.get('name_th', ''), '', '', 'not_in_ocha',
                'จังหวัด ' + d['province'])
    for o, why in one_sided:
        add('thailand_districts.json', o['adm2_name'], 'name_th', '', o['adm2_name1'], o['adm2_pcode'], 'missing_in_system',
            f"จังหวัด {pmap.get(o['adm1_pcode'], o['adm1_pcode'])} · {why} · ไม่เพิ่มรูปเส้นเขต")
    # label (never pair) one-sided rows of one province that differ only by the word เมือง
    for r in rows:
        if r['file'] != 'thailand_districts.json' or r['kind'] not in ('not_in_ocha', 'missing_in_system'):
            continue
        for s in rows:
            if (s is not r and s['file'] == r['file'] and {r['kind'], s['kind']} == {'not_in_ocha', 'missing_in_system'}
                    and s['note'].split(' · ')[0] == r['note'].split(' · ')[0]
                    and (r['current'] or r['proposed']).removeprefix('เมือง') == (s['current'] or s['proposed']).removeprefix('เมือง')):
                r['note'] += ' · อาจเป็นอำเภอเดียวกับแถวฝั่งเดียวอีกแถว (ต่างแค่คำว่า "เมือง") กฎ C5 ไม่จับคู่ จึงไม่เสนอแก้'
    cols = ['file', 'name_en', 'field', 'current', 'proposed', 'ocha_pcode', 'kind', 'note']
    with open(a.out, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    st['provinces_system'], st['districts_system'], st['adm1'], st['adm2'] = len(provs), len(dists), len(adm1), len(adm2)
    a.stats.write_text(json.dumps(dict(sorted(st.items())), ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(dict(sorted(st.items())), ensure_ascii=False, indent=1))
    for r in rows:
        if r['kind'] != 'prefix':
            print(r)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
