// ยุบหลักฐานเชิงสถิติของแผงสถิติให้เหลือป้ายเดียวบนหัวข้อ แล้วเก็บรายละเอียดไว้ข้างใน
//
// ทำไมต้องมี: แผงเดิมวางค่าที่ผู้ใช้เอาไปตัดสินใจได้จริง (เรือนยอดขาดอีกกี่ km²)
// ไว้ระดับเดียวกับหลักฐานที่ใส่ไว้ตอบ NFR-07/NFR-08 — ความไม่แน่นอน ±2σ เทียบเกณฑ์
// GCOS-245, จำนวนภาพปลอดเมฆต่อ pixel, ผลเทียบ ESA WorldCover แยกรายประเภทพื้นที่
// คนที่มาวางแผนปลูกต้นไม้จึงต้องอ่านผ่านของที่เขาไม่ได้ใช้ตัดสินใจก่อนถึงจะเจอคำตอบ
//
// ของไม่ได้ถูกตัดทิ้ง แค่ถูกลดลำดับ — กดหัวข้อแล้วเห็นครบเหมือนเดิมทุกตัว
// ผู้ตรวจ/กรรมการยังตามรอย NFR-07/08 ได้ ส่วนผู้ใช้ทั่วไปเห็นแค่ป้ายสรุปบรรทัดเดียว
import Accordion from '../../ui/Accordion';

const BADGE = {
  crit: { text: 'ข้อมูลไม่พอ',   color: 'var(--crit)' },
  warn: { text: 'ใช้อย่างระวัง', color: 'var(--warn)' },
  ok:   { text: 'เชื่อถือได้',   color: 'var(--accent)' },
};

/** ระดับที่แย่ที่สุดของทุกแหล่งเป็นตัวแทน — ป้ายรวมต้องไม่ดูดีกว่าความจริง */
export function trustLevel(dataQuality, validation) {
  if (dataQuality?.level === 'none') return 'crit';
  if (dataQuality?.level === 'below') return 'warn';
  if (validation?.available && !validation.within_target) return 'warn';
  return 'ok';
}

export default function DataTrustSection({
  dataQuality, validation, children,
  title = 'ความน่าเชื่อถือของข้อมูล · เกณฑ์อ้างอิง',
}) {
  // ไม่มีทั้งผลตรวจคุณภาพ ผลเทียบภายนอก และเนื้อหาเสริม = ไม่ต้องขึ้นหัวข้อเปล่า
  if (!dataQuality && !validation?.available && !children) return null;

  const badge = BADGE[trustLevel(dataQuality, validation)];

  return (
    <Accordion
      title={title}
      defaultOpen={false}
      meta={<span style={{ color: badge.color, fontWeight: 600 }}>{badge.text}</span>}
    >
      {children}
    </Accordion>
  );
}
