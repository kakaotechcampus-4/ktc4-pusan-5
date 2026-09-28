import { ErrorBox, InfoTip, SkeletonText, StatList, StatListItem, Tag } from '@/components/ui';
import { formatFiscalPeriod, formatRatio } from '@/lib/format';
import type { FinancialHealthData, Resource } from '@/lib/types';

function display(value: number | null): string {
  return value === null ? '—' : formatRatio(value);
}

function num(value: string) {
  return <span className="num text-sm font-semibold">{value}</span>;
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
  if (!health) return <SkeletonText lines={4} />;
  const data = health.data;
  const collecting = !data && (health.status === 'pending' || health.refreshing);
  const unavailable = !data && (health.status === 'empty' || health.status === 'unavailable');
  if (collecting) return <SkeletonText lines={4} />;
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
      <StatList>
        <StatListItem
          label={
            <>
              부채비율 <InfoTip description={`자기자본 대비 부채 비율입니다. ${periodHelp}`} />
            </>
          }
          value={num(display(data?.debtRatio ?? null))}
        />
        <StatListItem
          label={
            <>
              ROE <InfoTip description={`자기자본이익률입니다. ${periodHelp}`} />
            </>
          }
          value={num(display(data?.roe ?? null))}
        />
        <StatListItem
          label={
            <>
              영업이익률 <InfoTip description={`매출액 대비 영업이익 비율입니다. ${periodHelp}`} />
            </>
          }
          value={num(display(data?.operatingMargin ?? null))}
        />
        <StatListItem
          label={
            <>
              유동비율 <InfoTip description={`유동부채 대비 유동자산 비율입니다. ${periodHelp}`} />
            </>
          }
          value={num(display(data?.currentRatio ?? null))}
        />
      </StatList>
    </div>
  );
}
