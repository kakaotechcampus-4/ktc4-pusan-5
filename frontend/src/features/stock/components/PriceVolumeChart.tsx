import { useEffect, useRef } from 'react';
import { CandlestickSeries, ColorType, HistogramSeries, createChart } from 'lightweight-charts';
import type { Candle } from '../mock';

/**
 * lightweight-charts는 캔버스 렌더링이라 Tailwind 클래스를 못 받음
 * theme.css의 CSS 커스텀 프로퍼티를 사용
 */
function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function PriceVolumeChart({ candles }: { candles: Candle[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const up = cssVar('--color-up', 'crimson');
    const down = cssVar('--color-down', 'royalblue');
    const upFill = cssVar('--color-up-100', 'mistyrose');
    const downFill = cssVar('--color-down-100', 'aliceblue');
    const divider = cssVar('--color-divider', 'lightgray');
    const axisText = cssVar('--color-neutral-700', 'gray');

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
    priceSeries.setData(
      candles.map((c) => ({
        time: c.time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.75, bottom: 0 } });
    chart.priceScale('right').applyOptions({ scaleMargins: { top: 0.05, bottom: 0.3 } });
    volumeSeries.setData(
      candles.map((c) => ({
        time: c.time,
        value: c.volume,
        color: c.close >= c.open ? upFill : downFill,
      })),
    );

    chart.timeScale().fitContent();

    // 너비만 바꾸면 기존 확대 배율이 그대로 남아 최근 구간만 보이고 왼쪽이 빈다. 리사이즈 때마다 다시 맞춘다.
    const handleResize = () => {
      chart.applyOptions({ width: el.clientWidth });
      chart.timeScale().fitContent();
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [candles]);

  return <div ref={containerRef} className="h-80 w-full" />;
}
