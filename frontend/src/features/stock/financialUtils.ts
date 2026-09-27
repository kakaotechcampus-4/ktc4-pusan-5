import type { FinancialEpsPoint, FinancialIncomePoint } from '@/lib/types';

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
