import { Change, Skeleton } from '@/components/ui';
import { formatCompactKRW, formatMarketDate } from '@/lib/format';
import type { Resource, StockInvestorFlowData } from '@/lib/types';
import { NO_VALUE } from '../financialUtils';

/** 수량 아래에 붙는 보조 문구: 대금 · 기준일 */
function institutionDetail(flow: StockInvestorFlowData): string {
  return [
    flow.institutionNetValue === null ? null : formatCompactKRW(flow.institutionNetValue),
    `${formatMarketDate(flow.tradeDate)} 기준`,
  ]
    .filter(Boolean)
    .join(' · ');
}

/** 기관 순매수 수량을 등락 규칙(매수 빨강 / 매도 파랑)으로, 대금과 기준일을 보조 문구로 보여준다 */
export function InstitutionNetBuyValue({
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
  return (
    <span className="flex flex-col items-end">
      <span className="flex items-baseline gap-1">
        <Change value={flow.institutionNetQty} unit="price" />
        <span className="text-xs text-neutral-600">주</span>
      </span>
      <span className="num text-xs text-neutral-600">{institutionDetail(flow)}</span>
    </span>
  );
}
