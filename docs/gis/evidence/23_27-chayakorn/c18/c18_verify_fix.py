"""C18 step 4: check the fixed district files against the committed base.

* the two copies are byte-identical
* against `git show <base>:<path>`, the only differences are name_th of the two districts (parsed compare of every
  feature, plus a byte-level diff of the changed spans)
* 928 features and no duplicate name_th inside one province

usage: python -I -B c18_verify_fix.py --repo <worktree> --base <commit>
"""
import argparse, difflib, hashlib, json, subprocess, sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')
PATHS = ('green-area-backend/data/thailand_districts.json', 'green-area-frontend/public/thailand_districts.json')
ap = argparse.ArgumentParser()
ap.add_argument('--repo', required=True)
ap.add_argument('--base', required=True)
a = ap.parse_args()
ok = True
now = [open(f'{a.repo}/{p}', 'rb').read() for p in PATHS]
print('copies byte-identical:', now[0] == now[1], '· sha256', hashlib.sha256(now[0]).hexdigest(), '·', len(now[0]), 'B')
ok &= now[0] == now[1]
for p, cur in zip(PATHS, now):
    base = subprocess.run(['git', '-C', a.repo, 'show', f'{a.base}:{p}'], capture_output=True, check=True).stdout
    B, C = json.loads(base), json.loads(cur)
    changed = []
    assert len(B['features']) == len(C['features'])
    assert {k: v for k, v in B.items() if k != 'features'} == {k: v for k, v in C.items() if k != 'features'}
    for fb, fc in zip(B['features'], C['features']):
        if fb == fc:
            continue
        pb, pc = fb['properties'], fc['properties']
        rest_b = {**fb, 'properties': {k: v for k, v in pb.items() if k != 'name_th'}}
        rest_c = {**fc, 'properties': {k: v for k, v in pc.items() if k != 'name_th'}}
        if rest_b != rest_c:
            changed.append(('OTHER_CHANGE', pb.get('province'), pb.get('name')))
        else:
            changed.append((pb['province'], pb['name'], pb['name_th'], pc['name_th']))
    # text-level: split the raw text at each feature, then trim the common prefix/suffix of each changed piece
    # (shown with 12 characters of context before and 3 after)
    sb, sc = base.decode('utf-8').split('{"type":"Feature"'), cur.decode('utf-8').split('{"type":"Feature"')
    ops = []
    for t, i1, i2, j1, j2 in difflib.SequenceMatcher(None, sb, sc, autojunk=False).get_opcodes():
        if t == 'equal':
            continue
        x, y = ''.join(sb[i1:i2]), ''.join(sc[j1:j2])
        k = 0
        while k < min(len(x), len(y)) and x[k] == y[k]:
            k += 1
        m = 0
        while m < min(len(x), len(y)) - k and x[-1 - m] == y[-1 - m]:
            m += 1
        ops.append((t, x[max(0, k - 12):len(x) - m + 3], y[max(0, k - 12):len(y) - m + 3]))
    feats = C['features']
    nl, cr = cur.endswith(bytes([10])), bytes([13]) in cur
    dup = [k for k, n in Counter((f['properties']['province'], f['properties']['name_th']) for f in feats).items() if n > 1]
    print(f'{p}: base {len(base)} B sha {hashlib.sha256(base).hexdigest()[:12]} · features {len(feats)} · '
          f'changed features {changed} · byte-level edits {ops} · duplicate name_th in a province: {dup or "none"} · '
          f'ends with newline: {nl} · has CR: {cr}')
    ok &= len(feats) == 928 and not dup and len(changed) == 2 and all(c[0] != 'OTHER_CHANGE' for c in changed)
print('ALL_OK' if ok else 'CHECK_FAILED')
sys.exit(0 if ok else 1)
