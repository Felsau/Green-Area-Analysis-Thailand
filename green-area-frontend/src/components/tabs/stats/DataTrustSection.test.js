import { render, screen } from '@testing-library/react';
import DataTrustSection, { trustLevel } from './DataTrustSection';

// ป้ายบนหัวข้อนี้เป็นคำรับรองความน่าเชื่อถือ — ต้องไม่ดูดีกว่าความจริง โดยเฉพาะ
// กรณี "ยังไม่มีข้อมูล" ที่เดิมตกลงมาที่ 'ok' แล้วติดป้าย "เชื่อถือได้" ให้ข้อมูลที่ไม่มีอยู่

describe('trustLevel', () => {
  it('ไม่มีทั้ง dataQuality และ validation = unknown (ไม่ใช่ ok)', () => {
    expect(trustLevel(undefined, undefined)).toBe('unknown');
    expect(trustLevel(null, null)).toBe('unknown');
    expect(trustLevel(undefined, { available: false })).toBe('unknown');
  });

  it('level none = crit', () => {
    expect(trustLevel({ level: 'none' }, undefined)).toBe('crit');
  });

  it('level below = warn', () => {
    expect(trustLevel({ level: 'below' }, undefined)).toBe('warn');
  });

  it('validation ที่ไม่เข้าเป้า = warn', () => {
    expect(trustLevel({ level: 'goal' }, { available: true, within_target: false }))
      .toBe('warn');
  });

  it('มีหลักฐานและผ่านทั้งหมด = ok', () => {
    expect(trustLevel({ level: 'goal' }, { available: true, within_target: true }))
      .toBe('ok');
    expect(trustLevel({ level: 'threshold' }, undefined)).toBe('ok');
  });

  it('crit ชนะ warn เมื่อเกิดพร้อมกัน (เอาระดับแย่สุด)', () => {
    expect(trustLevel({ level: 'none' }, { available: true, within_target: false }))
      .toBe('crit');
  });
});

describe('DataTrustSection', () => {
  // children ที่ StatsTab ส่งมาเป็น array คงที่ จึง truthy เสมอแม้ลูกจะ render null
  const alwaysTruthyChildren = [<div key="a" />, <div key="b" />];

  it('ไม่ render อะไรเลยเมื่อไม่มีหลักฐาน แม้จะมี children ที่ truthy', () => {
    const { container } = render(
      <DataTrustSection hasEvidence={false}>{alwaysTruthyChildren}</DataTrustSection>
    );
    expect(container.innerHTML).toBe('');
  });

  it('มี stats แล้วแต่ยังไม่มีผลตรวจคุณภาพ = ป้าย "ยังไม่มีข้อมูล" ไม่ใช่ "เชื่อถือได้"', () => {
    render(<DataTrustSection hasEvidence={true}>{alwaysTruthyChildren}</DataTrustSection>);
    expect(screen.getByText('ยังไม่มีข้อมูล')).toBeInTheDocument();
    expect(screen.queryByText('เชื่อถือได้')).not.toBeInTheDocument();
  });

  it('ขึ้นหัวข้อจาก dataQuality ได้เองแม้ caller ไม่ส่ง hasEvidence', () => {
    render(<DataTrustSection dataQuality={{ level: 'goal' }}>{alwaysTruthyChildren}</DataTrustSection>);
    expect(screen.getByText('เชื่อถือได้')).toBeInTheDocument();
  });

  it('ขึ้นหัวข้อจาก validation ได้เองแม้ caller ไม่ส่ง hasEvidence', () => {
    render(
      <DataTrustSection validation={{ available: true, within_target: false }}>
        {alwaysTruthyChildren}
      </DataTrustSection>
    );
    expect(screen.getByText('ใช้อย่างระวัง')).toBeInTheDocument();
  });

  it('แสดงป้ายตามระดับที่แย่สุดพร้อมหัวข้อ default', () => {
    render(<DataTrustSection dataQuality={{ level: 'none' }}>{alwaysTruthyChildren}</DataTrustSection>);
    expect(screen.getByText('ข้อมูลไม่พอ')).toBeInTheDocument();
    expect(screen.getByText(/ความน่าเชื่อถือของข้อมูล/)).toBeInTheDocument();
  });
});
