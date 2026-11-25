import { render, screen, fireEvent } from '@testing-library/react';
import StatsTab, { urbanFallbackHint, degC } from './StatsTab';
import { exportStatsCsv } from '../../utils/exportUtils';

vi.mock('../../utils/exportUtils', () => ({ exportStatsCsv: vi.fn() }));

// แถว "ต่อหัวประชากร" ถอยไปแสดงค่าทั้งจังหวัดเมื่อไม่มีค่าเขตเมือง — ข้อความกำกับ
// ต้องบอกเหตุผลตามสถานะจริงของคำขอ ไม่ใช่โชว์ "กำลังดึง…" ค้างไว้ทุกกรณีที่ค่ายังไม่มา
describe('urbanFallbackHint', () => {
  it('กำลังโหลด → บอกว่ากำลังดึง', () => {
    expect(urbanFallbackHint('loading', null)).toBe('กำลังดึงค่าเฉพาะเขตเมือง…');
  });

  it('โหลดไม่สำเร็จ → บอกว่าไม่สำเร็จ + กำกับว่าค่าที่เห็นคือทั้งจังหวัด', () => {
    const hint = urbanFallbackHint('error', null);
    expect(hint).toContain('ไม่สำเร็จ');
    expect(hint).toContain('ทั้งจังหวัด');
    expect(hint).not.toContain('กำลังดึง');
  });

  it('สำเร็จแต่หารไม่ได้ (ประชากรเขตเมือง 0) → อธิบายเหตุ ไม่ใช่ข้อความโหลด', () => {
    const hint = urbanFallbackHint('ready', { m2_per_person_urban: null, population_urban: 0 });
    expect(hint).toContain('ประชากร');
    expect(hint).not.toContain('กำลังดึง');
  });

  it('ยังไม่เริ่มคำขอ → ไม่มีข้อความ', () => {
    expect(urbanFallbackHint('idle', null)).toBeNull();
  });

  it('สำเร็จและมีค่าแล้ว → ไม่มีข้อความ (แถวนี้ไม่ถูกใช้อยู่แล้ว)', () => {
    expect(urbanFallbackHint('ready', { m2_per_person_urban: 38.2 })).toBeNull();
  });

  // regression: เดิม UI เช็ค `urbanStats === null` ตัวเดียว ซึ่งเป็นจริงทั้งตอน
  // loading และ error → ข้อความโหลดค้างตลอดกาลหลังคำขอล้ม
  it('ไม่มีสถานะไหนนอกจาก loading ที่ให้ข้อความ "กำลังดึง"', () => {
    ['idle', 'ready', 'error'].forEach(status => {
      expect(urbanFallbackHint(status, null)).not.toBe('กำลังดึงค่าเฉพาะเขตเมือง…');
    });
  });
});

// backend คืน lst_* = null เมื่อไม่มีภาพ Landsat ที่ใช้ได้ (เดิมกลบเป็น 0 ซึ่งหน้าเว็บ
// แสดงเป็น "0°C" เหมือนค่าที่วัดได้จริง) — UI ต้องแสดง "—" ไม่ใช่ "null°C"
describe('degC', () => {
  it('มีค่า → ต่อท้ายด้วยหน่วย', () => {
    expect(degC(31.4)).toBe('31.4°C');
  });

  it('0 °C เป็นค่าที่วัดได้จริง ไม่ใช่ค่าว่าง', () => {
    expect(degC(0)).toBe('0°C');
  });

  it('null/undefined → ขีด ไม่ใช่ "null°C"', () => {
    expect(degC(null)).toBe('—');
    expect(degC(undefined)).toBe('—');
  });
});

// B2: ระหว่างโหลด NDVI/LST ค่าเดิมถูกล้างเป็น null — ส่งออกตอนนี้ได้ไฟล์ว่าง
describe('export while loading', () => {
  const handlers = new Proxy({}, { get: () => () => {} });
  const renderStats = (loading) => render(<StatsTab data={{
    selectedProvince: 'กรุงเทพมหานคร', selectedProvinceEN: 'Bangkok Metropolis',
    ndviLoading: loading, lstLoading: loading,
    ndviStats: null, lstStats: null, ndviMonthly: [], lstMonthly: [],
    urbanStatus: loading ? 'loading' : 'idle', landuseLoading: false,
  }} handlers={handlers} />);

  beforeEach(() => vi.clearAllMocks());

  it('ระหว่างโหลด → ปุ่มส่งออกกดไม่ได้ และกด CSV ไม่ส่งออก', () => {
    renderStats(true);
    const csv = screen.getByRole('button', { name: 'CSV' });
    expect(csv).toBeDisabled();
    fireEvent.click(csv);
    expect(exportStatsCsv).not.toHaveBeenCalled();
  });

  it('โหลดเสร็จ → กด CSV ส่งออกได้ตามเดิม', () => {
    renderStats(false);
    const csv = screen.getByRole('button', { name: 'CSV' });
    expect(csv).toBeEnabled();
    fireEvent.click(csv);
    expect(exportStatsCsv).toHaveBeenCalledTimes(1);
  });
});
