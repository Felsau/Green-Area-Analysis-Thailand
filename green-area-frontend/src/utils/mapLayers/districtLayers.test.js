import { vi, expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';
import MapTooltip from '../../components/MapTooltip';
import { districtLayers } from './districtLayers';

vi.mock('@deck.gl/layers', () => ({ GeoJsonLayer: class { constructor(props) { this.props = props; this.id = props.id; } } }));
const feature = { type: 'Feature', properties: { province: 'Bangkok Metropolis', name: 'BangRak', name_th: 'เขตบางรัก' },
  geometry: { type: 'Polygon', coordinates: [[[100.5,13.7],[100.51,13.7],[100.51,13.71],[100.5,13.71],[100.5,13.7]]] } };
function context(extra = {}) {
  return { showingDistricts: true, districtFeatures: [feature], districtCache: {}, selectedProvinceEN: 'Bangkok Metropolis', selectedDistrictEN: 'BangRak', selectedYear: 2024,
    setSelectedDistrict: vi.fn(), setSelectedDistrictEN: vi.fn(), setDistrictArea: vi.fn(), setSidebarTab: vi.fn(), fetchDistrictNDVI: vi.fn(), setTooltip: vi.fn(), ...extra };
}

test.each([6,12,18])('no persistent district label layer at zoom %s', zoom => {
  const before = JSON.stringify(feature);
  const layers = districtLayers(context({ zoom }));
  expect(layers.map(layer => layer.id)).toEqual(['thailand-districts']);
  expect(layers[0].props.data.features).toEqual([feature]);
  expect(JSON.stringify(feature)).toBe(before);
});

test('hover shows the original area names and does not invent NDVI', () => {
  const ctx = context(); const layer = districtLayers(ctx)[0].props;
  layer.onHover({ object: feature, x: 120, y: 160 });
  const tooltip = ctx.setTooltip.mock.calls[0][0];
  render(<MapTooltip tooltip={tooltip} />);
  expect(screen.getByRole('tooltip')).toHaveTextContent('เขตบางรัก');
  expect(screen.getByRole('tooltip')).toHaveTextContent('Bangkok Metropolis › BangRak');
  expect(screen.queryByText(/NDVI/)).not.toBeInTheDocument();
  layer.onHover({ object: null }); expect(ctx.setTooltip).toHaveBeenLastCalledWith(null);
});

test('click/tap selection retains original names, area and analysis scope', () => {
  const ctx = context(); const layer = districtLayers(ctx)[0].props;
  layer.onClick({ object: feature });
  expect(ctx.setSelectedDistrict).toHaveBeenCalledWith('เขตบางรัก');
  expect(ctx.setSelectedDistrictEN).toHaveBeenCalledWith('BangRak');
  expect(Number(ctx.setDistrictArea.mock.calls[0][0])).toBeGreaterThan(0);
  expect(ctx.setSidebarTab).toHaveBeenCalledWith('stats');
  expect(ctx.fetchDistrictNDVI).toHaveBeenCalledWith('Bangkok Metropolis','BangRak',2024);
  layer.onClick({ object: null }); expect(ctx.fetchDistrictNDVI).toHaveBeenCalledTimes(1);
});

test('selected area border remains distinct and drawing disables picking', () => {
  const layer = districtLayers(context())[0].props;
  const other = { ...feature, properties: { ...feature.properties, name: 'Other' } };
  expect(layer.getLineWidth(feature)).toBeGreaterThan(layer.getLineWidth(other));
  expect(layer.getLineColor(feature)).toEqual([26,115,232,255]);
  expect(districtLayers(context({ drawActive: true }))[0].props.pickable).toBe(false);
  expect(districtLayers(context({ showingDistricts: false }))).toEqual([]);
});
