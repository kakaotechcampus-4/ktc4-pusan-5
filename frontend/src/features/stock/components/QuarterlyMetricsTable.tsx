import { Fragment, type ReactNode } from 'react';
import { Change, InfoTip, Skeleton, Tag } from '@/components/ui';
import {
  formatCompactKRW,
  formatFiscalPeriod,
  formatMarketDate,
  formatPrice,
  formatRatio,
} from '@/lib/format';
import type { Growth, InvestmentPoint, Resource } from '@/lib/types';

type Row = {
  label: ReactNode | ((point: InvestmentPoint) => ReactNode);
  render: (point: InvestmentPoint) => ReactNode;
};
type Group = { title: string; rows: Row[] };

function unavailable(label: string, description: string) {
  return (
    <span className="flex items-center gap-1">
      {label}
      <InfoTip description={description} />
    </span>
  );
}

function datedDescription(
  description: string,
  asOf: string | null,
  baseDate?: string | null,
): string {
  const dates = [
    asOf ? `기준일 ${formatMarketDate(asOf)}` : null,
    baseDate ? `기준 시작일 ${formatMarketDate(baseDate)}` : null,
  ].filter(Boolean);
  return dates.length ? `${description} · ${dates.join(' · ')}` : description;
}

function growthLabel(growth: Growth): ReactNode {
  if (growth.status === 'value' && growth.value !== null)
    return <Change value={growth.value} size="sm" />;
  const labels: Record<Growth['status'], string> = {
    value: '—',
    turned_profit: '흑자전환',
    turned_loss: '적자전환',
    loss_narrowed: '적자축소',
    loss_widened: '적자확대',
    loss_unchanged: '적자지속',
    zero_base: '—',
    unavailable: '—',
  };
  return <span>{labels[growth.status]}</span>;
}

const GROUPS: Group[] = [
  {
    title: '추세',
    rows: [
      {
        label: (point) =>
          unavailable(
            'RS (12개월)',
            datedDescription(
              '배당을 포함하지 않은 수정 주가수익률과 현재 소속 시장 지수수익률의 차이인 상대강도입니다.',
              point.rsAsOf,
              point.rsBaseDate,
            ),
          ),
        render: (point) =>
          point.rs === null ? (
            <span className="num">—</span>
          ) : (
            <Change value={point.rs} unit="percentp" size="sm" />
          ),
      },
      {
        label: (
          <>
            매출성장률{' '}
            <InfoTip description="단일 분기 실적의 전년 동기 대비입니다. 이전값 0 또는 자료 부족 시 —로 표시하며, 흑자·적자 전환은 별도 상태로 표시합니다." />
          </>
        ),
        render: (point) => growthLabel(point.revenueGrowth),
      },
      {
        label: (
          <>
            영업이익성장률{' '}
            <InfoTip description="단일 분기 실적의 전년 동기 대비입니다. 이전값 0 또는 자료 부족 시 —로 표시하며, 흑자·적자 전환은 별도 상태로 표시합니다." />
          </>
        ),
        render: (point) => growthLabel(point.operatingProfitGrowth),
      },
      {
        label: (
          <>
            순이익성장률{' '}
            <InfoTip description="단일 분기 실적의 전년 동기 대비입니다. 이전값 0 또는 자료 부족 시 —로 표시하며, 흑자·적자 전환은 별도 상태로 표시합니다." />
          </>
        ),
        render: (point) => growthLabel(point.netIncomeGrowth),
      },
      {
        label: (point) =>
          unavailable(
            '시가총액',
            datedDescription('과거 분기말 시가총액 데이터입니다.', point.marketCapAsOf),
          ),
        render: (point) =>
          point.marketCap === null ? (
            <span className="num">—</span>
          ) : (
            <span className="num">{formatCompactKRW(point.marketCap)}</span>
          ),
      },
    ],
  },
  {
    title: '위치 및 밸류에이션',
    rows: [
      {
        label: unavailable('PER', '과거 분기말 데이터가 연결되지 않아 표시하지 않습니다.'),
        render: () => <span className="num">—</span>,
      },
      {
        label: unavailable('PBR', '과거 분기말 데이터가 연결되지 않아 표시하지 않습니다.'),
        render: () => <span className="num">—</span>,
      },
      {
        label: 'ROE',
        render: (point) => (
          <span className="num">{point.roe === null ? '—' : formatRatio(point.roe)}</span>
        ),
      },
    ],
  },
  {
    title: '리스크 관리 및 안정성',
    rows: [
      {
        label: '부채비율',
        render: (point) => (
          <span className="num">
            {point.debtRatio === null ? '—' : formatRatio(point.debtRatio)}
          </span>
        ),
      },
      {
        label: '영업이익',
        render: (point) =>
          point.operatingProfit === null ? (
            '—'
          ) : (
            <span className="num">{formatCompactKRW(point.operatingProfit)}</span>
          ),
      },
      {
        label: '당기순이익',
        render: (point) =>
          point.netIncome === null ? (
            '—'
          ) : (
            <span className="num">{formatCompactKRW(point.netIncome)}</span>
          ),
      },
      {
        label: (
          <>
            누적 EPS{' '}
            <InfoTip description="해당 결산연월까지 누적된 EPS이며, 분기 EPS의 단순 차분값이 아닙니다." />
          </>
        ),
        render: (point) =>
          point.epsCumulative === null ? (
            '—'
          ) : (
            <span className="num">{formatPrice(point.epsCumulative)}원</span>
          ),
      },
    ],
  },
];

