import { render, screen } from '@testing-library/react';
import SpeciesSection from './SpeciesSection';

// รูปร่างเดียวกับที่ backend คืนมา — พันธุ์ไม้แต่ละชนิดแนบ verification ที่สร้างจาก
// data/tree_species.json (ตรวจกับ BGCI GlobalTreeSearch / Kew WCVP / GBIF)
const NATIVE = {
  name_th: 'ประดู่ป่า',
  scientific: 'Pterocarpus macrocarpus',
  purpose: 'ฟื้นฟูป่า/ร่มเงา',
  height_m: '15–25',
  traits: ['ทนแล้งสุดยอด'],
  reason: 'ทนภัยแล้งและดินทรายของอีสานได้ดีที่สุด',
  verification: {
    gbif_url: 'https://www.gbif.org/species/5352530',
    bgci_is_tree: true,
    bgci_native_to_thailand: true,
    bgci_native_range: [],
    wcvp_thailand: 'NATIVE',
    gbif_records_in_this_region: 404,
  },
};

const EXOTIC = {
  name_th: 'หางนกยูงฝรั่ง',
  scientific: 'Delonix regia',
  purpose: 'ร่มเงา/ประดับ',
  height_m: '8–12',
  traits: ['โตเร็ว'],
  reason: 'ใช้ตกแต่งภูมิทัศน์ในเมือง',
  verification: {
    gbif_url: 'https://www.gbif.org/species/2943416',
    bgci_is_tree: true,
    bgci_native_to_thailand: false,
    bgci_native_range: ['Madagascar'],
    wcvp_thailand: 'INTRODUCED',
    gbif_records_in_this_region: 0,
  },
};

const wrap = (species) => ({ region: 'อีสาน', species });

test('renders nothing without species', () => {
  const { container } = render(<SpeciesSection recommendedSpecies={wrap([])} />);
  expect(container).toBeEmptyDOMElement();
});

test('shows origin and a link back to the source record', () => {
  render(<SpeciesSection recommendedSpecies={wrap([NATIVE])} />);
  expect(screen.getByText(/ไม้ยืนต้นพื้นเมืองของไทย/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /ดูระเบียนต้นทาง/ }))
    .toHaveAttribute('href', NATIVE.verification.gbif_url);
});

test('names the native range for a non-native species', () => {
  render(<SpeciesSection recommendedSpecies={wrap([EXOTIC])} />);
  expect(screen.getByText(/ไม้ยืนต้นต่างถิ่น/)).toBeInTheDocument();
  expect(screen.getByText(/Madagascar/)).toBeInTheDocument();
});

// ศูนย์รายการต้องอ่านว่า "ยังไม่มีใครบันทึก" ไม่ใช่ "ไม่มีต้นไม้ชนิดนี้"
test('states that zero records means nothing was recorded yet', () => {
  render(<SpeciesSection recommendedSpecies={wrap([EXOTIC])} />);
  expect(screen.getByText(/ยังไม่มีบันทึกการพบพร้อมพิกัดในภาคนี้/)).toBeInTheDocument();
});

test('shows the record count when the species has been recorded', () => {
  render(<SpeciesSection recommendedSpecies={wrap([NATIVE])} />);
  expect(screen.getByText(/มีบันทึกการพบในภาคนี้ 404 รายการ/)).toBeInTheDocument();
});

// คำตอบจากแคชรุ่นเก่ายังไม่มี verification — ต้องไม่พัง และไม่แสดงบรรทัดที่มา
test('renders the card without a source line for older cached responses', () => {
  const legacy = { ...NATIVE, verification: undefined };
  render(<SpeciesSection recommendedSpecies={wrap([legacy])} />);
  expect(screen.getByText('ประดู่ป่า')).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: /ดูระเบียนต้นทาง/ })).toBeNull();
});
