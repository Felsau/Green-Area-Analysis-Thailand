// แยกตรรกะจัดอันดับที่หน้าแรก (Landing) กับแดชบอร์ด (OverviewPanel) ใช้ ออกมาเป็น
// ฟังก์ชันล้วน เพื่อทดสอบได้โดยไม่ต้องเรนเดอร์หน้าเว็บ
//
// /analysis/ranking ส่งข้อมูลเรียงจากน้อยไปมาก (rank 1 = m²/คน น้อยที่สุด)

/**
 * หัวตาราง (เขียวที่สุด) กับท้ายตาราง (น้อยที่สุด) ของดัชนีจังหวัด
 * top: มากที่สุดก่อน ได้อันดับ 1..k · low: เรียงต่อจากอันดับ total-k+1 ลงไปจนถึง total
 * ท้ายสุดของ low คือจังหวัดที่น้อยที่สุดจริง (อันดับ = total)
 * ถ้ามีข้อมูลไม่ถึง 2k จังหวัด low จะไม่ซ้ำกับ top
 */
export function splitIndexRows(data, k = 4) {
  const n = data.length;
  const topCount = Math.min(k, n);
  const lowCount = Math.min(k, n - topCount);
  const top = data.slice(n - topCount).reverse()
    .map((d, i) => ({ d, rank: i + 1 }));
  const low = data.slice(0, lowCount).reverse()
    .map((d, i) => ({ d, rank: n - lowCount + 1 + i }));
  return { top, low };
}

/**
 * ค่าเฉลี่ย NDVI ในเขตเมืองของจังหวัดที่มีค่า (ไม่นับ null เป็น 0)
 * คืน null ถ้าไม่มีจังหวัดไหนมีค่า
 */
export function meanUrbanNdvi(data) {
  const vals = data.map((d) => d.ndvi_mean_urban).filter((v) => typeof v === 'number');
  if (!vals.length) return null;
  return vals.reduce((s, v) => s + v, 0) / vals.length;
}

/**
 * ห้าจังหวัดน้อยที่สุดกับมากที่สุดของแดชบอร์ด · ถ้ามีข้อมูลไม่ถึง 2k จังหวัด
 * รายการ "มากที่สุด" เอาเฉพาะจังหวัดที่ไม่อยู่ในรายการ "น้อยที่สุด"
 */
export function splitLeastMost(data, k = 5) {
  const least = data.slice(0, k);
  const mostCount = Math.max(0, Math.min(k, data.length - least.length));
  const most = mostCount ? data.slice(data.length - mostCount).reverse() : [];
  return { least, most };
}
