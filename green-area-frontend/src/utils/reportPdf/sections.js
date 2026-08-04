// Reusable narrative sections — methodology, conclusions, limitations, references.
import { MONTH_NAMES_TH, fmt } from './helpers';
import { COLOR, sectionTitle, paragraph, table } from './components';

const _yearRangeLabel = (year) => {
  const today = new Date();
  if (Number(year) === today.getFullYear()) {
    const m = today.getMonth() + 1;
    return `ม.ค.–${MONTH_NAMES_TH[m - 1]} ${Number(year) + 543} (ข้อมูลปัจจุบัน — ปียังไม่ครบ)`;
  }
  return `ม.ค.–ธ.ค. ${Number(year) + 543}`;
};

export const methodologySection = (year) => `
  ${sectionTitle('แหล่งข้อมูลและวิธีการ (Methodology)', { color: COLOR.muted })}
  ${table(
    ['ตัวชี้วัด', 'แหล่งข้อมูล', 'ความละเอียด', 'การกรอง'],
    [
      // เกณฑ์ต้องตรงกับ routers/ndvi/compute.py — ภาพ < 20% (ผ่อนเป็น < 80% เฉพาะปี/พื้นที่
      // ที่ไม่มีภาพผ่านเลย) แล้ว mask รายพิกเซลด้วย Cloud Score+ ไม่ใช่ QA60 (ESA หยุดเติม
      // QA60 ช่วง ม.ค.2565–ก.พ.2567 → mask กลายเป็น no-op)
      ['NDVI', `Sentinel-2 SR Harmonized (${_yearRangeLabel(year)})`, '10 m', 'CLOUDY_PIXEL_PERCENTAGE < 20% (สำรอง < 80%) + Cloud Score+ cs ≥ 0.6 รายพิกเซล'],
      ['LST',  `Landsat 8/9 Collection 2 Level 2 (${_yearRangeLabel(year)})`, '30 m', 'CLOUD_COVER < 40% + QA_PIXEL cloud mask'],
      // province_population เป็นตาราง seed จาก census/ทะเบียนราษฎร์ (ปีล่าสุดที่มี) —
      // คนละแหล่งกับ WorldPop raster ที่ใช้เฉพาะ Urban Subset (population_urban) · ปีที่ใช้จริง
      // ของแต่ละแหล่งแสดงกำกับที่ตัวเลข (population_year / ปีใน endpoint นั้นๆ) ไม่ตายตัวในตารางนี้
      ['ประชากร (ระดับจังหวัด)', 'ทะเบียนราษฎร์/census รายจังหวัด (seed table)', '—', '—'],
      ['ประชากรในเขตเมือง (Urban Subset)', 'WorldPop (ผ่าน Supabase cache)', '100 m', '—'],
      ['ขอบเขตจังหวัด/อำเภอ', 'GADM v4.1 (Database of Global Administrative Areas)', '—', '—'],
    ],
    { firstColWidth: 110, keepTogether: true }
  )}
  ${paragraph(
    'NDVI คำนวณจาก <b>(B8 − B4) / (B8 + B4)</b> ของภาพ median composite ทั้งปี · พิกเซลน้ำ (NDVI < −0.1) ถูก mask ก่อนคำนวณ min/mean เพื่อหลีกเลี่ยงค่าผิดปกติจากแหล่งน้ำและเงาเมฆ · จำนวนภาพที่เข้า composite และเดือนที่ครอบคลุมจริงของพื้นที่นี้ ดูตาราง <b>"คุณภาพข้อมูล NDVI"</b> ในหัวข้อ NDVI',
    { size: '9.5pt', muted: true }
  )}
  ${paragraph(
    'LST แปลงจาก ST_B10 ของ Landsat โดยสูตร <b>ST_B10 × 0.00341802 + 149.0 − 273.15</b> หน่วย °C · พิจารณาเป็นค่าเฉลี่ย median ของ pixel ที่ผ่าน QA mask',
    { size: '9.5pt', muted: true }
  )}
`;

