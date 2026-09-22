import { ErrorBox, InfoTip, Skeleton, Stat, StatGrid, Tag } from '@/components/ui';
import { formatFiscalPeriod, formatRatio } from '@/lib/format';
import type { FinancialHealthData, Resource } from '@/lib/types';

function display(value: number | null): string {
  return value === null ? '—' : formatRatio(value);
}

function StatSkeleton() {
  return (
    <StatGrid>
      {[1, 2, 3, 4].map((key) => (
        <Skeleton key={key} className="h-16" />
      ))}
    </StatGrid>
  );
}

export function FinancialHealthSummary({
  health,
  error,
  onRetry,
}: {
  health: Resource<FinancialHealthData> | null;
  error?: Error | null;
  onRetry?: () => void;
}) {
  if (error && !health?.data)
    return <ErrorBox title="재무 건전성을 불러오지 못했습니다" onRetry={onRetry} />;
  if (!health) return <StatSkeleton />;
  const data = health.data;
  const collecting = !data && (health.status === 'pending' || health.refreshing);
  const unavailable = !data && (health.status === 'empty' || health.status === 'unavailable');
  if (collecting) return <StatSkeleton />;
  const periodHelp = data
    ? `기준 결산연월 ${formatFiscalPeriod(data.fiscalPeriod)}`
    : '결산연월 기준';
  const hasNotice = unavailable || health.status === 'stale' || Boolean(error && data);
  return (
    <div className="flex flex-col gap-2">
      {hasNotice && (
        <div className="flex items-center gap-2 text-sm text-neutral-600">
          {unavailable && <Tag>미제공</Tag>}
          {health.status === 'stale' && <Tag>이전 데이터</Tag>}
          {error && data && <Tag>조회 실패</Tag>}
        </div>
      )}
      <StatGrid>
        <Stat
          label={
            <>
              부채비율 <InfoTip description={`자기자본 대비 부채 비율입니다. ${periodHelp}`} />
            </>
          }
          value={display(data?.debtRatio ?? null)}
        />
        <Stat
          label={
            <>
              ROE <InfoTip description={`자기자본이익률입니다. ${periodHelp}`} />
            </>
          }
          value={display(data?.roe ?? null)}
        />
        <Stat
          label={
            <>
              영업이익률 <InfoTip description={`매출액 대비 영업이익 비율입니다. ${periodHelp}`} />
            </>
          }
          value={display(data?.operatingMargin ?? null)}
        />
        <Stat
          label={
            <>
              유동비율 <InfoTip description={`유동부채 대비 유동자산 비율입니다. ${periodHelp}`} />
            </>
          }
          value={display(data?.currentRatio ?? null)}
        />
      </StatGrid>
    </div>
  );
}
