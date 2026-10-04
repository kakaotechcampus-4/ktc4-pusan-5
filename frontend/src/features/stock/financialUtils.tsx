import type { ReactNode } from 'react';
import { Change } from '@/components/ui';
import type { FinancialEpsPoint, FinancialIncomePoint, Growth } from '@/lib/types';

/** 정상 조회됐지만 값 자체가 없을 때 쓰는 문구. "null"처럼 개발자 용어를 그대로 보여주지 않고
 * 일반 사용자도 알 수 있는 말(미제공)로 알려준다. 로딩/에러 상태와는 다르다. */
export const NO_VALUE: ReactNode = <span className="text-neutral-400">미제공</span>;

/** 52주 최고가 대비 현재 주가 위치(%). -12.5 → 최고가보다 12.5% 낮은 위치 */
export function distanceFromWeek52High(price: number, week52High: number): number {
  return ((price - week52High) / week52High) * 100;
}

/** 52주 최저가 대비 현재 주가 위치(%). +45.2 → 최저가보다 45.2% 높은 위치 */
export function distanceFromWeek52Low(price: number, week52Low: number): number {
  return ((price - week52Low) / week52Low) * 100;
}

const GROWTH_STATUS_LABEL: Record<Exclude<Growth['status'], 'value'>, ReactNode> = {
  turned_profit: '흑자전환',
  turned_loss: '적자전환',
  loss_narrowed: '적자축소',
  loss_widened: '적자확대',
  loss_unchanged: '적자지속',
  zero_base: NO_VALUE,
  unavailable: NO_VALUE,
};

/** 성장률(YoY) 값. 흑자·적자 전환 같은 특수 상태는 부호 대신 상태 라벨로 표시한다. */
export function growthLabel(growth: Growth) {
  if (growth.status === 'value' && growth.value !== null)
    return <Change value={growth.value} size="sm" />;
  if (growth.status === 'value')
    return <span className="num text-sm font-semibold">{NO_VALUE}</span>;
  return <span className="text-sm font-semibold">{GROWTH_STATUS_LABEL[growth.status]}</span>;
}

export type AnnualRow = {
  fiscalPeriod: string;
  revenue: number | null;
  operatingProfit: number | null;
  netIncome: number | null;
  eps: number | null;
};

export function mergeAnnualRows(
  income: FinancialIncomePoint[] | null,
  eps: FinancialEpsPoint[] | null,
): AnnualRow[] {
  const byPeriod = new Map<string, AnnualRow>();
  income?.forEach((point) => byPeriod.set(point.fiscalPeriod, { ...point, eps: null }));
  eps?.forEach((point) => {
    const row = byPeriod.get(point.fiscalPeriod) ?? {
      fiscalPeriod: point.fiscalPeriod,
      revenue: null,
      operatingProfit: null,
      netIncome: null,
      eps: null,
    };
    row.eps = point.eps;
    byPeriod.set(point.fiscalPeriod, row);
  });
  return [...byPeriod.values()]
    .sort((a, b) => a.fiscalPeriod.localeCompare(b.fiscalPeriod))
    .slice(-5);
}
