import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import LddPreparedPreview from './LddPreparedPreview';
import { gisRequest } from '../utils/gisClient';
vi.mock('../utils/gisClient', () => ({ gisRequest: vi.fn() }));
const dataset = { revision: 2, province: 'Bangkok Metropolis', data_year: 2026 };
const edition = { id: '11111111-1111-4111-8111-111111111111', input_revision: 1, input_hash: 'a'.repeat(64) };
const job = { id: '22222222-2222-4222-8222-222222222222', state: 'succeeded', progress: 100 };
const ring = [[100,13],[100.01,13],[100.01,13.01],[100,13.01],[100,13]];
const hole = [[100.002,13.002],[100.008,13.002],[100.008,13.008],[100.002,13.008],[100.002,13.002]];
function show(data) {
  gisRequest.mockResolvedValue(data);
  const action = vi.fn();
  render(<LddPreparedPreview dataset={dataset} edition={edition} version={0} onAction={action} pending={false} />);
  fireEvent.click(screen.getByText('เตรียมข้อมูล / ดูตัวอย่าง LDD'));
  return action;
}

beforeEach(() => vi.clearAllMocks());
test('prepare uses existing confirmation callback with current scope and revision', async () => {
  const action = show({ status: 'not_prepared', ready_for_publication: false });
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  fireEvent.click(screen.getByText('สั่งเตรียมข้อมูล LDD'));
  expect(action).toHaveBeenCalledWith(expect.objectContaining({ path: `/editions/${edition.id}/prepare-jobs`,
    body: { expected_dataset_revision: 2, expected_input_revision: 1, input_hash: edition.input_hash, province: dataset.province, data_year: 2026 } }));
});
test('worker candidate requires a separate trusted verification', async () => {
  const action = show({ status: 'succeeded', prepared: true, ready_for_publication: false, job, attempts: [{}] });
  fireEvent.click(await screen.findByText('ตรวจไฟล์จริงและเปิด Preview'));
  expect(action).toHaveBeenCalledWith(expect.objectContaining({ path: `/editions/${edition.id}/prepare-verification`, body: { job_id: job.id } }));
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});
test('verified geometry preserves holes and labels the data as preview only', async () => {
  show({ status: 'verified_for_local_review', ready_for_publication: true, method_version: 'ldd-source-area-v1', job, attempts: [{}],
    geometry: { features: [{ geometry: { type: 'Polygon', coordinates: [ring,hole] } }] },
    summary: { feature_count: 3, total_area_m2: 6400, area_by_code_m2: { 'A101/A401': 6400 }, metadata: { source_sha256: 'b'.repeat(64) } } });
  const svg = await screen.findByRole('img');
  expect(svg.querySelector('path').getAttribute('fill-rule')).toBe('evenodd');
  expect(screen.getByText(/Local Preview เท่านั้น/)).toBeInTheDocument();
  expect(screen.getByText('A101/A401')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /เปิดใช้ฉบับ/ })).not.toBeInTheDocument();
});
test('revoked files never show geometry or offer verification as if valid', async () => {
  show({ status: 'verification_revoked', prepared: true, ready_for_publication: false, job });
  await screen.findByText(/ไฟล์หายหรือเสียหาย/);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(screen.queryByText('ตรวจไฟล์จริงและเปิด Preview')).not.toBeInTheDocument();
});
test('a failed recheck clears previously verified geometry', async () => {
  show({ status: 'verified_for_local_review', ready_for_publication: true, job,
    geometry: { features: [{ geometry: { type: 'Polygon', coordinates: [ring] } }] },
    summary: { feature_count: 1, total_area_m2: 6400, area_by_code_m2: {}, metadata: {} } });
  await screen.findByRole('img');
  gisRequest.mockRejectedValueOnce(new Error('ตรวจไฟล์รอบใหม่ไม่สำเร็จ'));
  fireEvent.click(screen.getByText('รีเฟรชสถานะเตรียมข้อมูล'));
  await screen.findByRole('alert');
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(screen.queryByText(/ตรวจไฟล์จริงผ่าน พร้อมให้ตรวจทาน/)).not.toBeInTheDocument();
});
