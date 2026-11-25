"""C18 step 6: draw the 15 Nakhon Sawan districts with their name_th labels, before and after the fix.

before = `git show <base>:green-area-frontend/public/thailand_districts.json`, after = the worktree file.
Uses a Thai-capable Windows font (Leelawadee UI, else Tahoma). Takhli and PhayuhaKhiri are filled orange.

usage: python -I -B c18_draw.py --repo <worktree> --base <commit> --out <dir>
"""
import argparse, json, subprocess, sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from shapely.geometry import shape

sys.stdout.reconfigure(encoding='utf-8')
P = 'green-area-frontend/public/thailand_districts.json'
FIXED = {'Takhli', 'PhayuhaKhiri'}


def pick_font():
    names = {f.name: f.fname for f in font_manager.fontManager.ttflist}
    for n in ('Leelawadee UI', 'Tahoma'):
        if n in names:
            return n, names[n]
    sys.exit('NO_THAI_FONT')


def draw(feats, title, path, font):
    fig, ax = plt.subplots(figsize=(11, 12), dpi=130)
    for f in feats:
        g = shape(f['geometry'])
        polys = getattr(g, 'geoms', [g])
        hit = f['properties']['name'] in FIXED
        for p in polys:
            x, y = p.exterior.xy
            ax.fill(x, y, facecolor='#f6b26b' if hit else '#d9ead3', edgecolor='#38761d', linewidth=0.8)
        pt = g.representative_point()
        ax.annotate(f"{f['properties']['name_th']}\n({f['properties']['name']})", (pt.x, pt.y), ha='center', va='center',
                    fontsize=11, fontname=font, bbox=dict(boxstyle='round,pad=0.25', fc='white', ec='#999999', alpha=0.85))
    ax.set_aspect(1 / 0.958)   # cos(15.7 deg): lon/lat aspect at Nakhon Sawan
    ax.set_title(title, fontsize=15, fontname=font)
    ax.set_xlabel('ลองจิจูด', fontname=font)
    ax.set_ylabel('ละติจูด', fontname=font)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True)
    ap.add_argument('--base', required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    font, fpath = pick_font()
    before = json.loads(subprocess.run(['git', '-C', a.repo, 'show', f'{a.base}:{P}'], capture_output=True, check=True).stdout)
    after = json.load(open(f'{a.repo}/{P}', encoding='utf-8'))
    for tag, geo, title in (('before', before, f'นครสวรรค์ 15 อำเภอ · ก่อนแก้ ({a.base[:7]}) · ป้าย = name_th'),
                            ('after', after, 'นครสวรรค์ 15 อำเภอ · หลังแก้ (C18) · ป้าย = name_th')):
        feats = [f for f in geo['features'] if f['properties']['province'] == 'Nakhon Sawan']
        assert len(feats) == 15, len(feats)
        out = a.out / f'c18-nakhon-sawan-{tag}.png'
        draw(feats, title + ' · สีส้ม = ตาคลี/พยุหะคีรี (Takhli/PhayuhaKhiri)', out, font)
        print(tag, out.name, out.stat().st_size, 'B · font', font, Path(fpath).name,
              sorted((f['properties']['name'], f['properties']['name_th']) for f in feats if f['properties']['name'] in FIXED))


if __name__ == '__main__':
    main()
