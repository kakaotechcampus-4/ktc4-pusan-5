import { Card, Empty, ErrorBox, InfoTip, Kicker, Skeleton, Tag } from '@/components/ui';
import { formatCompactKRW, formatFiscalPeriod, formatPrice } from '@/lib/format';
import type { StockFinancials } from '@/lib/types';
import { mergeAnnualRows } from '../financialUtils';

const METRICS = [
  { key: 'revenue', label: '매출액', format: formatCompactKRW },
  { key: 'operatingProfit', label: '영업이익', format: formatCompactKRW },
  { key: 'netIncome', label: '순이익', format: formatCompactKRW },
  { key: 'eps', label: 'EPS', format: (value: number) => `${formatPrice(value)}원` },
] as const;

function formatValue(value: number | null, format: (value: number) => string) {
  return value === null ? '—' : format(value);
}

export function AnnualFinancialTrend({
  financials,
  error,
  onRetry,
}: {
  financials: StockFinancials | null;
  error: Error | null;
  onRetry: () => void;
}) {
  const periods = mergeAnnualRows(financials?.income.data ?? null, financials?.eps.data ?? null);
  const resources = financials ? [financials.income, financials.eps] : [];
  const collecting =
    !error &&
    (!financials ||
      resources.some((resource) => resource.status === 'pending' || resource.refreshing));
  const failed = Boolean(error) || resources.some((resource) => resource.status === 'unavailable');
  const stale = resources.some((resource) => resource.status === 'stale');
  return (
    <Card tone="plain">
      <div className="flex items-center justify-between gap-2">
        <Kicker>재무 추이</Kicker>
        {periods.length > 0 && (failed || stale) && (
          <Tag>{failed ? '일부 조회 실패' : '이전 데이터'}</Tag>
        )}
      </div>
      {!periods.length ? (
        collecting ? (
          <div role="status" aria-label="재무 데이터 불러오는 중">
            <Skeleton className="h-40 w-full" />
          </div>
        ) : failed ? (
          <ErrorBox title="재무 추이를 불러오지 못했습니다" onRetry={onRetry} />
        ) : (
          <Empty title="재무 추이 데이터가 없습니다" description="다른 종목을 확인해보세요" />
        )
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th
                  scope="col"
                  className="border-divider bg-canvas sticky left-0 border-b px-2 py-2 text-left font-semibold whitespace-nowrap text-neutral-600"
                >
                  <span className="flex items-center gap-1">
                    지표
                    <InfoTip description="KIS 결산연월 기준입니다. 중간결산이 포함될 수 있어 기간을 확인해 비교해주세요." />
                  </span>
                </th>
                {periods.map((period) => (
                  <th
                    scope="col"
                    key={period.fiscalPeriod}
                    className="num border-divider border-b px-2 py-2 text-right font-semibold whitespace-nowrap text-neutral-600"
                  >
                    {formatFiscalPeriod(period.fiscalPeriod)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRICS.map((metric) => (
                <tr key={metric.key}>
                  <th
                    scope="row"
                    className="border-divider bg-canvas sticky left-0 border-b px-2 py-2 text-left font-normal whitespace-nowrap"
                  >
                    {metric.label}
                  </th>
                  {periods.map((period) => (
                    <td
                      key={period.fiscalPeriod}
                      className="num border-divider border-b px-2 py-2 text-right whitespace-nowrap"
                    >
                      {formatValue(period[metric.key], metric.format)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
