import {
  getNdviColor, getNdviLabel, getLstColor, getLstLabel, getNdviRgba,
} from './colorUtils';

describe('getNdviColor', () => {
  test('null → light fallback', () => expect(getNdviColor(null)).toBe('#bbf7d0'));
  test('dense band (≥0.6)', () => expect(getNdviColor(0.7)).toBe('#22c55e'));
  test('boundary 0.6 counts as dense', () => expect(getNdviColor(0.6)).toBe('#22c55e'));
  test('mid band (0.45–0.6)', () => expect(getNdviColor(0.5)).toBe('#4ade80'));
  test('low-mid band (0.3–0.45)', () => expect(getNdviColor(0.3)).toBe('#86efac'));
  test('below 0.3 → sparse', () => expect(getNdviColor(0.1)).toBe('#bbf7d0'));
});

describe('getLstColor', () => {
  test('null → grey', () => expect(getLstColor(null)).toBe('#dadce0'));
  test('cool (<28)', () => expect(getLstColor(25)).toBe('#60a5fa'));
  test('boundary 28 → warm (not cool)', () => expect(getLstColor(28)).toBe('#fbbf24'));
  test('hot band (≥38)', () => expect(getLstColor(40)).toBe('#ef4444'));
});

describe('labels', () => {
  test('ndvi null → dash', () => expect(getNdviLabel(null)).toBe('—'));
  test('ndvi dense label', () => expect(getNdviLabel(0.7)).toBe('พืชพรรณหนาแน่น'));
  test('lst hot label', () => expect(getLstLabel(40)).toBe('ร้อนมาก'));
  test('lst cool label', () => expect(getLstLabel(20)).toBe('เย็น'));
});

describe('getNdviRgba', () => {
  test('null → translucent fallback', () => expect(getNdviRgba(null)).toEqual([200, 230, 200, 120]));
  test('dense uses the alpha argument', () => expect(getNdviRgba(0.7, 150)).toEqual([34, 197, 94, 150]));
  test('default alpha is 200', () => expect(getNdviRgba(0.5)).toEqual([74, 222, 128, 200]));
});
