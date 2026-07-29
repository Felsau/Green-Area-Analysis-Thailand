// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom';

// Polyfill TextEncoder/TextDecoder ที่ jsdom ไม่มี — jspdf → fast-png → iobuffer ต้องใช้
import { TextEncoder, TextDecoder } from 'util';
if (typeof global.TextEncoder === 'undefined') global.TextEncoder = TextEncoder;
if (typeof global.TextDecoder === 'undefined') global.TextDecoder = TextDecoder;

// fetch mock — ตั้ง default ไว้ที่นี่เพื่อให้ครอบคลุมทุก test
// payload เดียวรองรับทั้ง /cache, /cache/ndvi-latest (data) และ /thailand.json
const fetchOk = () => Promise.resolve({
  ok: true,
  json: () => Promise.resolve({
    annual: [], monthly: [], count: 0, data: {},
    type: 'FeatureCollection', features: [],
  }),
});
global.fetch = vi.fn(fetchOk);
if (typeof window !== 'undefined') window.fetch = global.fetch;

beforeEach(() => {
  global.fetch.mockImplementation(fetchOk);
});
