import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts';
import { cssVar } from '../chartColors';
import type { Candle } from '@/lib/types';

export function PriceVolumeChart({ candles }: { candles: Candle[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const upFillRef = useRef('');
  const downFillRef = useRef('');

  // 마운트 시 차트/시리즈를 한 번만 만든다. candles 갱신은 아래 별도 effect가 setData로 처리한다.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const up = cssVar('--color-up', 'crimson');
    const down = cssVar('--color-down', 'royalblue');
    const divider = cssVar('--color-divider', 'lightgray');
    const axisText = cssVar('--color-neutral-700', 'gray');
    upFillRef.current = cssVar('--color-up-100', 'mistyrose');
    downFillRef.current = cssVar('--color-down-100', 'aliceblue');

    const chart = createChart(el, {
      width: el.clientWidth,
      height: 320,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: axisText,
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: divider } },
      rightPriceScale: { borderColor: divider },
      timeScale: { borderColor: divider },
    });

    const priceSeries = chart.addSeries(CandlestickSeries, {
      upColor: up,
      downColor: down,
      borderVisible: false,
      wickUpColor: up,
      wickDownColor: down,
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.75, bottom: 0 } });
    chart.priceScale('right').applyOptions({ scaleMargins: { top: 0.05, bottom: 0.3 } });

    chartRef.current = chart;
    priceSeriesRef.current = priceSeries;
    volumeSeriesRef.current = volumeSeries;

    // 너비만 바꾸면 기존 확대 배율이 그대로 남아 최근 구간만 보이고 왼쪽이 빈다. 리사이즈 때마다 다시 맞춘다.
    const handleResize = () => {
      chart.applyOptions({ width: el.clientWidth });
      chart.timeScale().fitContent();
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      priceSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, []);

  // candles가 바뀔 때는 차트를 다시 만들지 않고 데이터만 갱신함
  // 데이터 갱신 effect
  useEffect(() => {
    const priceSeries = priceSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    if (!priceSeries || !volumeSeries) return;

    const upFill = upFillRef.current;
    const downFill = downFillRef.current;

    priceSeries.setData(
      candles.map((c) => ({
        time: c.date,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );
    volumeSeries.setData(
      candles.map((c) => ({
        time: c.date,
        value: c.volume,
        color: c.close >= c.open ? upFill : downFill,
      })),
    );
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  return <div ref={containerRef} className="h-80 w-full" />;
}
