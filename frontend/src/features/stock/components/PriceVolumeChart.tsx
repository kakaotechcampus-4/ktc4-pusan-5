import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
} from 'lightweight-charts';
import { cssVar } from '../chartColors';
import type { Candle } from '@/lib/types';

export function PriceVolumeChart({
  candles,
  onLoadEarlier,
  canLoadEarlier,
}: {
  candles: Candle[];
  onLoadEarlier: () => void;
  canLoadEarlier: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const previousCandlesRef = useRef<Candle[]>([]);
  const interactedRef = useRef(false);
  const updatingRef = useRef(false);
  const loadEarlierRef = useRef(onLoadEarlier);
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
      handleScale: false,
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      kineticScroll: { mouse: false, touch: false },
      timeScale: {
        borderColor: divider,
        fixRightEdge: true,
        lockVisibleTimeRangeOnResize: true,
        shiftVisibleRangeOnNewBar: false,
      },
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

    const onRangeChange = (range: LogicalRange | null) => {
      if (!updatingRef.current && interactedRef.current && range && range.from < 8) {
        loadEarlierRef.current();
      }
    };
    const onInteraction = () => {
      interactedRef.current = true;
    };
    el.addEventListener('pointerdown', onInteraction);
    el.addEventListener('wheel', onInteraction, { passive: true });
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange);
    const observer = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    observer.observe(el);
    return () => {
      observer.disconnect();
      el.removeEventListener('pointerdown', onInteraction);
      el.removeEventListener('wheel', onInteraction);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange);
      previousCandlesRef.current = [];
      interactedRef.current = false;
      chart.remove();
      chartRef.current = null;
      priceSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.timeScale().applyOptions({ fixLeftEdge: !canLoadEarlier });
  }, [canLoadEarlier]);

  // candles가 바뀔 때는 차트를 다시 만들지 않고 데이터만 갱신함
  // 데이터 갱신 effect
  useEffect(() => {
    const priceSeries = priceSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    if (!priceSeries || !volumeSeries) return;

    const timeScale = chartRef.current!.timeScale();
    const range = timeScale.getVisibleLogicalRange();
    const previous = previousCandlesRef.current;
    const offset = previous.length ? candles.findIndex((c) => c.date === previous[0].date) : -1;
    updatingRef.current = true;
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
    if (interactedRef.current && range && offset >= 0) {
      // Prepending candles changes logical indices, but must not move the visible dates.
      timeScale.setVisibleLogicalRange({ from: range.from + offset, to: range.to + offset });
    } else {
      timeScale.fitContent();
    }
    previousCandlesRef.current = candles;
    updatingRef.current = false;
  }, [candles]);

  useEffect(() => {
    loadEarlierRef.current = onLoadEarlier;
    const range = chartRef.current?.timeScale().getVisibleLogicalRange();
    if (interactedRef.current && range && range.from < 8) onLoadEarlier();
  }, [onLoadEarlier]);

  return <div ref={containerRef} className="h-80 w-full" />;
}
