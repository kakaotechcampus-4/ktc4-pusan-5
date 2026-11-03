import type { ReactNode } from 'react';
import { Change, InfoTip, Skeleton, SkeletonText, StatList, StatListItem } from '@/components/ui';
import { formatCompactKRW, formatMarketDate, formatPrice, formatRatio } from '@/lib/format';
import type {
  Resource,
  StockInvestorFlowData,
  StockMetricsData,
  StockQuoteData,
} from '@/lib/types';
import { NO_VALUE } from '../financialUtils';

function renderValue(value: number | null | undefined, render: (value: number) => string) {
  return value === null || value === undefined ? NO_VALUE : render(value);
}

function num(value: ReactNode) {
  return <span className="num text-sm font-semibold">{value}</span>;
}

/** 기관 순매수 수량을 등락 규칙(매수 빨강 / 매도 파랑)으로, 대금과 기준일을 보조 문구로 보여준다 */
function InstitutionNetBuyValue({
  investorFlow,
}: {
  investorFlow: Resource<StockInvestorFlowData> | null | undefined;
}) {
  const flow = investorFlow?.data;
  if (!flow) {
    // 수집 중이면 자리를 잡아두고, 미제공·빈 값·서버가 필드를 주지 않는 경우는 미제공으로 둔다
    if (investorFlow?.status === 'pending') return <Skeleton className="h-4 w-24" />;
    return NO_VALUE;
  }
  const detail = [
    flow.institutionNetValue === null ? null : formatCompactKRW(flow.institutionNetValue),
    `${formatMarketDate(flow.tradeDate)} 기준`,
    investorFlow?.status === 'stale' ? '갱신 지연' : null,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <span className="flex flex-col items-end">
      <span className="flex items-baseline gap-1">
        <Change value={flow.institutionNetQty} unit="price" />
        <span className="text-xs text-neutral-600">주</span>
      </span>
      <span className="num text-xs text-neutral-600">{detail}</span>
    </span>
  );
}

export function MarketActivitySummary({
  quote,
  metrics,
  investorFlow,
}: {
  quote: Resource<StockQuoteData> | null;
  metrics: Resource<StockMetricsData> | null;
  investorFlow?: Resource<StockInvestorFlowData> | null;
}) {
  if (!quote && !metrics) return <SkeletonText lines={5} />;
  const q = quote?.data;
  const m = metrics?.data;
  return (
    <StatList>
      <StatListItem label="시가총액" value={num(renderValue(q?.marketCap, formatCompactKRW))} />
      <StatListItem
        label={
          <>
            거래량{' '}
            <InfoTip description="전일 대비 거래량 변화율입니다. 장중에는 오늘 거래량이 쌓이는 중이라 낮게 보일 수 있고, 전일 거래량이 없으면 표시하지 않습니다." />
          </>
        }
        value={
          <span className="flex items-baseline gap-2">
            {num(q ? `${formatPrice(q.volume)}주` : NO_VALUE)}
            {typeof q?.volumeChange === 'number' && <Change value={q.volumeChange} />}
          </span>
        }
      />
      <StatListItem label="거래대금" value={num(q ? formatCompactKRW(q.tradingValue) : NO_VALUE)} />
      <StatListItem
        label="외국인 보유"
        value={num(renderValue(m?.foreignOwnership ?? null, formatRatio))}
      />
      <StatListItem
        label={
          <>
            기관 순매수{' '}
            <InfoTip description="기관 투자자의 최근 거래일 순매수 수량입니다. 음수는 순매도이며, 장중 값은 달라질 수 있습니다." />
          </>
        }
        value={<InstitutionNetBuyValue investorFlow={investorFlow} />}
      />
    </StatList>
  );
}
