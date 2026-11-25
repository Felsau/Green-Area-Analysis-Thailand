import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ExportBar from './ExportBar';
import { exportElementPng, exportTabWithMapPng } from '../../utils/export/image';

vi.mock('../../utils/export/image', () => ({
  exportElementPng: vi.fn(),
  exportTabWithMapPng: vi.fn(),
}));

const labels = ['CSV', 'PNG', 'PDF', 'PNG + แผนที่'];

const setup = (props = {}) => {
  const onCsv = vi.fn();
  const onPdf = vi.fn();
  render(<ExportBar targetId="t" baseName="b" onCsv={onCsv} onPdf={onPdf} {...props} />);
  return { onCsv, onPdf };
};

beforeEach(() => vi.clearAllMocks());

// B2: ข้อมูลยังโหลดไม่เสร็จ → ห้ามส่งออก (ได้ไฟล์ว่าง/ครึ่งเดียว/ของรอบก่อน)
test('disabled → every export button is disabled and clicking exports nothing', async () => {
  const { onCsv, onPdf } = setup({ disabled: true });
  for (const l of labels) {
    const btn = screen.getByRole('button', { name: l });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
  }
  await Promise.resolve();
  expect(onCsv).not.toHaveBeenCalled();
  expect(onPdf).not.toHaveBeenCalled();
  expect(exportElementPng).not.toHaveBeenCalled();
  expect(exportTabWithMapPng).not.toHaveBeenCalled();
});

test('not disabled → buttons are enabled and each one runs its export', async () => {
  const { onCsv, onPdf } = setup();
  for (const l of labels) expect(screen.getByRole('button', { name: l })).toBeEnabled();

  fireEvent.click(screen.getByRole('button', { name: 'CSV' }));
  await waitFor(() => expect(onCsv).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole('button', { name: 'PDF' })).toBeEnabled());

  fireEvent.click(screen.getByRole('button', { name: 'PDF' }));
  await waitFor(() => expect(onPdf).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole('button', { name: 'PNG' })).toBeEnabled());

  fireEvent.click(screen.getByRole('button', { name: 'PNG' }));
  await waitFor(() => expect(exportElementPng).toHaveBeenCalledWith('t', 'b.png'));
  await waitFor(() => expect(screen.getByRole('button', { name: 'PNG + แผนที่' })).toBeEnabled());

  fireEvent.click(screen.getByRole('button', { name: 'PNG + แผนที่' }));
  await waitFor(() => expect(exportTabWithMapPng).toHaveBeenCalledWith('t', 'b_with_map.png'));
});
