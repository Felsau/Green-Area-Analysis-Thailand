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
  crit:    { text: 'ข้อมูลไม่พอ',    color: 'var(--crit)' },
  warn:    { text: 'ใช้อย่างระวัง',  color: 'var(--warn)' },
  ok:      { text: 'เชื่อถือได้',    color: 'var(--accent)' },
  // ยังไม่มีหลักฐานให้ตัดสิน — ต้องไม่ยืมป้าย ok มาใช้ (ดู trustLevel)
  unknown: { text: 'ยังไม่มีข้อมูล', color: 'var(--ink-3)' },
};

/** ระดับที่แย่ที่สุดของทุกแหล่งเป็นตัวแทน — ป้ายรวมต้องไม่ดูดีกว่าความจริง
 *
 * 'unknown' ต่างจาก 'ok' อย่างมีนัยสำคัญ: ok = ตรวจแล้วผ่าน · unknown = ยังไม่มี
 * อะไรให้ตรวจ (กำลังโหลด / โหลดไม่สำเร็จ / ปีที่ไม่มีภาพ) · เดิม trustLevel ตกลงมาที่
 * `return 'ok'` ในทั้งสองกรณี ทำให้หน้าจอติดป้าย "เชื่อถือได้" ให้ข้อมูลที่ไม่มีอยู่
 * ซึ่งผิดหลักเดียวกับที่แผงนี้ตั้งใจเลี่ยง — ป้ายต้องไม่ดูดีกว่าความจริง
 */
export function trustLevel(dataQuality, validation) {
  if (dataQuality?.level === 'none') return 'crit';
  if (dataQuality?.level === 'below') return 'warn';
  if (validation?.available && !validation.within_target) return 'warn';
  if (!dataQuality && !validation?.available) return 'unknown';
  return 'ok';
}

export default function DataTrustSection({
  dataQuality, validation, children, hasEvidence = false,
  title = 'ความน่าเชื่อถือของข้อมูล · เกณฑ์อ้างอิง',
}) {
  // ไม่มีทั้งผลตรวจคุณภาพ ผลเทียบภายนอก และหลักฐานอื่นที่ลูกจะเอาไปแสดง = ไม่ขึ้นหัวข้อเปล่า
  //
  // เช็ค `hasEvidence` (caller บอกมาว่ามี stats แล้วหรือยัง) ไม่ใช่ `children` —
  // children ที่ StatsTab ส่งมาเป็น array ของ element คงที่ 4 ตัว จึง truthy เสมอ
  // แม้ลูกทุกตัวจะ return null ตอน render · guard เดิมจึงไม่เคยทำงาน หัวข้อขึ้นทุกครั้ง
  // (React ไม่มีทางรู้ล่วงหน้าว่า element จะ render ออกมาเป็น null — ต้องถามจากข้อมูล)
  if (!hasEvidence && !dataQuality && !validation?.available) return null;

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
