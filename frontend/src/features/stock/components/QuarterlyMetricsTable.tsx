import { Fragment, type ReactNode } from 'react';
import { Change, InfoTip } from '@/components/ui';
import { formatCompactKRW, formatMultiple, formatPrice, formatRatio } from '@/lib/format';
import type { QuarterlyMetric } from '../mock';

type Row = {
  label: ReactNode;
  render: (m: QuarterlyMetric) => ReactNode;
};

type Group = {
  title: string;
  rows: Row[];
};

const GROUPS: Group[] = [
  {
    title: '추세',
    rows: [
      {
        label: (
          <>
            RS
            <InfoTip description="최근 가격 움직임이 시장 전체 대비 얼마나 강한지 보여주는 상대강도 점수(0~100)입니다." />
          </>
        ),
        render: (m) => <span className="num">{m.rs}</span>,
      },
      { label: '매출성장률', render: (m) => <Change value={m.revenueGrowth} size="sm" /> },
      {
        label: '영업이익성장률',
        render: (m) => <Change value={m.operatingProfitGrowth} size="sm" />,
      },
      { label: '순이익성장률', render: (m) => <Change value={m.netIncomeGrowth} size="sm" /> },
      {
        label: '시가총액',
        render: (m) => <span className="num">{formatCompactKRW(m.marketCap)}</span>,
      },
    ],
  },
  {
    title: '위치 및 밸류에이션',
    rows: [
      { label: 'PER', render: (m) => <span className="num">{formatMultiple(m.per)}</span> },
      { label: 'PBR', render: (m) => <span className="num">{formatMultiple(m.pbr)}</span> },
      { label: 'ROE', render: (m) => <span className="num">{formatRatio(m.roe)}</span> },
    ],
  },
  {
    title: '리스크 관리 및 안정성',
    rows: [
      { label: '부채비율', render: (m) => <span className="num">{formatRatio(m.debtRatio)}</span> },
      {
        label: '영업이익',
        render: (m) => <span className="num">{formatCompactKRW(m.operatingProfit)}</span>,
      },
      {
        label: '당기순이익',
        render: (m) => <span className="num">{formatCompactKRW(m.netIncome)}</span>,
      },
      { label: 'EPS', render: (m) => <span className="num">{formatPrice(m.eps)}원</span> },
    ],
  },
];

/** 분기별 투자 지표. 컬럼(분기)이 많아 좁은 화면에서는 가로 스크롤로 본다. */
export function QuarterlyMetricsTable({ metrics }: { metrics: QuarterlyMetric[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            <th className="border-divider bg-canvas sticky left-0 border-b px-2 py-2 text-left font-semibold whitespace-nowrap text-neutral-600">
              지표
            </th>
            {metrics.map((m) => (
              <th
                key={m.quarter}
                className="num border-divider border-b px-2 py-2 text-right font-semibold whitespace-nowrap text-neutral-600"
              >
                {m.quarter}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {GROUPS.map((group) => (
            <Fragment key={group.title}>
              <tr>
                <td
                  colSpan={metrics.length + 1}
                  className="bg-surface text-kicker tracking-kicker px-2 py-1.5 font-semibold text-neutral-600 uppercase"
                >
                  {group.title}
                </td>
              </tr>
              {group.rows.map((row, i) => (
                <tr key={i}>
                  <td className="border-divider bg-canvas sticky left-0 border-b px-2 py-2 whitespace-nowrap">
                    <span className="flex items-center gap-1">{row.label}</span>
                  </td>
                  {metrics.map((m) => (
                    <td
                      key={m.quarter}
                      className="border-divider border-b px-2 py-2 text-right whitespace-nowrap"
                    >
                      {row.render(m)}
                    </td>
                  ))}
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