export const conclusionsSection = ({ ndvi, lst, deficitInfo, comparison }) => {
  if (!ndvi) return '';
  const lines = [];

  if (ndvi.ndvi_mean != null) {
    const interp = ndvi.ndvi_mean >= 0.5 ? 'หนาแน่นสูง'
                : ndvi.ndvi_mean >= 0.3 ? 'ปานกลาง'
                : ndvi.ndvi_mean >= 0.15 ? 'น้อย'
                : 'ต่ำมาก';
    const detail = ndvi.ndvi_mean >= 0.5
      ? 'สอดคล้องกับลักษณะพื้นที่ที่มีป่าหรือเกษตรเข้มข้น เช่น ภูเขา/พื้นที่นอกเมือง'
      : ndvi.ndvi_mean >= 0.3
      ? 'พื้นที่ส่วนใหญ่เป็นเกษตร ทุ่งหญ้า หรือเรือนยอดเปิดโปร่ง'
      : 'พื้นที่ส่วนใหญ่เป็นเมือง/พื้นที่เปิดโล่ง — ควรเพิ่มพืชพรรณในพื้นที่อาศัย';
    lines.push(
      `<b>NDVI เฉลี่ย ${fmt(ndvi.ndvi_mean, 3)}</b> จัดเป็นพืชพรรณ${interp} — ${detail}`
    );
  }

  if (ndvi.green_area_pct != null) {
    const denseTxt = ndvi.dense_area_pct != null
      ? ` ในจำนวนนี้เป็น <b>ป่าหนา (NDVI &gt; 0.5) ${fmt(ndvi.dense_area_pct, 1)}%</b>`
      : '';
    lines.push(
      `พื้นที่สีเขียว (NDVI &gt; 0.3) ครอบคลุม <b>${fmt(ndvi.green_area_pct, 1)}%</b> ของพื้นที่ทั้งหมด${denseTxt} · ` +
      `ค่าที่สูงสะท้อนภูมิประเทศที่มีป่าและเกษตรเป็นหลัก ` +
      (ndvi.dense_area_pct != null && ndvi.green_area_pct - ndvi.dense_area_pct > 30
        ? '<i>โดยส่วนต่างระหว่างสองเกณฑ์ชี้ให้เห็นสัดส่วนพื้นที่เกษตรที่มีนัยสำคัญ</i>'
        : '')
    );
  }

  if (lst?.lst_mean != null) {
    const heat = lst.lst_mean >= 38 ? 'ร้อนจัด'
                : lst.lst_mean >= 32 ? 'ร้อน'
                : lst.lst_mean >= 28 ? 'ปกติ' : 'เย็น';
    const cooling = ndvi?.ndvi_mean != null && ndvi.ndvi_mean >= 0.5
      ? ' — ค่า NDVI ที่สูงน่าจะมีบทบาทช่วยลดอุณหภูมิเทียบกับพื้นที่ที่ NDVI ต่ำ'
      : '';
    lines.push(
      `อุณหภูมิผิวพื้นเฉลี่ย <b>${fmt(lst.lst_mean, 1)}°C</b> (${heat})${cooling}`
    );
  }

  if (deficitInfo) lines.push(deficitInfo);
  if (comparison) lines.push(comparison);

  if (lines.length === 0) return '';
  // wrap heading + items ใน .no-split เพื่อกัน heading orphan ท้ายหน้าก่อน
  return `
    <div class="no-split" style="page-break-inside:avoid;break-inside:avoid;">
      ${sectionTitle('สรุปผลและข้อเสนอแนะ (Conclusions)', { color: COLOR.green })}
      <div style="margin:0 40px 12px;">
        <ol style="padding-left:24px;margin:0;color:${COLOR.text};font-size:10.5pt;line-height:1.75;">
          ${lines.map(l => `<li class="no-split" style="margin-bottom:8px;page-break-inside:avoid;break-inside:avoid;">${l}</li>`).join('')}
        </ol>
      </div>
    </div>
  `;
};

