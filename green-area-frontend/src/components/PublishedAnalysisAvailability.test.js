import {fireEvent,render,screen} from '@testing-library/react';
import {publishedGeoFixture,publishedLddFixture} from '../testFixtures/publishedSnapshots';
import PublishedAnalysisAvailability from './PublishedAnalysisAvailability';

test('availability is accessible and bound to the current edition and snapshot',()=>{
  const b=publishedGeoFixture();const {rerender}=render(<PublishedAnalysisAvailability bundle={b} kind="raster"/>);
  fireEvent.click(screen.getByText('ความพร้อมของฟีเจอร์วิเคราะห์ Published'));
  expect(screen.getByRole('region',{name:'ความพร้อมของฟีเจอร์ Published'})).toHaveAttribute('data-source-snapshot',b.snapshot_id);
  expect(screen.getByText(/Edition/)).toHaveTextContent(b.source_identity.edition_id);
  expect(screen.getByText(/Timeseries.*ยังไม่รองรับ/)).toBeVisible();
  rerender(<PublishedAnalysisAvailability bundle={null} kind="raster"/>);
  expect(screen.queryByText(/edition-a/)).not.toBeInTheDocument();expect(screen.getByText(/แผนที่.*ยังไม่พร้อม/)).toBeVisible();
});
test('selected unsupported navigation shows a specific reason and no fabricated numeric result',()=>{
  render(<PublishedAnalysisAvailability bundle={publishedLddFixture()} kind="landuse" feature="compare"/>);
  expect(screen.getByText(/เปรียบเทียบจังหวัด.*ยังไม่รองรับ/)).toBeVisible();expect(screen.getByText(/ครอบคลุมจังหวัด/)).toBeVisible();
});
