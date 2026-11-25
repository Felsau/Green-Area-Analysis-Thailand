"""C18 step 2: rebuild the add_district_th_names.py lookup from the current kongvut data, without running the script.

Only strict(), loose(), MANUAL_OVERRIDES and PROVINCE_EN_OVERRIDES are imported from the script (its main() is
never called and nothing is fetched or written by it). The lookup follows the script's order exactly:
  * pid_to_en: kongvut province name.en, then PROVINCE_EN_OVERRIDES
  * strict_lookup / loose_lookup: one pass over district.json in file order, later rows overwrite earlier ones
  * per feature: MANUAL_OVERRIDES[strict] -> strict_lookup[strict] -> loose_lookup[loose] -> global unique loose
The kongvut files changed format (name.th / name.en instead of name_th / name_en), so this reads the new keys.
`--extra-manual` adds the two C18 overrides to test the fixed lookup.

usage: python -I -B c18_kongvut_check.py --script <add_district_th_names.py> --kongvut <dir> --districts <json> --out <json>
"""
import argparse, importlib.util, json, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
C18 = {('Nakhon Sawan', 'takhli'): 'ตาคลี', ('Nakhon Sawan', 'phayuhakhiri'): 'พยุหะคีรี'}


def load_names(script):
    spec = importlib.util.spec_from_file_location('add_district_th_names', script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # top level only defines constants and functions; main() is guarded
    return mod.strict, mod.loose, dict(mod.MANUAL_OVERRIDES), dict(mod.PROVINCE_EN_OVERRIDES)


def build(provinces, districts, strict, loose, PROV):
    pid_to_en = {}
    for p in provinces:
        en = p['name']['en'].strip()
        pid_to_en[p['id']] = PROV.get(en, en)
    strict_lookup, loose_lookup, s_src, l_src = {}, {}, {}, {}
    s_over, l_over = [], []
    for d in districts:
        prov_en = pid_to_en.get(d['province_id'])
        if not prov_en:
            continue
        ks, kl = (prov_en, strict(d['name']['en'])), (prov_en, loose(d['name']['en']))
        row = {'id': d['id'], 'en': d['name']['en'], 'th': d['name']['th'], 'deleted_at': d.get('deleted_at')}
        if ks in strict_lookup and strict_lookup[ks] != d['name']['th']:
            s_over.append({'key': list(ks), 'earlier': s_src[ks], 'later_wins': row})
        if kl in loose_lookup and loose_lookup[kl] != d['name']['th']:
            l_over.append({'key': list(kl), 'earlier': l_src[kl], 'later_wins': row})
        strict_lookup[ks], s_src[ks] = d['name']['th'], row
        loose_lookup[kl], l_src[kl] = d['name']['th'], row
    return pid_to_en, strict_lookup, loose_lookup, s_src, l_src, s_over, l_over


def resolve(feat_props, strict, loose, MAN, sl, ll, s_src, l_src):
    prov_en, dist_en = feat_props.get('province', ''), feat_props.get('name', '')
    ks, kl = (prov_en, strict(dist_en)), (prov_en, loose(dist_en))
    if MAN.get(ks):
        return MAN[ks], 'manual', {'key': list(ks)}
    if sl.get(ks):
        return sl[ks], 'strict', {'key': list(ks), 'kongvut_row': s_src[ks]}
    if ll.get(kl):
        return ll[kl], 'loose', {'key': list(kl), 'kongvut_row': l_src[kl]}
    cands = {v for (p, n), v in ll.items() if n == kl[1]}
    if len(cands) == 1:
        return next(iter(cands)), 'global', {'key': kl[1]}
    return dist_en, 'unmatched', {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--script', type=Path, required=True)
    ap.add_argument('--kongvut', type=Path, required=True)
    ap.add_argument('--districts', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--extra-manual', action='store_true')
    a = ap.parse_args()
    strict, loose, MAN, PROV = load_names(a.script)
    if a.extra_manual:
        MAN.update(C18)
    provinces = json.load(open(a.kongvut / 'province.json', encoding='utf-8'))
    districts = json.load(open(a.kongvut / 'district.json', encoding='utf-8'))
    pid_to_en, sl, ll, s_src, l_src, s_over, l_over = build(provinces, districts, strict, loose, PROV)
    feats = json.load(open(a.districts, encoding='utf-8'))['features']

    layers, diffs, khet_only, per = Counter(), [], [], {}
    for f in feats:
        p = f['properties']
        th, layer, how = resolve(p, strict, loose, MAN, sl, ll, s_src, l_src)
        layers[layer] += 1
        cur = p.get('name_th')
        if th != cur:
            item = {'province': p['province'], 'name': p['name'], 'file_name_th': cur, 'rebuilt_name_th': th, 'layer': layer}
            if p['province'] == 'Bangkok Metropolis' and (cur == 'เขต' + th or th == 'เขต' + cur):
                khet_only.append(item)
            else:
                diffs.append(item)
        if p['province'] == 'Nakhon Sawan' or (p['province'], p['name']) == ('Phra Nakhon Si Ayutthaya', 'BangSai'):
            per[f"{p['province']} / {p['name']}"] = {'file_name_th': cur, 'rebuilt_name_th': th, 'layer': layer, **how}

    # same English name inside one kongvut province (raw, strict() and loose() keys)
    raw, sk, lk = defaultdict(list), defaultdict(list), defaultdict(list)
    for d in districts:
        pe = pid_to_en.get(d['province_id'])
        r = {'id': d['id'], 'en': d['name']['en'], 'th': d['name']['th'], 'deleted_at': d.get('deleted_at')}
        raw[(pe, d['name']['en'].strip().lower())].append(r)
        sk[(pe, strict(d['name']['en']))].append(r)
        lk[(pe, loose(d['name']['en']))].append(r)
    dup = lambda m: [{'key': list(k), 'rows': v} for k, v in m.items() if len(v) > 1]
    th_dup = Counter((f['properties']['province'], f['properties']['name_th']) for f in feats)
    res = {
        'kongvut': {'provinces': len(provinces), 'districts': len(districts),
                    'district_rows_with_deleted_at': sum(1 for d in districts if d.get('deleted_at')),
                    'keys_old_script_reads_present': {'province name_en': 'name_en' in provinces[0], 'district name_en': 'name_en' in districts[0],
                                                       'district name_th': 'name_th' in districts[0]},
                    'keys_now': {'province': sorted(provinces[0]), 'district': sorted(districts[0])}},
        'extra_manual_c18': a.extra_manual,
        'features': len(feats), 'layers': dict(layers),
        'strict_lookup_entries': len(sl), 'loose_lookup_entries': len(ll),
        'diff_count': len(diffs), 'diffs': diffs, 'bangkok_khet_only_count': len(khet_only), 'bangkok_khet_only': khet_only,
        'kongvut_same_english_name_in_province': dup(raw),
        'kongvut_same_strict_key_in_province': dup(sk),
        'kongvut_same_loose_key_in_province': dup(lk),
        'strict_overwrites_with_different_th': s_over, 'loose_overwrites_with_different_th': l_over,
        'file_duplicate_name_th_in_province': [list(k) + [n] for k, n in th_dup.items() if n > 1],
        'nakhon_sawan_and_bangsai': per,
    }
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: res[k] for k in ('kongvut', 'extra_manual_c18', 'features', 'layers', 'strict_lookup_entries',
                                           'loose_lookup_entries', 'diff_count', 'bangkok_khet_only_count')}, ensure_ascii=False))
    for d in diffs:
        print('DIFF', d)
    for k in ('kongvut_same_english_name_in_province', 'kongvut_same_strict_key_in_province', 'kongvut_same_loose_key_in_province',
              'strict_overwrites_with_different_th', 'loose_overwrites_with_different_th'):
        print(k, len(res[k]))
        for x in res[k]:
            print('   ', json.dumps(x, ensure_ascii=False))
    print('file_duplicate_name_th_in_province', res['file_duplicate_name_th_in_province'])
    for k, v in per.items():
        print(k, json.dumps(v, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
