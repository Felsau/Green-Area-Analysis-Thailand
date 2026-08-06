import { useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE, CURRENT_YEAR, PROVINCE_TH, TOTAL_DISTRICTS, DATA_YEAR_SPAN } from '../constants';
import { WHO_REFERENCE_M2 } from '../utils/greenMetric';

// Public-facing intro page shown before the dashboard ("Atlas Index" direction):
// an editorial, magazine-grade cover for the dataset. Pure presentation plus a
// live read of the national green-per-capita ranking — the enter/skip logic
// (sessionStorage + deep-link bypass) lives in App.js.

const FEATURES = [
  ['สถิติเชิงพื้นที่', 'Spatial statistics',
   'NDVI · LST · พื้นที่สีเขียวต่อหัวเทียบเกณฑ์ WHO ระดับจังหวัดถึงอำเภอ'],
  ['แนวโน้ม + พยากรณ์', 'Trends & forecast',
   'ย้อนหลังหลายปี พร้อมพยากรณ์ 3 ปีด้วย OLS regression และช่วงเชื่อมั่น 95%'],
  ['เทียบภาพดาวเทียม', 'Satellite compare',
   'เลื่อนเทียบสองปีแบบ swipe หรือดูแผนที่ผลต่าง (Δ)'],
  ['ผลความเย็น', 'Cooling effect',
   'Regression ของ LST ต่อ NDVI ระดับอำเภอ — ยิ่งเขียวยิ่งเย็น'],
  ['AI แนะนำจุดปลูก', 'AI recommendation',
   'Heatmap จัดลำดับพื้นที่ที่ควรปลูก พร้อมพันธุ์ไม้แนะนำรายภาค'],
  ['รายงาน + แชร์', 'Reports & sharing',
   'ส่งออก PDF/CSV พร้อมพิกัด และลิงก์แชร์ระดับอำเภอ'],
];

const SOURCES = [
  ['ภาพถ่ายดาวเทียม', [
    ['Sentinel-2 (ESA)', 'NDVI ความละเอียด 10 ม. อัปเดตรายปี'],
    ['Landsat 8/9 (USGS)', 'LST ความละเอียด 30 ม. ย้อนหลังหลายปี'],
    ['ESA WorldCover', 'การจำแนกประเภทการใช้ที่ดิน 10 ม.'],
  ]],
  ['ข้อมูลสนับสนุน', [
    ['GADM 4.1', 'ขอบเขตการปกครอง จังหวัด/อำเภอ/ตำบล'],
    ['WorldPop', 'ประชากรรายตาราง สำหรับคำนวณ m²/คน'],
    ['OpenStreetMap · CARTO', 'เลเยอร์แผนที่พื้น'],
  ]],
];

const NDVI_STOPS = ['#bbf7d0', '#86efac', '#4ade80', '#22c55e', '#1f6f43'];
function ndviRamp(t) {
  const i = Math.max(0, Math.min(NDVI_STOPS.length - 1, Math.floor(t * NDVI_STOPS.length)));
  return NDVI_STOPS[i];
}

// Decorative 12-bar NDVI sparkline, seeded by the province's mean NDVI so greener
// provinces read taller. Deterministic — no per-province monthly fetch needed.
function spark(baseLevel, index) {
  const bars = [];
  for (let m = 0; m < 12; m++) {
    let v = baseLevel + Math.sin(m * 0.7 + index) * 0.1 + (m / 11) * 0.06;
    v = Math.max(0.1, Math.min(0.95, v));
    bars.push({ h: Math.round(v * 100), c: ndviRamp(v) });
  }
  return bars;
}

const fmt = (n) => Number(n).toLocaleString('en-US', { maximumFractionDigits: 1 });

