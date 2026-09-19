import { useMemo, useState } from 'react';
import { Card, Kicker, Tabs } from '@/components/ui';
import { PERIOD_DAYS, type Candle, type PricePeriod } from '../mock';
import { PriceVolumeChart } from './PriceVolumeChart';

const TABS: { value: PricePeriod; label: string }[] = [
  { value: '1M', label: '1개월' },
  { value: '3M', label: '3개월' },
  { value: '1Y', label: '1년' },
  { value: '5Y', label: '5년' },
  { value: 'ALL', label: '전체' },
];

export function PriceActionSection({ history }: { history: Candle[] }) {
  const [period, setPeriod] = useState<PricePeriod>('1Y');
  const candles = useMemo(
    () => history.slice(-PERIOD_DAYS[period]),
    [history, period],
  );

  return (
    <Card tone="plain" className="flex-1">
      <Kicker>PRICE ACTION · 주가와 거래량</Kicker>
      <Tabs tabs={TABS} value={period} onChange={setPeriod} />
      <PriceVolumeChart candles={candles} />
    </Card>
  );
}
