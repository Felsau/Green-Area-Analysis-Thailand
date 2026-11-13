export const getNdviColor = (value) => {
  if (value == null) return '#bbf7d0';
  if (value >= 0.6) return '#22c55e';
  if (value >= 0.45) return '#4ade80';
  if (value >= 0.3) return '#86efac';
  return '#bbf7d0';
};

export const getNdviLabel = (value) => {
  if (value == null) return '—';
  if (value >= 0.6) return 'พืชพรรณหนาแน่น';
  if (value >= 0.45) return 'พืชพรรณค่อนข้างมาก';
  if (value >= 0.3) return 'พืชพรรณปานกลาง';
  return 'พืชพรรณน้อย';
};

export const getLstColor = (value) => {
  if (value == null) return '#dadce0';
  if (value < 28) return '#60a5fa';
  if (value < 33) return '#fbbf24';
  if (value < 38) return '#f97316';
  return '#ef4444';
};

export const getLstLabel = (value) => {
  if (value == null) return '—';
  if (value < 28) return 'เย็น';
  if (value < 33) return 'ปานกลาง';
  if (value < 38) return 'ร้อน';
  return 'ร้อนมาก';
};

export const getNdviRgba = (value, alpha = 200) => {
  if (value == null) return [200, 230, 200, 120];
  if (value >= 0.6) return [34, 197, 94, alpha];
  if (value >= 0.45) return [74, 222, 128, alpha];
  if (value >= 0.3) return [134, 239, 172, alpha];
  return [187, 247, 208, alpha];
};

// เกณฑ์เดียวกับ getLstColor — ใช้กับ choropleth ตอน time-lapse LST
export const getLstRgba = (value, alpha = 200) => {
  if (value == null) return [218, 220, 224, 120];
  if (value < 28) return [96, 165, 250, alpha];
  if (value < 33) return [251, 191, 36, alpha];
  if (value < 38) return [249, 115, 22, alpha];
  return [239, 68, 68, alpha];
};