export function QuarterlyMetricsTable({
  investment,
  error,
}: {
  investment: Resource<InvestmentPoint[]> | null;
  error?: Error | null;
}) {
  if (!investment?.data && (error || investment?.status === 'unavailable'))
    return (
      <div className="flex items-center gap-2 text-sm text-neutral-600">
        <Tag>{error ? '조회 실패' : '미제공'}</Tag>
      </div>
    );
  if (!investment?.data) return <Skeleton className="h-48 w-full" />;
  const points = [...investment.data]
    .sort((a, b) => a.fiscalPeriod.localeCompare(b.fiscalPeriod))
    .slice(-8);
  const notice = error || investment.status === 'stale';
  return (
    <div className="flex flex-col gap-2">
      {notice && (
        <div>
          <Tag>{error ? '조회 실패' : '이전 데이터'}</Tag>
        </div>
      )}
      {points.length === 0 ? (
        <span className="text-sm text-neutral-600">—</span>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th className="border-divider bg-canvas sticky left-0 border-b px-2 py-2 text-left font-semibold whitespace-nowrap text-neutral-600">
                  지표
                </th>
                {points.map((point) => (
                  <th
                    key={point.fiscalPeriod}
                    className="num border-divider border-b px-2 py-2 text-right font-semibold whitespace-nowrap text-neutral-600"
                  >
                    {formatFiscalPeriod(point.fiscalPeriod)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {GROUPS.map((group) => (
                <Fragment key={group.title}>
                  <tr>
                    <td
                      colSpan={points.length + 1}
                      className="bg-surface text-kicker tracking-kicker px-2 py-1.5 font-semibold text-neutral-600 uppercase"
                    >
                      {group.title}
                    </td>
                  </tr>
                  {group.rows.map((row, index) => (
                    <tr key={`${group.title}-${index}`}>
                      <th className="border-divider bg-canvas sticky left-0 border-b px-2 py-2 text-left font-normal whitespace-nowrap">
                        <span className="flex items-center gap-1">
                          {typeof row.label === 'function'
                            ? row.label(points[points.length - 1])
                            : row.label}
                        </span>
                      </th>
                      {points.map((point) => (
                        <td
                          key={point.fiscalPeriod}
                          className="border-divider border-b px-2 py-2 text-right whitespace-nowrap"
                        >
                          {row.render(point)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
