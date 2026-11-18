"""Read-only map of LDD province / district names to the system boundary files (C5, week 3).

Reads only the .dbf of the province and district layers found in each LDD province ZIP (through zipfile, in memory,
nothing extracted; a ZIP that only wraps another ZIP is opened one level down in memory) and the system files
green-area-backend/data/thailand.json, thailand_districts.json and gis_worker/province_boundaries_ldd.json.
Writes nothing but the outputs named on the command line.

Two rule sets. Default = rules with abbreviations (used for c5-name-map.csv); --strict = the rules of the leader's
document as written.

STRICT RULES (--strict), as given:
  Thai:    drop the prefixes "จังหวัด" "อำเภอ" "เขต" and every space, then compare exactly.
  English: case-insensitive, drop spaces, "-", "." and "'", drop "District" at the end and "Amphoe" / "King Amphoe" /
           "Khet" at the start, then compare exactly.
DEFAULT RULES = STRICT RULES plus, only when at the start of the name:
  Thai:    also drop "จ." and "อ."
  English: also drop "Changwat"
COMMON TO BOTH:
  Thai first; if no match or more than one, try English; if still none or more than one, match_by = none with the
  reason in note (th_not_found, th_ambiguous: <names>, en_not_found, en_ambiguous: <names>).
  Districts are matched only inside a province that is already matched.
  A province that matches neither by Thai nor by English is paired through package_sha256 in
  province_boundaries_ldd.json when the C4 zip_sha256 equals it (note "จังหวัดจับคู่จาก package_sha256");
  otherwise all its districts get match_by = none with note province_unmatched.
  No fuzzy matching. Unmatched rows are labelled, never paired by name similarity (see classify()).

Usage:
  python -I c5_name_map.py [--strict] --code <repo-root> --zips <ldd-zips> --inventory <c4-ldd-inventory.csv>
                           --out <name-map.csv> --provinces <province-map.csv> --stats <stats.json>
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import struct
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

sys.stdout.reconfigure(encoding='utf-8')
OUT_COLUMNS = ['province_th', 'system_province', 'ldd_amphoe_idn', 'ldd_amphoe_t', 'ldd_amphoe_e', 'system_district',
               'match_by', 'note']
TH_PREFIX_STRICT = ('จังหวัด', 'อำเภอ', 'เขต')
TH_PREFIX_ABBR = TH_PREFIX_STRICT + ('จ.', 'อ.')


# ---------------------------------------------------------------- normalisation
def make_norms(strict):
    th_prefixes = TH_PREFIX_STRICT if strict else TH_PREFIX_ABBR

    def norm_th(s):
        s = (s or '').strip()
        for p in th_prefixes:
            if s.startswith(p):
                s = s[len(p):]
                break
        return re.sub(r'\s+', '', s)

    def norm_en(s):
        s = (s or '').strip()
        if not strict:
            s = re.sub(r'^\s*Changwat\s+', '', s, flags=re.I)
        s = re.sub(r'\s*District\s*$', '', s, flags=re.I)
        s = re.sub(r'^\s*(King\s+Amphoe|Amphoe|Khet)\s+', '', s, flags=re.I)
        return re.sub(r"[\s\-\.']", '', s).casefold()
    return norm_th, norm_en


# ---------------------------------------------------------------- zip / dbf reading
def member_name(info):
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode('cp437').decode('cp874')
    except UnicodeError:
        return info.filename


def dbf_fields(raw):
    nrec, hlen, rlen = struct.unpack('<IHH', raw[4:12])
    fields, off = [], 1
    for i in range(32, hlen - 1, 32):
        d = raw[i:i + 32]
        if d[0] == 0x0D:
            break
        fields.append((d[:11].split(b'\x00')[0].decode('ascii', 'replace'), chr(d[11]), d[16], off))
        off += d[16]
    return nrec, hlen, rlen, fields


def dbf_records(raw, codec):
    nrec, hlen, rlen, fields = dbf_fields(raw)
    rows = []
    for r in range(nrec):
        rec = raw[hlen + r * rlen: hlen + (r + 1) * rlen]
        if not rec or rec[:1] == b'*':
            continue
        row, rawlen = {}, {}
        for name, typ, width, off in fields:
            b = rec[off:off + width].rstrip(b' \x00')
            row[name] = b.decode(codec, 'strict').strip()
            rawlen[name] = len(b)
        row['_bytes'] = rawlen
        rows.append(row)
    return {f[0]: f[2] for f in fields}, rows


def layer_kind(fields):
    up = [f.upper() for f in fields]
    if any(f.startswith(('TAMBON_', 'TAM_')) for f in up):
        return 'tam'
    if any(f.startswith('AMPHOE_') for f in up):
        return 'amp'
    if any(f.startswith('PROV_') for f in up):
        return 'pro'
    return None


def codec_for(z, files, shp, policy):
    cpg = next((i for n, i in files if n.casefold() == (shp[:-4] + '.cpg').casefold()), None)
    if cpg is None:
        return None, 'no .cpg'
    text = z.read(cpg).decode('ascii', 'replace').strip()
    codec = policy.cpg_alias(text) or text
    try:
        ''.encode(codec)
        return codec, f'.cpg "{text}" -> {codec}'
    except LookupError:
        return None, f'.cpg "{text}" unknown codec'


def open_package(zips_root, zip_name, policy):
    """The ZIP by name under zips_root; a ZIP with no land-use layer that holds nested ZIPs is opened one level down
    (largest nested ZIP) in memory."""
    hits = [p for p in zips_root.rglob('*.zip') if p.name == zip_name.split(' > ')[0]]
    if len(hits) != 1:
        raise FileNotFoundError(f'{zip_name}: {len(hits)} files found')
    with zipfile.ZipFile(hits[0]) as z:
        names = [member_name(i) for i in z.infolist() if not i.is_dir()]
        nested = [i for i in z.infolist() if member_name(i).lower().endswith('.zip')]
        if policy.select_land_use_layer(names) is None and nested:
            return io.BytesIO(z.read(max(nested, key=lambda i: i.file_size))), 'nested ZIP read in memory'
    return hits[0], ''


def read_layers(source, policy):
    out = {'pro': [], 'amp': []}
    with zipfile.ZipFile(source) as z:
        files = [(member_name(i), i) for i in z.infolist() if not i.is_dir()]
        layer = policy.select_land_use_layer([n for n, _ in files])
        for n, i in files:
            if not n.lower().endswith('.shp') or n == layer:
                continue
            dbf = next((j for m, j in files if m.casefold() == (n[:-4] + '.dbf').casefold()), None)
            if dbf is None:
                continue
            raw = z.read(dbf)
            kind = layer_kind([x[0] for x in dbf_fields(raw)[3]])
            if kind not in out:
                continue
            codec, how = codec_for(z, files, n, policy)
            widths, rows, used = {}, [], f'{how}; could not decode'
            for c in ([codec] if codec else ['utf-8', 'cp874']):
                try:
                    widths, rows = dbf_records(raw, c)
                    used = how if codec else f'no .cpg -> decoded as {c}'
                    break
                except UnicodeDecodeError:
                    continue
            out[kind].append((PurePosixPath(n).name, widths, rows, used))
    return out


def pick(fields, *wanted):
    up = {f.upper(): f for f in fields}
    return next((up[w.upper()] for w in wanted if w.upper() in up), None)


def match(th, en, cands, key_th, key_en, norm_th, norm_en):
    notes = []
    if th:
        hit = [c for c in cands if norm_th(key_th(c)) == norm_th(th)]
        if len(hit) == 1:
            return hit[0], 'th', ''
        notes.append('th_not_found' if not hit else 'th_ambiguous: ' + ', '.join(key_en(c) for c in hit))
    else:
        notes.append('th_missing')
    if en:
        hit = [c for c in cands if norm_en(key_en(c)) == norm_en(en)]
        if len(hit) == 1:
            return hit[0], 'en', '; '.join(notes)
        notes.append('en_not_found' if not hit else 'en_ambiguous: ' + ', '.join(key_en(c) for c in hit))
    else:
        notes.append('en_missing')
    return None, 'none', '; '.join(notes)


# ---------------------------------------------------------------- unmatched-row labels (never a match)
def classify(ldd_un, sys_un, sysdist_prov, norm_th, width):
    """Label the unmatched rows of one province with districts in both files.

    ldd_th_truncated: the LDD Thai value fills its field to within 3 bytes of the width (a Thai character takes 3
      bytes in UTF-8) AND, after normalisation, is the start of exactly one unmatched system name_th.
    system_th_wrong: the system name_th is shared by two districts of the province; the LDD row is labelled with it
      only when it is the one LDD row and that is the one system row left unmatched in the province.
    ldd_only / system_only: everything else.
    """
    labels_l, labels_s = {}, {}
    for i, r in enumerate(ldd_un):
        t = norm_th(r['t'])
        full = r['t_bytes'] >= width - 3
        cand = [j for j, s in enumerate(sys_un) if t and norm_th(s['name_th']).startswith(t) and norm_th(s['name_th']) != t]
        if full and len(cand) == 1:
            j = cand[0]
            labels_l[i] = f'ldd_th_truncated: field {width} bytes, value {r["t_bytes"]} bytes; system has {sys_un[j]["name"]} ({sys_un[j]["name_th"]})'
            labels_s[j] = f'ldd_th_truncated: LDD [{r["idn"]}] {r["t"]} is the cut-off start of this name_th'
    dup = Counter(d['name_th'] for d in sysdist_prov)
    for j, s in enumerate(sys_un):
        if j not in labels_s and dup[s['name_th']] > 1:
            others = [d['name'] for d in sysdist_prov if d['name_th'] == s['name_th'] and d['name'] != s['name']]
            labels_s[j] = f'system_th_wrong: name_th {s["name_th"]} is also the name_th of {", ".join(others)}'
    left_l = [i for i in range(len(ldd_un)) if i not in labels_l]
    left_s = [j for j in range(len(sys_un)) if not labels_s.get(j, '').startswith('ldd_th_truncated')]
    wrong = [j for j in left_s if labels_s.get(j, '').startswith('system_th_wrong')]
    if len(left_l) == 1 and len(left_s) == 1 and wrong:
        s = sys_un[wrong[0]]
        labels_l[left_l[0]] = (f'system_th_wrong: the one LDD row and the one system row left unmatched in the province; '
                               f'system {s["name"]} has a wrong name_th ({s["name_th"]}) - not a match, left for review')
    for i in range(len(ldd_un)):
        labels_l.setdefault(i, 'ldd_only')
    for j in range(len(sys_un)):
        labels_s.setdefault(j, 'system_only')
    return labels_l, labels_s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--strict', action='store_true', help='rules of the leader document as written')
    ap.add_argument('--code', required=True, type=Path)
    ap.add_argument('--zips', required=True, type=Path)
    ap.add_argument('--inventory', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--provinces', required=True, type=Path)
    ap.add_argument('--stats', required=True, type=Path)
    a = ap.parse_args()
    norm_th, norm_en = make_norms(a.strict)
    backend = a.code / 'green-area-backend'
    sys.path.insert(0, str(backend))
    from gis_worker import ldd_policy as policy

    sysprov = [f['properties'] for f in json.load(open(backend / 'data/thailand.json', encoding='utf-8'))['features']]
    sysdist = [f['properties'] for f in json.load(open(backend / 'data/thailand_districts.json', encoding='utf-8'))['features']]
    bounds = [f['properties'] for f in json.load(open(backend / 'gis_worker/province_boundaries_ldd.json', encoding='utf-8'))['features']]
    by_sha = {p['package_sha256']: p['name'] for p in bounds if p.get('package_sha256')}
    inv = list(csv.DictReader(open(a.inventory, encoding='utf-8')))

    prov_rows, out_rows, stats, prefixes = [], [], Counter(), Counter()
    matched_sys = {}
    for r in inv:
        pth, pnote, layers = r['province_th'], [], {'pro': [], 'amp': []}
        if r['zip_name']:
            try:
                src, how_open = open_package(a.zips, r['zip_name'], policy)
                layers = read_layers(src, policy)
                if how_open:
                    pnote.append(how_open)
            except Exception as exc:
                pnote.append(f'read failed: {type(exc).__name__}: {exc}')
        th = en = ''
        if layers['pro']:
            lname, widths, rows, used = layers['pro'][0]
            ft, fe = pick(widths, 'PROV_NAM_T'), pick(widths, 'PROV_NAM_E')
            names = sorted({x.get(ft, '') for x in rows}) if ft else []
            row = rows[0] if len(names) == 1 else None
            if len(rows) > 1 and len(names) == 1:
                pnote.append(f'province layer has {len(rows)} rows, all "{names[0]}" (parts of one province)')
            elif len(names) > 1:
                own = [x for x in rows if norm_th(x.get(ft, '')).endswith(re.sub(r'\s+', '', pth))]
                row = own[0] if own else None
                pnote.append(f'province layer has {len(rows)} rows: {", ".join(names)}; used the row of {pth}'
                             + ('' if own else ' (NOT FOUND)'))
            if row:
                th, en = row.get(ft, ''), row.get(fe, '') if fe else ''
            source = f'province layer {lname}'
            pnote.append(f'{source} {ft}/{fe} ({used})')
        else:
            th, source = pth, ('C4 file name (no province layer)' if r['zip_name'] else 'C4 row (no file)')
        for s in (th,):
            m = re.match(r'^(\S{1,3}\.)', s or '')
            if m:
                prefixes[('th', m.group(1))] += 1
        m = re.match(r'^(Changwat|Amphoe|King Amphoe|Khet)\b', en or '', re.I)
        if m:
            prefixes[('en', m.group(1))] += 1
        chosen, how, why = match(th, en, sysprov, lambda c: c.get('NL_NAME_1', ''), lambda c: c['name'], norm_th, norm_en)
        if chosen is None and r['zip_sha256'] in by_sha:
            chosen = next((c for c in sysprov if c['name'] == by_sha[r['zip_sha256']]), None)
            if chosen:
                how, why = 'package_sha256', (why + '; ' if why else '') + 'จังหวัดจับคู่จาก package_sha256'
        if why:
            pnote.append(why)
        sysname = chosen['name'] if chosen else ''
        stats[f'province_{how}'] += 1
        if chosen:
            if sysname in matched_sys:
                pnote.append(f'system province already matched to {matched_sys[sysname]}')
            matched_sys[sysname] = pth
        prov_rows.append({'region': r['region'], 'province_th': pth, 'ldd_name_source': source, 'ldd_prov_nam_t': th,
                          'ldd_prov_nam_e': en, 'system_province': sysname,
                          'system_nl_name_1': chosen.get('NL_NAME_1', '') if chosen else '', 'match_by': how,
                          'has_amp_layer': 'yes' if layers['amp'] else 'no', 'note': ' | '.join(pnote)})
        if not layers['amp']:
            continue
        lname, widths, rows, used = layers['amp'][0]
        fi, ft, fe = pick(widths, 'AMPHOE_IDN'), pick(widths, 'AMPHOE_T'), pick(widths, 'AMPHOE_E')
        # one output row per LDD district = rows with the same AMPHOE_IDN and AMPHOE_T (parts of one district);
        # differing English spellings inside a group are recorded in note
        groups, en_variants = {}, {}
        for x in rows:
            k2 = (x.get(fi, '') if fi else '', x.get(ft, '') if ft else '')
            groups.setdefault(k2, []).append(x)
            en_variants.setdefault(k2, []).append(x.get(fe, '') if fe else '')
        groups = {(k[0], k[1], en_variants[k][0]): v for k, v in groups.items()}
        stats['ldd_amphoe_layer_rows'] += len(rows)
        stats['ldd_amphoe_districts'] += len(groups)
        cands = [d for d in sysdist if d['province'] == sysname] if chosen else []
        used_sys, prov_out, ldd_un = Counter(), [], []
        for (idn, t, e), parts in groups.items():
            for s in (t,):
                mm = re.match(r'^(\S{1,3}\.)', s or '')
                if mm:
                    prefixes[('th', mm.group(1))] += 1
            mm = re.match(r'^(Changwat|Amphoe|King Amphoe|Khet)\b', e or '', re.I)
            if mm:
                prefixes[('en', mm.group(1) if mm.group(1)[0].isupper() else mm.group(1) + ' (lower case)')] += 1
            elif e and re.match(r'^Amph\w*\s', e):
                prefixes[('en-other', e.split()[0])] += 1
            if chosen:
                d, dhow, dwhy = match(t, e, cands, lambda c: c['name_th'], lambda c: c['name'], norm_th, norm_en)
            else:
                d, dhow, dwhy = None, 'none', 'province_unmatched'
            note = [n for n in (dwhy,) if n]
            if len(parts) > 1:
                note.append(f'{len(parts)} rows in the LDD layer (parts of one district)')
            variants = sorted(set(en_variants[(idn, t)]))
            if len(variants) > 1:
                note.append('AMPHOE_E differs between its rows: ' + ' / '.join(variants))
            row = {'province_th': pth, 'system_province': sysname, 'ldd_amphoe_idn': idn, 'ldd_amphoe_t': t,
                   'ldd_amphoe_e': e, 'system_district': f"{d['name']} ({d['name_th']})" if d else '',
                   'match_by': dhow, 'note': ' | '.join(note)}
            prov_out.append(row)
            stats[f'district_{dhow}'] += 1
            if d:
                used_sys[d['name']] += 1
            elif chosen:
                ldd_un.append({'row': row, 't': t, 'idn': idn, 't_bytes': parts[0]['_bytes'].get(ft, 0) if ft else 0})
        for name, n in used_sys.items():
            if n > 1:
                for o in prov_out:
                    if o['system_district'].startswith(name + ' ('):
                        o['note'] = (o['note'] + ' | ' if o['note'] else '') + f'system district matched by {n} LDD rows'
        sys_un = [d for d in cands if d['name'] not in used_sys]
        sys_rows = [{'province_th': pth, 'system_province': sysname, 'ldd_amphoe_idn': '', 'ldd_amphoe_t': '',
                     'ldd_amphoe_e': '', 'system_district': f"{d['name']} ({d['name_th']})", 'match_by': 'none',
                     'note': ''} for d in sys_un]
        ll, ls = classify(ldd_un, sys_un, cands, norm_th, widths.get(ft, 0) if ft else 0)
        for i, u in enumerate(ldd_un):
            u['row']['note'] = ll[i] + (' | ' + u['row']['note'] if u['row']['note'] else '')
            stats['diff_' + ll[i].split(':')[0]] += 1
        for j, srow in enumerate(sys_rows):
            srow['note'] = ls[j]
            stats['diff_sys_' + ls[j].split(':')[0]] += 1
        out_rows += prov_out + sys_rows
    # system districts outside the provinces that have an LDD district layer
    amp_provs = {p['system_province'] for p in prov_rows if p['has_amp_layer'] == 'yes' and p['system_province']}
    for d in sysdist:
        if d['province'] in amp_provs:
            continue
        owner = next((p for p in prov_rows if p['system_province'] == d['province']), None)
        if owner:
            note = 'ldd_no_amphoe_layer' + ('; no LDD file' if owner['ldd_name_source'].startswith('C4 row') else '')
            stats['system_ldd_no_amphoe_layer'] += 1
        else:
            note = 'system_province_unmatched: the system province is not matched to any LDD province'
            stats['system_province_unmatched'] += 1
        out_rows.append({'province_th': owner['province_th'] if owner else '', 'system_province': d['province'],
                         'ldd_amphoe_idn': '', 'ldd_amphoe_t': '', 'ldd_amphoe_e': '',
                         'system_district': f"{d['name']} ({d['name_th']})", 'match_by': 'none', 'note': note})
    unmatched_sys = [c['name'] for c in sysprov if c['name'] not in matched_sys]
    checks = []
    nl = Counter(c.get('NL_NAME_1') for c in sysprov)
    for c in sysprov:
        v = c.get('NL_NAME_1', '')
        if nl[v] > 1 or not v.startswith('จังหวัด'):
            checks.append(f"thailand.json {c['name']}: NL_NAME_1 = {v}" + (' (duplicate)' if nl[v] > 1 else ''))
    per = defaultdict(Counter)
    for d in sysdist:
        per[d['province']][d['name_th']] += 1
    for prov, cnt in per.items():
        for t, n in cnt.items():
            if n > 1:
                checks.append(f'thailand_districts.json {prov}: name_th {t} on {n} districts: '
                              + ', '.join(d['name'] for d in sysdist if d['province'] == prov and d['name_th'] == t))
    matched_d = {(o['system_province'], o['system_district']) for o in out_rows if o['match_by'] in ('th', 'en')}
    stats_out = dict(stats)
    stats_out.update(rules='strict' if a.strict else 'with abbreviations', system_provinces=len(sysprov),
                     system_districts=len(sysdist), system_districts_matched=len(matched_d),
                     system_districts_matched_th=len({k for k in matched_d if any(o['match_by'] == 'th' and (o['system_province'], o['system_district']) == k for o in out_rows)}),
                     unmatched_system_provinces=unmatched_sys, system_file_checks=checks,
                     name_prefixes_seen={f'{k[0]}:{k[1]}': v for k, v in sorted(prefixes.items())})
    stats_out['system_districts_matched_en'] = stats_out['system_districts_matched'] - stats_out['system_districts_matched_th']
    with open(a.out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)
    with open(a.provinces, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(prov_rows[0]))
        w.writeheader()
        w.writerows(prov_rows)
    with open(a.stats, 'w', encoding='utf-8') as f:
        json.dump(stats_out, f, ensure_ascii=False, indent=1)
    print(json.dumps(stats_out, ensure_ascii=False, indent=1))
    print('name-map rows:', len(out_rows))


if __name__ == '__main__':
    main()
