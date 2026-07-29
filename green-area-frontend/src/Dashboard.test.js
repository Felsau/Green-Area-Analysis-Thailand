// Smoke test for the dashboard shell. App.test.js can no longer reach it —
// Dashboard is lazy-loaded behind the auth gate, so App's tests stop at the
// landing/sign-in screens. This mounts it directly with a fake signed-in
// `auth`, which is what catches a broken import or a hook wired to the wrong
// prop after the split out of App.js.
import { render, screen, waitFor } from '@testing-library/react';
import Dashboard from './Dashboard';

// WebGL/mapping libs don't run under jsdom — same stubs App.test.js uses.
vi.mock('@deck.gl/react', () => ({
  __esModule: true,
  default: ({ children }) => <div data-testid="deckgl">{children}</div>,
}));
vi.mock('@deck.gl/layers', () => ({
  GeoJsonLayer: class {},
  BitmapLayer: class {},
  ScatterplotLayer: class {},
  TextLayer: class {},
}));
vi.mock('@deck.gl/geo-layers', () => ({ TileLayer: class {} }));
vi.mock('@deck.gl/extensions', () => ({ ClipExtension: class {} }));
vi.mock('@deck.gl/core', () => ({
  FlyToInterpolator: class {},
  WebMercatorViewport: class { getBounds() { return [0, 0, 1, 1]; } },
}));
vi.mock('@turf/turf', () => ({ area: () => 0, bbox: () => [0, 0, 0, 0] }));
vi.mock('react-map-gl/maplibre', () => ({ __esModule: true, default: () => null }));

const auth = {
  user: { id: 'u1', email: 'test@example.com' },
  profile: { display_name: 'ผู้ทดสอบ', role: 'user' },
  signOut: vi.fn(),
};

const renderDashboard = (props = {}) => render(
  <Dashboard
    thailandData={{ type: 'FeatureCollection', features: [] }}
    loading={false}
    theme="light"
    onToggleTheme={vi.fn()}
    auth={auth}
    onGoHome={vi.fn()}
    onCookieSettings={vi.fn()}
    onOpenPolicy={vi.fn()}
    {...props}
  />
);

beforeEach(() => {
  window.history.replaceState(null, '', '/');  // ล้าง deep-link param จากเทสต์ก่อนหน้า
});

test('mounts the map canvas and the sidebar', async () => {
  renderDashboard();
  expect(await screen.findByTestId('deckgl')).toBeInTheDocument();
  // แถบเครื่องมือบนแผนที่ = ตัวบอกว่า render ผ่านครบทั้งต้นไม้ ไม่ได้หยุดกลางทาง
  expect(screen.getByRole('button', { name: 'วาดพื้นที่วิเคราะห์เอง' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'พื้นที่ที่บันทึกไว้' })).toBeInTheDocument();
});

test('round-trips the ?tab= deep link through state and back into the URL', async () => {
  // แท็บบนแถบข้างจะ render ก็ต่อเมื่อเลือกจังหวัดแล้ว จึงยืนยันที่ URL แทน:
  // ตัว reader อ่าน ?tab= เข้า state แล้ว writer เขียนกลับ — ถ้า reader พัง
  // sidebarTab จะเป็น 'stats' (ค่า default) แล้ว writer จะล้าง query ทิ้งทั้งอัน
  window.history.replaceState(null, '', '/?tab=recommend');
  renderDashboard();
  await screen.findByTestId('deckgl');
  await waitFor(() => expect(window.location.search).toBe('?tab=recommend'));
});