function IndexRow({ r, i, onEnter }) {
  return (
    <a
      className="c__row"
      href="#dashboard"
      role="row"
      onClick={(e) => { e.preventDefault(); onEnter(); }}
      aria-label={`${r.th} — ${r.val} ตารางเมตรต่อคน${r.warn ? ' (ต่ำกว่าเกณฑ์ WHO)' : ''}`}
    >
      <span className="c__row-rank" role="cell">{String(r.rank).padStart(2, '0')}</span>
      <span className="c__row-name" role="cell">
        <span className="c__row-th">{r.th}</span>
        <span className="c__row-en">{r.en}</span>
      </span>
      <span className="c__row-en c__row-en--col" role="cell">{r.en}</span>
      <span className="c__spark" role="cell" aria-hidden="true">
        {spark(r.base, i).map((b, k) => (
          <i key={k} style={{ height: `${b.h}%`, '--g': b.c }} />
        ))}
      </span>
      <span className={`c__row-val${r.warn ? ' warn' : ''}`} role="cell">
        {r.val}<em>m²/คน</em>
      </span>
    </a>
  );
}

export default function Landing({ onEnter, theme, onToggleTheme, onCookieSettings, onOpenPolicy }) {
  const isDark = theme === 'dark';
  const rootRef = useRef(null);
  const [scrolled, setScrolled] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [ranking, setRanking] = useState(null);   // raw /analysis/ranking payload, or null

  // Live national ranking (green m²/person). Best-effort: the cover still works
  // without it, so a failed/empty fetch simply hides the province index.
  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/analysis/ranking?year=${CURRENT_YEAR}`, { signal: ctrl.signal });
        if (!res.ok) return;
        const json = await res.json();
        if (Array.isArray(json.data) && json.data.length) setRanking(json);
      } catch (err) {
        if (err?.name !== 'AbortError') console.error('โหลดอันดับจังหวัดไม่สำเร็จ:', err);
      }
    })();
    return () => ctrl.abort();
  }, []);

  // backend ranks ascending (rank 1 = lowest m²/person). Build a "greenest few"
  // head and a "lowest few" tail for the editorial index, with real WHO flags.
  const { topRows, lowRows, total, whoFail } = useMemo(() => {
    const data = ranking?.data ?? [];
    if (!data.length) return { topRows: [], lowRows: [], total: 0, whoFail: 0 };
    const toRow = (d, rank) => ({
      rank,
      th: PROVINCE_TH[d.province] || d.province,
      en: d.province,
      val: fmt(d.green_area_m2_per_person),
      // คิดจากตัวเลขตรง ๆ — เดิม match ข้อความใน who_status ซึ่งพังเงียบทันทีที่แก้ถ้อยคำ
      // (main.py:324 เตือนเรื่องนี้ไว้เองอยู่แล้ว) · who_status กำลังเลิกใช้
      warn: d.green_area_m2_per_person != null
        && d.green_area_m2_per_person < WHO_REFERENCE_M2,
      base: Math.max(0.18, Math.min(0.8, d.ndvi_mean ?? 0.4)),
    });
    const n = data.length;
    const top = data.slice(-4).reverse().map((d, i) => toRow(d, i + 1));
    const low = data.slice(0, 4).map((d, i) => toRow(d, n - 3 + i));
    return {
      topRows: top,
      lowRows: low,
      total: n,
      whoFail: ranking?.who_fail_count ?? 0,
    };
  }, [ranking]);

  // Sticky-nav shadow on scroll.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;
    const onScroll = () => setScrolled(root.scrollTop > 40);
    root.addEventListener('scroll', onScroll, { passive: true });
    return () => root.removeEventListener('scroll', onScroll);
  }, []);

  // Scroll-reveal: fade sections in as they enter view. Falls back to always-on
  // when IntersectionObserver is missing (jsdom) or reduced motion is preferred.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;
    const targets = root.querySelectorAll('.c-reveal');
    if (typeof IntersectionObserver === 'undefined'
        || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      targets.forEach(el => el.classList.add('is-visible'));
      return undefined;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        io.unobserve(entry.target);
      });
    }, { threshold: 0.12 });
    targets.forEach(el => io.observe(el));
    return () => io.disconnect();
  }, [topRows.length]);

  // `total` = จำนวนจังหวัดใน ranking — เคยถูกนำมาแสดงเป็นจำนวน "อำเภอที่มีข้อมูล"
  // ทำให้หน้าแรกขึ้น "77 อำเภอ · เขต (มีข้อมูล)" ทั้งที่ทั้งประเทศมี 928 อำเภอ และ
  // อำเภอที่มีข้อมูลจริงใน cache มีหลักสิบ · ranking เป็น endpoint ระดับจังหวัด
  // ไม่มีตัวเลขอำเภอให้เลย จึงแสดงจำนวนอำเภอทั้งประเทศตรง ๆ ไม่อ้างว่ามีข้อมูลครบ
  const stats = [
    ['77', 'จังหวัด', 'Provinces'],
    [String(TOTAL_DISTRICTS), 'อำเภอ · เขต', 'Districts'],
    ['10', 'ความละเอียด NDVI', 'Resolution', 'ม.'],
    [String(DATA_YEAR_SPAN), 'ชุดข้อมูลรายปี', 'Annual series', 'ปี'],
  ];

  return (
    <div className="landing" ref={rootRef}>
      <div className="c" id="top">
        {/* Navigation */}
        <div className={`c__nav-wrap${scrolled ? ' is-scrolled' : ''}`}>
          <nav className="c__nav" aria-label="เมนูหลัก">
            <a className="c__brand" href="#top" aria-label="GreenLens — กลับด้านบน">
              <span className="c__brand-mark" aria-hidden="true" />
              <b>GreenLens</b>
            </a>
            <div className={`c__nav-links${navOpen ? ' is-open' : ''}`} role="list">
              <a href="#index" role="listitem" onClick={() => setNavOpen(false)}>ดัชนีจังหวัด</a>
              <a href="#feat" role="listitem" onClick={() => setNavOpen(false)}>ความสามารถ</a>
              <a href="#method" role="listitem" onClick={() => setNavOpen(false)}>วิธีการ</a>
              <button
                className="c__nav-theme"
                onClick={onToggleTheme}
                aria-label={isDark ? 'สลับเป็นธีมสว่าง' : 'สลับเป็นธีมมืด'}
                title={isDark ? 'ธีมสว่าง' : 'ธีมมืด'}
              >
                {isDark ? '☀' : '☾'}
              </button>
              <button className="c__nav-cta" onClick={onEnter}>เปิดแดชบอร์ด →</button>
            </div>
            <button
              className="c__nav-mobile-btn"
              aria-label="เปิดเมนู"
              aria-expanded={navOpen}
              onClick={() => setNavOpen(o => !o)}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <rect y="2" width="16" height="1.5" rx="0.75" fill="currentColor" />
                <rect y="7.25" width="16" height="1.5" rx="0.75" fill="currentColor" />
                <rect y="12.5" width="16" height="1.5" rx="0.75" fill="currentColor" />
              </svg>
            </button>
          </nav>
        </div>

        <main>
          {/* Hero */}
          <section className="c__hero" aria-labelledby="heroHeading">
            <div className="c-wrap">
              <div className="c__hero-grid">
                <div className="c__hero-text">
                  <div className="c__eyebrow" aria-hidden="true">สมุดดัชนีพื้นที่สีเขียวแห่งชาติ</div>
                  <h1 className="c__h1" id="heroHeading">แผนที่ความเขียว<br />ของประเทศไทย</h1>
                  <div className="c__h1-en">A living atlas of the nation&rsquo;s green space.</div>
                  <p className="c__lede">
                    ดัชนีพืชพรรณ อุณหภูมิพื้นผิว และพื้นที่สีเขียวต่อประชากร
                    จากภาพถ่ายดาวเทียม เรียบเรียงเป็นสมุดข้อมูลที่ค้นได้ทุกจังหวัด
                    ทุกอำเภอ — เพื่อการตัดสินใจเชิงผังเมืองบนหลักฐานที่มองเห็นได้
                  </p>
                  <div className="c__hero-actions">
                    <button className="c__btn c__btn--primary" onClick={onEnter}>
                      เปิดแดชบอร์ด <span aria-hidden="true">→</span>
                    </button>
                    <a className="c__link" href="#index">เลื่อนดูดัชนีจังหวัด</a>
                  </div>
                </div>

                <div className="c__plate c__hero-plate">
                  <div className="c__plate-badge" aria-label="ค่า NDVI เฉลี่ยทั่วประเทศ">
                    <b>{ranking?.data?.length
                      ? (ranking.data.reduce((s, d) => s + (d.ndvi_mean ?? 0), 0) / ranking.data.length).toFixed(2)
                      : '0.41'}</b>
                    <span>μ NDVI</span>
                  </div>
                  <div className="c__plate-frame">
                    <img
                      className="c__plate-img"
                      src="/landing/stats.jpg"
                      alt="แผนที่และสถิติพื้นที่สีเขียวรายจังหวัด จากระบบ GreenLens"
                      loading="eager"
                    />
                    <div className="c__plate-tag">
                      <b>{lowRows[3]?.th ?? 'กรุงเทพมหานคร'}</b>
                      <span>{lowRows[3] ? `${lowRows[3].val} m²/คน · ต่ำสุดของประเทศ` : 'NDVI 0.27 · 4.1 m²/คน'}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* Stat band */}
          <section className="c__statband" aria-label="สถิติภาพรวม">
            <div className="c-wrap c__statband-inner">
              {stats.map(([num, cap, en, unit], i) => (
                <div className={`c__sb c-reveal c-reveal--delay-${i}`} key={en}>
                  <div className="c__sb-num">{num}{unit && <small>{unit}</small>}</div>
                  <div className="c__sb-cap">{cap}<em>{en}</em></div>
                </div>
              ))}
            </div>
          </section>

          {/* Province index */}
          {topRows.length > 0 && (
            <section className="c__section" id="index" aria-labelledby="indexHeading">
              <div className="c-wrap">
                <div className="c__sec-head c-reveal">
                  <div>
                    <div className="c__kicker">ดัชนีจังหวัด · Provincial index</div>
                    <h2 className="c__h2" id="indexHeading">เปิดดูได้ทุกจังหวัด <em>— green per capita</em></h2>
                  </div>
                  <p className="c__sec-note">เรียงตามพื้นที่สีเขียวต่อประชากร · แท่งคือ NDVI โดยประมาณ</p>
                </div>

                <div className="c__index" role="table" aria-label="ดัชนีพื้นที่สีเขียวรายจังหวัด">
                  <div className="c__index-head" role="row" aria-hidden="true">
                    <span>#</span><span>จังหวัด</span><span /><span>NDVI</span><span>m²/คน</span>
                  </div>
                  <div role="rowgroup">
                    {topRows.map((r, i) => <IndexRow key={r.en} r={r} i={i} onEnter={onEnter} />)}
                    <div className="c__index-sep" aria-hidden="true">
                      <span>{`··· จังหวัดอันดับ 5–${Math.max(5, total - 4)} ···`}</span>
                    </div>
                    {lowRows.map((r, i) => <IndexRow key={r.en} r={r} i={topRows.length + i} onEnter={onEnter} />)}
                  </div>
                </div>

                <div className="c__index-foot c-reveal">
                  <button className="c__btn c__btn--primary" onClick={onEnter}>
                    ดูครบทั้ง {total} จังหวัดในแดชบอร์ด <span aria-hidden="true">→</span>
                  </button>
                </div>
              </div>
            </section>
          )}

          {/* Features */}
          <section className="c__feat" id="feat" aria-labelledby="featHeading">
            <div className="c-wrap c__section c__feat-head">
              <div className="c__sec-head c-reveal">
                <div>
                  <div className="c__kicker">ความสามารถ · Capabilities</div>
                  <h2 className="c__h2" id="featHeading">เครื่องมือเบื้องหลังสมุดเล่มนี้</h2>
                </div>
              </div>
            </div>
            <div className="c-wrap c__feat-wrap">
              <div className="c__feat-grid">
                {FEATURES.map(([th, en, desc], i) => (
                  <div className={`c__feat-cell c-reveal c-reveal--delay-${i % 6}`} key={en}>
                    <div className="c__feat-no">{String(i + 1).padStart(2, '0')}</div>
                    <h3>{th}</h3>
                    <span>{en}</span>
                    <p>{desc}</p>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* Methodology */}
          <section className="c__section" id="method" aria-labelledby="methodHeading">
            <div className="c-wrap">
              <div className="c__sec-head c-reveal">
                <div>
                  <div className="c__kicker">วิธีการ · Methodology</div>
                  <h2 className="c__h2" id="methodHeading">แหล่งข้อมูลและกระบวนการ</h2>
                </div>
                {whoFail > 0 && (
                  <p className="c__sec-note">{whoFail} จังหวัดมีพื้นที่สีเขียวต่ำกว่าเกณฑ์ WHO (9 ตร.ม./คน)</p>
                )}
              </div>
              <div className="c__method-grid c-reveal c-reveal--delay-1">
                {SOURCES.map(([head, items]) => (
                  <div key={head}>
                    <div className="c__kicker c__method-kicker">{head}</div>
                    <div className="c__method-list">
                      {items.map(([name, use]) => (
                        <div className="c__method-item" key={name}>
                          <strong>{name}</strong> — {use}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* CTA */}
          <section className="c__cta" id="dashboard" aria-labelledby="ctaHeading">
            <div className="c-wrap">
              <div className="c-reveal">
                <h2 id="ctaHeading">เปิดสมุดดัชนีพื้นที่สีเขียว<br /><em>ของจังหวัดท่าน</em></h2>
                <p>เข้าถึงข้อมูลดาวเทียมเชิงพื้นที่โดยไม่มีค่าใช้จ่าย สำหรับหน่วยงานและสาธารณะ</p>
                <button className="c__btn c__btn--primary" onClick={onEnter}>
                  เข้าสู่แดชบอร์ด <span aria-hidden="true">→</span>
                </button>
                <p className="c__cta-sub">รองรับ Chrome · Firefox · Edge · Safari</p>
              </div>
            </div>
          </section>
        </main>

        {/* Footer */}
        <footer className="c__footer">
          <div className="c-wrap">
            <div className="c__footer-inner">
              <div>
                <b>GreenLens · กรีนเลนส์</b>
                แพลตฟอร์มวิเคราะห์พื้นที่สีเขียวและเกาะความร้อนเมืองจากภาพถ่ายดาวเทียม
                สำหรับหน่วยงานภาครัฐและนักผังเมือง
              </div>
              <div>
                <b>แหล่งข้อมูล</b>
                Copernicus Sentinel-2<br />
                USGS Landsat 8/9<br />
                WorldPop · ESA WorldCover
              </div>
              <div>
                <b>ขอบเขตและแผนที่</b>
                GADM 4.1<br />
                CARTO · OpenStreetMap
              </div>
            </div>
            <div className="c__footer-bottom">
              <span>วิทยานิพนธ์ระดับปริญญาตรี โดย Felsau · MIT License</span>
              {/* ช่องทางถอน/แก้ความยินยอมคุกกี้ — ต้องหาเจอได้ตลอด ไม่ใช่เฉพาะตอน
                  แบนเนอร์ยังค้างอยู่ (PDPA ม.19 วรรคห้า: ถอนต้องง่ายเท่าตอนให้) */}
              <span className="c__footer-legal">
                <button className="consent-link" onClick={onCookieSettings}>ตั้งค่าคุกกี้</button>
                <button className="consent-link" onClick={() => onOpenPolicy('cookies')}>นโยบายคุกกี้</button>
                <button className="consent-link" onClick={() => onOpenPolicy('privacy')}>ความเป็นส่วนตัว</button>
                <button className="consent-link" onClick={() => onOpenPolicy('terms')}>ข้อกำหนด</button>
              </span>
              <span>ข้อมูลล่าสุด {CURRENT_YEAR}</span>
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}
