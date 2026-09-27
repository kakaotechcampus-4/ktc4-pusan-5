import { fireEvent, render } from '@testing-library/react';
import { PriceVolumeChart } from './PriceVolumeChart';
import type { Candle } from '@/lib/types';

const chart = vi.hoisted(() => {
  const scale = {
    fitContent: vi.fn(),
    getVisibleLogicalRange: vi.fn(() => ({ from: 0, to: 2 })),
    setVisibleLogicalRange: vi.fn(),
    applyOptions: vi.fn(),
    subscribeVisibleLogicalRangeChange: vi.fn(),
    unsubscribeVisibleLogicalRangeChange: vi.fn(),
  };
  return {
    scale,
    create: vi.fn(),
    api: {
      timeScale: () => scale,
      addSeries: () => ({ setData: vi.fn() }),
      priceScale: () => ({ applyOptions: vi.fn() }),
      applyOptions: vi.fn(),
      remove: vi.fn(),
    },
  };
});
vi.mock('lightweight-charts', () => ({
  createChart: chart.create,
  CandlestickSeries: {},
  HistogramSeries: {},
  ColorType: { Solid: 'solid' },
}));
const candle = (date: string): Candle => ({ date, open: 1, high: 2, low: 1, close: 2, volume: 10 });

beforeEach(() => {
  vi.clearAllMocks();
  chart.create.mockReturnValue(chart.api);
  chart.scale.getVisibleLogicalRange.mockReturnValue({ from: 0, to: 2 });
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(() => vi.unstubAllGlobals());

it('disables zoom and requests older data only after navigation', () => {
  const onLoadEarlier = vi.fn();
  const { container } = render(
    <PriceVolumeChart
      candles={[candle('2026-09-01')]}
      onLoadEarlier={onLoadEarlier}
      canLoadEarlier
    />,
  );
  expect(chart.create.mock.calls[0][1].handleScale).toBe(false);
  const onRange = chart.scale.subscribeVisibleLogicalRangeChange.mock.calls[0][0];
  onRange({ from: 0, to: 2 });
  expect(onLoadEarlier).not.toHaveBeenCalled();
  fireEvent.pointerDown(container.firstChild!);
  onRange({ from: -1, to: 1 });
  expect(onLoadEarlier).toHaveBeenCalledOnce();
});

it('preserves visible dates and width when older candles are prepended or refreshed', () => {
  const onLoadEarlier = vi.fn();
  const candles = [candle('2026-09-02'), candle('2026-09-03')];
  const { container, rerender } = render(
    <PriceVolumeChart candles={candles} onLoadEarlier={onLoadEarlier} canLoadEarlier />,
  );
  fireEvent.pointerDown(container.firstChild!);
  const expanded = [candle('2026-09-01'), ...candles];
  rerender(<PriceVolumeChart candles={expanded} onLoadEarlier={onLoadEarlier} canLoadEarlier />);
  expect(chart.scale.setVisibleLogicalRange).toHaveBeenLastCalledWith({ from: 1, to: 3 });
  expect(chart.scale.fitContent).toHaveBeenCalledOnce();
  chart.scale.getVisibleLogicalRange.mockReturnValue({ from: 1, to: 3 });
  rerender(
    <PriceVolumeChart
      candles={[...expanded]}
      onLoadEarlier={onLoadEarlier}
      canLoadEarlier={false}
    />,
  );
  expect(chart.scale.setVisibleLogicalRange).toHaveBeenLastCalledWith({ from: 1, to: 3 });
  expect(chart.scale.applyOptions).toHaveBeenLastCalledWith({ fixLeftEdge: true });
});