export const limitationsSection = () => {
  // li style รวม break-inside:avoid เพื่อกัน limitation ข้อเดียวถูกตัดข้ามหน้า
  const li = (html) => `
    <li class="no-split" style="margin-bottom:8px;page-break-inside:avoid;break-inside:avoid;">
      ${html}
    </li>`;
  return `
    ${sectionTitle('ข้อจำกัดของการวิเคราะห์ (Limitations)', { color: COLOR.orange })}
    <div style="margin:0 40px 12px;">
      <ol style="padding-left:24px;margin:0;color:${COLOR.text};font-size:10pt;line-height:1.7;">
        ${li(`<b>มาตรฐาน WHO 9 m²/คน</b> หมายถึงพื้นที่สีเขียวที่ประชาชน <b>เข้าถึงได้</b> เช่น สวนสาธารณะหรือพื้นที่นันทนาการในเมือง — ไม่ใช่พื้นที่ NDVI &gt; 0.3 ทั้งหมดที่รวมป่าเขาและเกษตรในชนบท การประเมินตามรายงานนี้จึงมักให้ตัวเลขสูงเกินจริงสำหรับการวางแผนพื้นที่นันทนาการ`)}
        ${li(`<b>เกณฑ์ NDVI &gt; 0.3 เป็น binary classification</b> ที่ไม่แยกแยะ ป่า / เกษตร / ทุ่งหญ้า / สวนผลไม้ ซึ่งมีการจัดการและประโยชน์เชิงนิเวศต่างกัน — ควรใช้ Land Cover map (เช่น ESA WorldCover, MODIS MCD12Q1) ร่วมเพื่อแยกประเภท`)}
        ${li(`<b>การวิเคราะห์เป็นรายปีเดียว</b> และอาจเป็นปีบางส่วน (เช่น ม.ค.–พ.ค. 2569) — ค่ารายปียังไม่สมบูรณ์เมื่อยังไม่ครบทุกฤดูกาล ทำให้แนวโน้มฤดูแล้ง/ฝนสะท้อนไม่ครบ`)}
        ${li(`<b>เมฆและช่องว่างของ revisit</b> — Sentinel-2 (5 วัน) และ Landsat (8 วันรวมทั้ง 8 และ 9) อาจไม่มีภาพที่ผ่านเกณฑ์เมฆในบางเดือน โดยเฉพาะในฤดูฝน — เดือนที่แสดง N/A ในกราฟคือเดือนเหล่านี้`)}
        ${li(`<b>ค่าเฉลี่ยรายปี vs รายเดือน</b> — ค่าเฉลี่ยรายปีคำนวณจาก single median composite ของทั้งปี ส่วนค่ารายเดือนคำนวณ median ของแต่ละเดือนแยกกัน ทั้งสองค่าจึงมักไม่เท่ากันเล็กน้อย เพราะวิธี aggregate ต่างกัน`)}
        ${li(`<b>ประชากรระดับจังหวัด</b> (ตัวหารของ m²/คน ในรายงานนี้และหน้าจัดอันดับ) มาจากทะเบียนราษฎร์/census ปีล่าสุดที่มีในระบบ — เป็นค่าคงที่ต่อจังหวัดต่อปี ไม่ได้ปรับตามฤดูกาล/การย้ายถิ่นระหว่างปี`)}
        ${li(`<b>WorldPop</b> (ใช้เฉพาะ Urban Subset — population_urban) เป็น gridded population estimate ความละเอียด 100 m ที่ disaggregate มาจาก census ผ่าน covariates (สิ่งปลูกสร้าง, แสงไฟกลางคืน) — ไม่ใช่การสำรวจประชากรในตำแหน่งจริง การคำนวณ "พื้นที่ต่อคน" ในเขตเมืองจึงมี uncertainty ระดับชุมชน`)}
        ${li(`<b>NDVI Min</b> หลังการ mask water (NDVI &lt; 0) ที่ยังต่ำผิดปกติบ่งชี้ว่ามี cloud-shadow บาง pixel ที่หลุดเงื่อนไข — โปรดตีความ Min ด้วยความระมัดระวัง`)}
      </ol>
    </div>
  `;
};

// References (เอกสารอ้างอิง) — wrap ทั้งก้อนใน .no-split เพื่อให้ refs ทุกอันอยู่หน้าเดียว
// (refs 7 รายการ ~400px เข้าหน้าเดียวได้)
export const referencesSection = () => {
  const ref = (html) => `
    <li style="margin-bottom:5px;page-break-inside:avoid;break-inside:avoid;">
      ${html}
    </li>`;
  return `
    <div class="no-split" style="page-break-inside:avoid;break-inside:avoid;">
      ${sectionTitle('เอกสารอ้างอิง (References)', { color: COLOR.muted })}
      <div style="margin:0 40px 14px;">
        <ol style="padding-left:24px;margin:0;color:${COLOR.text};font-size:9.5pt;line-height:1.55;">
          ${ref(`Drusch, M., Del Bello, U., Carlier, S., et al. (2012). <i>Sentinel-2: ESA's Optical High-Resolution Mission for GMES Operational Services.</i> Remote Sensing of Environment, 120, 25–36. doi:10.1016/j.rse.2011.11.026`)}
          ${ref(`U.S. Geological Survey (2021). <i>Landsat Collection 2 Level-2 Science Products — Surface Temperature.</i> USGS Earth Resources Observation and Science Center. https://www.usgs.gov/landsat-missions/landsat-collection-2-level-2-science-products`)}
          ${ref(`Tatem, A.J. (2017). <i>WorldPop, open data for spatial demography.</i> Scientific Data, 4, 170004. doi:10.1038/sdata.2017.4`)}
          ${ref(`Global Administrative Areas (2022). <i>GADM database of Global Administrative Areas, version 4.1.</i> https://gadm.org/`)}
          ${ref(`World Health Organization Regional Office for Europe (2017). <i>Urban green spaces: a brief for action.</i> WHO Regional Office for Europe, Copenhagen.`)}
          ${ref(`Gorelick, N., Hancher, M., Dixon, M., et al. (2017). <i>Google Earth Engine: Planetary-scale geospatial analysis for everyone.</i> Remote Sensing of Environment, 202, 18–27. doi:10.1016/j.rse.2017.06.031`)}
          ${ref(`Tucker, C.J. (1979). <i>Red and photographic infrared linear combinations for monitoring vegetation.</i> Remote Sensing of Environment, 8(2), 127–150.`)}
        </ol>
      </div>
    </div>
  `;
};
