import { InfoTip, Stat, StatGrid } from '@/components/ui';
import { formatRatio } from '@/lib/format';
import type { FinancialHealth, FinancialSummary } from '../mock';

/** 부채비율·ROE·영업이익률·유동비율 4개를 요약 카드로 보여준다. */
export function FinancialHealthSummary({
  health,
  financials,
}: {
  health: FinancialHealth;
  financials: FinancialSummary;
}) {
  const operatingMargin = (financials.operatingProfit / financials.revenue) * 100;

  return (
    <StatGrid>
      <Stat
        label={
          <>
            부채비율
            <InfoTip description="자기자본 대비 부채가 얼마나 되는지 보여주는 비율입니다. 낮을수록 재무구조가 안정적입니다." />
          </>
        }
        value={formatRatio(health.debtRatio)}
      />
      <Stat
        label={
          <>
            ROE
            <InfoTip description="자기자본으로 얼마나 이익을 냈는지 보여주는 자기자본이익률입니다." />
          </>
        }
        value={formatRatio(health.roe)}
      />
      <Stat
        label={
          <>
            영업이익률
            <InfoTip description="매출액 대비 영업이익이 차지하는 비율입니다." />
          </>
        }
        value={formatRatio(operatingMargin)}
      />
      <Stat
        label={
          <>
            유동비율
            <InfoTip description="1년 내 갚아야 할 부채를 유동자산으로 얼마나 감당할 수 있는지 보여주는 비율입니다. 100% 이상이면 안정적이라고 봅니다." />
          </>
        }
        value={formatRatio(health.currentRatio)}
      />
    </StatGrid>
  );
}
