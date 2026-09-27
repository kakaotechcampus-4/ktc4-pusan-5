import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  Card,
  Change,
  Empty,
  ErrorBox,
  Kicker,
  Skeleton,
  StockAvatar,
  Tabs,
} from '@/components/ui';
import { SectionHead, SplitLayout } from '@/components/layout/PageShell';
import type { FlowBoard, SectorBoard } from '@/lib/types';

export function MarketFlowSection({
  loading,
  failed,
  flows,
  sectors,
  onRetry,
}: {
  loading: boolean;
  failed: boolean;
  flows: FlowBoard[];
  sectors: SectorBoard[];
  onRetry: () => void;
}) {
  const [flowTab, setFlowTab] = useState<FlowBoard['kind']>('flowBuy');
  const [sectorTab, setSectorTab] = useState<SectorBoard['kind']>('sectorKospi');
  const flow = flows.find((board) => board.kind === flowTab);
  const sector = sectors.find((board) => board.kind === sectorTab);
  return (
    <section>
      <SectionHead title="외국인 및 기관 동향 및 섹터" />
      <SplitLayout
        main={
          <Card>
            <Kicker>외국인·기관 합계 · 기타 법인 포함</Kicker>
            <Tabs
              tabs={[
                { value: 'flowBuy', label: '순매수' },
                { value: 'flowSell', label: '순매도' },
              ]}
              value={flowTab}
              onChange={setFlowTab}
            />
            <BoardState loading={loading} failed={failed} board={flow} onRetry={onRetry}>
              <ol className="flex list-none flex-col">
                {flow?.items.map((item, i) => (
                  <li key={item.code}>
                    <Link
                      to={`/stock/${item.code}`}
                      className="border-divider text-ink flex items-center gap-3 border-b py-2 no-underline hover:bg-neutral-100"
                    >
                      <span className="num w-5 flex-none text-xs font-semibold text-neutral-500">
                        {i + 1}
                      </span>
                      <StockAvatar initial={item.name.slice(0, 1)} size="sm" />
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold">
                        {item.name}
                      </span>
                      <span className="flex items-baseline gap-0.5">
                        <Change value={item.netVolume} unit="price" size="sm" />
                        <span className="text-xs text-neutral-600">주</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ol>
            </BoardState>
          </Card>
        }
        side={
          <Card>
            <Kicker>업종 지수 등락률 · TOP 5</Kicker>
            <Tabs
              tabs={[
                { value: 'sectorKospi', label: '코스피' },
                { value: 'sectorKosdaq', label: '코스닥' },
              ]}
              value={sectorTab}
              onChange={setSectorTab}
            />
            <BoardState loading={loading} failed={failed} board={sector} onRetry={onRetry}>
              <ol className="flex list-none flex-col">
                {sector?.items.map((item, i) => (
                  <li
                    key={item.name}
                    className="border-divider flex items-center gap-3 border-b py-2 last:border-b-0"
                  >
                    <span className="num w-5 flex-none text-xs font-semibold text-neutral-500">
                      {i + 1}
                    </span>
                    <span className="min-w-0 flex-1 text-sm font-semibold">{item.name}</span>
                    <Change value={item.change} display="arrow" size="sm" />
                  </li>
                ))}
              </ol>
            </BoardState>
          </Card>
        }
      />
    </section>
  );
}

function BoardState({
  loading,
  failed,
  board,
  onRetry,
  children,
}: {
  loading: boolean;
  failed: boolean;
  board?: FlowBoard | SectorBoard;
  onRetry: () => void;
  children: ReactNode;
}) {
  if (loading) return <FlowSkeleton />;
  const hasItems = Boolean(board?.items.length);
  const unavailable = failed || board?.status === 'unavailable';
  return (
    <>
      {unavailable && (
        <ErrorBox
          title="정보를 갱신하지 못했습니다"
          description={hasItems ? '마지막으로 수집한 데이터입니다.' : '잠시 후 다시 시도해주세요.'}
          onRetry={onRetry}
        />
      )}
      {!failed && board?.status === 'stale' && (
        <p role="status" className="text-sm text-neutral-700">
          갱신 지연 · 마지막으로 수집한 데이터입니다.
        </p>
      )}
      {!unavailable && (!board || board.status === 'pending') && (
        <Empty title="첫 데이터를 수집 중입니다" description="잠시 후 자동으로 갱신됩니다." />
      )}
      {!unavailable && board && board.status !== 'pending' && !hasItems && (
        <Empty
          title="표시할 데이터가 없습니다"
          description="거래가 없는 시간에는 순위가 비어 있을 수 있습니다."
        />
      )}
      {hasItems && children}
    </>
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
