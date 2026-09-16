import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, Change, ErrorBox, Kicker, Skeleton, StockAvatar, Tabs } from '@/components/ui';
import { SectionHead, SplitLayout } from '@/components/layout/PageShell';
import type { FlowItem, SectorRank } from '../mock';

export type MarketFlowStatus = 'loading' | 'error' | 'success';

type FlowTab = 'buy' | 'sell';

const TABS: { value: FlowTab; label: string }[] = [
  { value: 'buy', label: '매수' },
  { value: 'sell', label: '매도' },
];

export function MarketFlowSection({
  status,
  flow,
  sectors,
  onRetry,
}: {
  status: MarketFlowStatus;
  flow: { buy: FlowItem[]; sell: FlowItem[] };
  sectors: SectorRank[];
  onRetry: () => void;
}) {
  return (
    <section>
      <SectionHead title="외국인 및 기관 동향 및 섹터" />

      {status === 'error' && (
        <ErrorBox
          title="수급 정보를 불러오지 못했습니다"
          description="잠시 후 다시 시도해주세요"
          onRetry={onRetry}
        />
      )}

      {status !== 'error' && (
        <SplitLayout
          main={<InstitutionalFlowCard loading={status === 'loading'} flow={flow} />}
          side={<SectorRankCard loading={status === 'loading'} sectors={sectors} />}
        />
      )}
    </section>
  );
}

function InstitutionalFlowCard({
  loading,
  flow,
}: {
  loading: boolean;
  flow: { buy: FlowItem[]; sell: FlowItem[] };
}) {
  const [tab, setTab] = useState<FlowTab>('buy');
  const items = flow[tab];

  return (
    <Card>
      <Kicker>외국인 및 기관 매매 동향</Kicker>
      <Tabs tabs={TABS} value={tab} onChange={setTab} />

      {loading ? (
        <FlowSkeleton />
      ) : (
        <ol className="flex list-none flex-col">
          {items.map((item, i) => (
            <li key={item.code}>
              <Link
                to={`/stock/${item.code}`}
                className="border-divider text-ink flex items-center gap-3 border-b py-2 no-underline hover:bg-neutral-100"
              >
                <span className="num w-5 flex-none text-xs font-semibold text-neutral-500">
                  {i + 1}
                </span>
                <StockAvatar initial={item.initial} size="sm" />
                <span className="min-w-0 flex-1 truncate text-sm font-semibold">{item.name}</span>
                <span className="flex items-baseline gap-0.5">
                  <Change value={item.netVolume} unit="price" size="sm" />
                  <span className="text-xs text-neutral-600">주</span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function SectorRankCard({ loading, sectors }: { loading: boolean; sectors: SectorRank[] }) {
  return (
    <Card>
      <Kicker>섹터별 순위 · 상승 TOP 5</Kicker>

      {loading ? (
        <FlowSkeleton />
      ) : (
        <ol className="flex list-none flex-col">
          {sectors.map((sector, i) => (
            <li
              key={sector.name}
              className="border-divider flex items-center gap-3 border-b py-2 last:border-b-0"
            >
              <span className="num w-5 flex-none text-xs font-semibold text-neutral-500">
                {i + 1}
              </span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="text-sm font-semibold">{sector.name}</span>
                <span className="text-xs text-neutral-600">대표 종목 {sector.topStock}</span>
              </span>
              <Change value={sector.change} display="arrow" size="sm" />
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function FlowSkeleton() {
  return (
    <div className="flex flex-col">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="border-divider flex items-center gap-3 border-b py-2">
          <Skeleton className="size-6 flex-none" />
          <Skeleton className="h-5 flex-1" />
          <Skeleton className="h-5 w-16 flex-none" />
        </div>
      ))}
    </div>
  );
}
