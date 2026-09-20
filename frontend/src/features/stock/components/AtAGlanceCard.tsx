import { Card, Empty, InfoTip, Kicker, SkeletonText } from '@/components/ui';
import { formatCompactKRW, formatMultiple, formatPrice, formatRatio } from '@/lib/format';
import type { Resource, StockMetricsData, StockQuoteData } from '@/lib/types';

function renderValue(value: number | null, render: (number: number) => string) {
  return value === null ? '—' : render(value);
}

export function AtAGlanceCard({
  quote,
  metrics,
}: {
  quote: Resource<StockQuoteData> | null;
  metrics: Resource<StockMetricsData> | null;
}) {
  if (!quote && !metrics)
    return (
      <Card tone="plain">
        <Kicker>AT A GLANCE · 주요 지표</Kicker>
        <SkeletonText lines={8} />
      </Card>
    );
  const q = quote?.data;
  const m = metrics?.data;
  const rows = [
    ['시가총액', q?.marketCap === null || !q ? '—' : formatCompactKRW(q.marketCap)],
    ['거래량', q ? `${formatPrice(q.volume)}주` : '—'],
    [
      '거래대금',
      q ? formatCompactKRW(q.tradingValue) : '—',
      '그날 거래된 주식 수에 가격을 곱한 총 금액입니다.',
    ],
    [
      '외국인 보유',
      renderValue(m?.foreignOwnership ?? null, formatRatio),
      '전체 발행주식 중 외국인 투자자가 보유한 비율입니다.',
    ],
    [
      'PER',
      renderValue(m?.per ?? null, formatMultiple),
      '주가를 주당순이익(EPS)으로 나눈 값입니다.',
    ],
    [
      'PBR',
      renderValue(m?.pbr ?? null, formatMultiple),
      '주가를 주당순자산(BPS)으로 나눈 값입니다.',
    ],
    ['EPS', renderValue(m?.eps ?? null, (v) => `${formatPrice(v)}원`)],
    ['BPS', renderValue(m?.bps ?? null, (v) => `${formatPrice(v)}원`)],
    ['52주 최고', renderValue(m?.week52High ?? null, (v) => `${formatPrice(v)}원`)],
    ['52주 최저', renderValue(m?.week52Low ?? null, (v) => `${formatPrice(v)}원`)],
  ];
  const unavailable = [quote?.status, metrics?.status].some(
    (status) => status === 'unavailable' || status === 'empty',
  );
  return (
    <Card tone="plain" className="flex-1">
      <Kicker>AT A GLANCE · 주요 지표</Kicker>
      {quote?.status === 'unavailable' && (
        <p className="mb-2 text-sm text-neutral-600">현재 시세를 준비하지 못했습니다</p>
      )}
      {metrics?.status === 'stale' && (
        <p role="status" className="mb-2 text-sm text-neutral-600">
          주요 지표 갱신 지연 · 마지막 정상값입니다.
        </p>
      )}
      {metrics?.status === 'unavailable' && (
        <p className="mb-2 text-sm text-neutral-600">주요 지표를 준비하지 못했습니다</p>
      )}
      {unavailable && !q && !m ? (
        <Empty title="주요 지표를 준비하지 못했습니다" description="잠시 후 다시 확인해주세요" />
      ) : (
        <dl className="flex flex-1 flex-col justify-center">
          {rows.map(([label, rendered, description]) => (
            <div
              key={label}
              className="border-divider flex items-center justify-between border-b py-2 last:border-b-0"
            >
              <dt className="flex items-center gap-1 text-sm text-neutral-600">
                {label}
                {description && <InfoTip description={description} />}
              </dt>
              <dd className="num text-sm font-semibold">{rendered}</dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
}
