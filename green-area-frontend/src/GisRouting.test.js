import { fireEvent, render, screen } from '@testing-library/react';
import App from './App';
import { useAuth } from './hooks/useAuth';
import { useGisAccess } from './hooks/useGisAccess';

vi.mock('./hooks/useAuth', () => ({ useAuth: vi.fn() }));
vi.mock('./hooks/useGisAccess', () => ({ useGisAccess: vi.fn() }));
vi.mock('./Dashboard', () => ({ default: ({ onOpenGis }) => <div><h1>แผนที่เดิม</h1>{onOpenGis && <button onClick={onOpenGis}>เปิด GIS</button>}</div> }));
vi.mock('./components/GisManagement', () => ({ default: ({ onBack }) => <div><h1>หน้าจัดการ GIS</h1><button onClick={onBack}>กลับแผนที่</button></div> }));
beforeEach(() => { window.history.replaceState(null, '', '/?p=Bangkok&year=2024'); useAuth.mockReturnValue({ user: { id: 'test' } }); useGisAccess.mockReturnValue({ allowed: true }); });
test('navigation preserves map deep-link parameters and supports browser Back', async () => {
  render(<App />); fireEvent.click(await screen.findByText('เปิด GIS')); await screen.findByText('หน้าจัดการ GIS'); expect(new URLSearchParams(location.search).get('p')).toBe('Bangkok');
  fireEvent.click(screen.getByText('กลับแผนที่')); await screen.findByText('แผนที่เดิม'); expect(location.search).toBe('?p=Bangkok&year=2024');
  window.history.replaceState(null, '', '/?view=gis'); fireEvent.popState(window); await screen.findByText('หน้าจัดการ GIS');
});
test('unauthorized profile has no navigation action', async () => {
  useGisAccess.mockReturnValue({ allowed: false }); render(<App />); await screen.findByText('แผนที่เดิม'); expect(screen.queryByText('เปิด GIS')).not.toBeInTheDocument();
});
test('GIS deep link goes through existing sign-in flow', async () => {
  useAuth.mockReturnValue({ user: null, initializing: false }); window.history.replaceState(null, '', '/?view=gis'); render(<App />);
  expect(await screen.findByRole('heading', { name: 'เข้าสู่ระบบ' })).toBeInTheDocument(); expect(screen.queryByText('หน้าจัดการ GIS')).not.toBeInTheDocument();
});
