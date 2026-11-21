import { splitIndexRows, meanUrbanNdvi, splitLeastMost } from './rankingRows';

// ascending by m2 per person: index 0 = lowest = API rank 1
const make = (n) => Array.from({ length: n }, (_, i) => ({
  province: `P${i}`, rank: i + 1, m2_per_person_urban: i + 1, ndvi_mean_urban: 0.1,
}));

describe('splitIndexRows', () => {
  test('77 rows: top 4 highest first, low 4 ending with true lowest', () => {
    const data = make(77);
    const { top, low } = splitIndexRows(data, 4);
    expect(top.map((t) => t.d)).toEqual([data[76], data[75], data[74], data[73]]);
    expect(top.map((t) => t.rank)).toEqual([1, 2, 3, 4]);
    expect(low.map((l) => l.rank)).toEqual([74, 75, 76, 77]);
    expect(low[0].d).toBe(data[3]);
    expect(low[3].d).toBe(data[0]);
  });

  test('6 rows: no overlap', () => {
    const data = make(6);
    const { top, low } = splitIndexRows(data, 4);
    expect(top).toHaveLength(4);
    expect(low.map((l) => l.rank)).toEqual([5, 6]);
    expect(low[low.length - 1].d).toBe(data[0]);
    const tp = new Set(top.map((t) => t.d.province));
    low.forEach((l) => expect(tp.has(l.d.province)).toBe(false));
  });

  test('3 rows: top 3, low empty', () => {
    const { top, low } = splitIndexRows(make(3), 4);
    expect(top).toHaveLength(3);
    expect(low).toEqual([]);
  });

  test('0 rows', () => {
    expect(splitIndexRows([], 4)).toEqual({ top: [], low: [] });
  });
});

describe('meanUrbanNdvi', () => {
  test('averages values and ignores null/undefined', () => {
    expect(meanUrbanNdvi([
      { ndvi_mean_urban: 0.2 }, { ndvi_mean_urban: 0.4 },
      { ndvi_mean_urban: null }, {},
    ])).toBeCloseTo(0.3);
  });
  test('null for empty or all-null', () => {
    expect(meanUrbanNdvi([])).toBeNull();
    expect(meanUrbanNdvi([{ ndvi_mean_urban: null }, {}])).toBeNull();
  });
  test('ignores old ndvi_mean field', () => {
    expect(meanUrbanNdvi([{ ndvi_mean: 0.9 }])).toBeNull();
    expect(meanUrbanNdvi([{ ndvi_mean: 0.9 }, { ndvi_mean_urban: 0.5 }])).toBeCloseTo(0.5);
  });
});

describe('splitLeastMost', () => {
  test('77 rows', () => {
    const data = make(77);
    const { least, most } = splitLeastMost(data, 5);
    expect(least).toEqual(data.slice(0, 5));
    expect(most).toEqual(data.slice(72).reverse());
  });
  test('2 rows: most is empty (no repeat of least)', () => {
    const data = make(2);
    const { least, most } = splitLeastMost(data, 5);
    expect(least).toEqual(data);
    expect(most).toEqual([]);
  });
  test('7 rows: no province in both', () => {
    const data = make(7);
    const { least, most } = splitLeastMost(data, 5);
    expect(least).toHaveLength(5);
    expect(most).toEqual([data[6], data[5]]);
    const ls = new Set(least.map((d) => d.province));
    most.forEach((d) => expect(ls.has(d.province)).toBe(false));
  });
});
