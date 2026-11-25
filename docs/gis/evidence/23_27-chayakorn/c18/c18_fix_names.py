"""C18 step 3: set name_th of Nakhon Sawan / Takhli and Nakhon Sawan / PhayuhaKhiri in both district files.

Reads each file, checks the round trip json.dumps(ensure_ascii=False, separators=(",", ":")) reproduces the
original bytes exactly (so the rewrite changes nothing else), checks the two current values, changes only those
two values and writes the file back the same way, with no trailing newline.

usage: python -I -B c18_fix_names.py <thailand_districts.json> [<thailand_districts.json> ...]
"""
import hashlib, json, sys

sys.stdout.reconfigure(encoding='utf-8')
FIX = {('Nakhon Sawan', 'Takhli'): ('ท่าตะโก', 'ตาคลี'),
       ('Nakhon Sawan', 'PhayuhaKhiri'): ('ลาดยาว', 'พยุหะคีรี')}


def dump(geo):
    return json.dumps(geo, ensure_ascii=False, separators=(",", ":")).encode('utf-8')


for path in sys.argv[1:]:
    raw = open(path, 'rb').read()
    geo = json.loads(raw.decode('utf-8'))
    if dump(geo) != raw:
        sys.exit(f'ROUND_TRIP_DIFFERS {path}')
    hits = 0
    for f in geo['features']:
        p = f['properties']
        k = (p.get('province'), p.get('name'))
        if k in FIX:
            old, new = FIX[k]
            if p.get('name_th') != old:
                sys.exit(f'UNEXPECTED_VALUE {k} {p.get("name_th")!r} in {path}')
            p['name_th'] = new
            hits += 1
    if hits != 2:
        sys.exit(f'EXPECTED_2_FEATURES got {hits} in {path}')
    out = dump(geo)
    with open(path, 'wb') as f:
        f.write(out)
    print(f'{path}: {len(raw)} -> {len(out)} B · sha256 {hashlib.sha256(raw).hexdigest()[:12]} -> {hashlib.sha256(out).hexdigest()}')
