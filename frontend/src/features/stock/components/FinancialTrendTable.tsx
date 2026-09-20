import type { ReactNode } from 'react';
import { formatCompactKRW, formatPrice } from '@/lib/format';
import type { FinancialTrendPoint } from '../mock';

type Row = {
  label: string;
  render: (p: FinancialTrendPoint) => ReactNode;
};

const ROWS: Row[] = [
  {
    label: '매출액',
    render: (p) => <span className="num">{formatCompactKRW(p.revenue)}</span>,
  },
  {
    label: '영업이익',
    render: (p) => <span className="num">{formatCompactKRW(p.operatingProfit)}</span>,
  },
  {
    label: 'EPS',
    render: (p) => <span className="num">{formatPrice(p.eps)}원</span>,
  },
];

/** 5년치 매출액·영업이익·EPS를 표로 보여준다. (투자 지표 표와 같은 "지표=행, 기간=열" 패턴) */
export function FinancialTrendTable({ trend }: { trend: FinancialTrendPoint[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            <th className="border-divider bg-canvas sticky left-0 border-b px-2 py-2 text-left font-semibold whitespace-nowrap text-neutral-600">
              지표
            </th>
            {trend.map((p) => (
              <th
                key={p.year}
                className="num border-divider border-b px-2 py-2 text-right font-semibold whitespace-nowrap text-neutral-600"
              >
                {p.year}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => (
            <tr key={row.label}>
              <td className="border-divider bg-canvas sticky left-0 border-b px-2 py-2 whitespace-nowrap">
                {row.label}
              </td>
              {trend.map((p) => (
                <td
                  key={p.year}
                  className="border-divider border-b px-2 py-2 text-right whitespace-nowrap"
                >
                  {row.render(p)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
