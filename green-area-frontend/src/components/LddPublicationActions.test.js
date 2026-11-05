import { fireEvent, render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import LddPublicationActions from './LddPublicationActions';

describe('LddPublicationActions', () => {
  const dataset = {
    id: 'dataset-ldd-1',
    revision: 2,
    active_edition_id: null,
    province: 'Chiang Mai',
    data_year: 2025,
  };

  const edition = {
    id: 'edition-ldd-1',
    input_revision: 3,
    input_hash: 'c'.repeat(64),
    validated_result_id: 'result-ldd-1',
    upload: { sha256: 'd'.repeat(64) },
    state: 'validated',
  };

  test('renders publication actions for inactive edition and handles activation and rollback', () => {
    const onAction = vi.fn();
    render(
      <LddPublicationActions
        dataset={dataset}
        edition={edition}
        editions={[edition]}
        pending={false}
        onAction={onAction}
      />
    );

    expect(screen.getByText('ยังไม่ได้เปิดใช้ฉบับนี้ · ไม่เปลี่ยน NDVI/LST')).toBeInTheDocument();
    const activateButton = screen.getByRole('button', { name: 'เปิดใช้ LDD (Local)' });
    const rollbackButton = screen.getByRole('button', { name: 'ย้อนกลับมาฉบับนี้' });
    const withdrawButton = screen.getByRole('button', { name: 'ถอนฉบับนี้ (ไม่แทนที่)' });

    expect(activateButton).toBeInTheDocument();
    expect(rollbackButton).toBeInTheDocument();
    expect(withdrawButton).toBeInTheDocument();

    fireEvent.click(activateButton);
    expect(onAction).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'เปิดใช้ LDD ใน Local Dashboard',
        path: '/datasets/dataset-ldd-1/ldd-publication/activation',
        body: expect.objectContaining({
          edition_id: 'edition-ldd-1',
          expected_dataset_revision: 2,
          expected_active_edition_id: null,
          method_version: 'ldd-source-area-v1',
          coverage_mode: 'validated_source_footprint',
        }),
      })
    );

    fireEvent.click(rollbackButton);
    expect(onAction).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'ย้อนกลับ LDD ไปฉบับที่เคยเปิดใช้',
        path: '/datasets/dataset-ldd-1/ldd-publication/rollback',
        body: expect.objectContaining({
          edition_id: 'edition-ldd-1',
          expected_dataset_revision: 2,
          expected_active_edition_id: null,
        }),
      })
    );
  });

  test('renders publication actions for active edition and handles withdrawal with replacement', () => {
    const activeDataset = { ...dataset, active_edition_id: edition.id };
    const replacementEdition = {
      id: 'edition-ldd-2-replacement',
      input_revision: 1,
      input_hash: 'e'.repeat(64),
      validated_result_id: 'result-ldd-2',
      upload: { sha256: 'f'.repeat(64) },
      state: 'validated',
    };

    const onAction = vi.fn();
    render(
      <LddPublicationActions
        dataset={activeDataset}
        edition={edition}
        editions={[edition, replacementEdition]}
        pending={false}
        onAction={onAction}
      />
    );

    expect(screen.getByText('กำลังเปิดใช้ฉบับนี้ · ไม่เปลี่ยน NDVI/LST')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'เปิดใช้ LDD (Local)' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'ย้อนกลับมาฉบับนี้' })).not.toBeInTheDocument();

    const replaceButton = screen.getByRole('button', {
      name: `ถอนและใช้ฉบับ ${replacementEdition.id.slice(0, 8)} แทน`,
    });
    expect(replaceButton).toBeInTheDocument();

    fireEvent.click(replaceButton);
    expect(onAction).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'ถอนฉบับและใช้ฉบับแทนที่ที่ตรวจไฟล์ใหม่',
        path: '/datasets/dataset-ldd-1/ldd-publication/withdrawal',
        body: expect.objectContaining({
          edition_id: 'edition-ldd-1',
          replacement_edition_id: 'edition-ldd-2-replacement',
          expected_active_edition_id: 'edition-ldd-1',
        }),
      })
    );

    const withdrawNoReplace = screen.getByRole('button', { name: 'ถอนฉบับนี้ (ไม่แทนที่)' });
    fireEvent.click(withdrawNoReplace);
    expect(onAction).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'ถอนฉบับ LDD แบบถาวร โดยเก็บประวัติ',
        path: '/datasets/dataset-ldd-1/ldd-publication/withdrawal',
        body: expect.objectContaining({
          edition_id: 'edition-ldd-1',
          replacement_edition_id: null,
          expected_active_edition_id: 'edition-ldd-1',
        }),
      })
    );
  });

  test('disables all action buttons when pending is true', () => {
    const onAction = vi.fn();
    render(
      <LddPublicationActions
        dataset={dataset}
        edition={edition}
        editions={[edition]}
        pending={true}
        onAction={onAction}
      />
    );

    const buttons = screen.getAllByRole('button');
    expect(buttons.length).toBeGreaterThan(0);
    buttons.forEach((btn) => {
      expect(btn).toBeDisabled();
    });
  });
});
