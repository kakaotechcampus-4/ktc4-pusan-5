import { Kicker, Skeleton } from '@/components/ui';
import { formatAsOf } from '@/lib/format';
import { StockSearchBox } from './StockSearchBox';

export function HomeHero({ asOf, loading = false }: { asOf?: string; loading?: boolean }) {
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Kicker>TODAY</Kicker>
        {/* 기준 시각은 시세와 함께 온다. 로딩 중에는 스켈레톤으로 자리를 잡아둔다.
            시세를 못 가져왔으면 아무것도 쓰지 않는다. 스켈레톤을 계속 두면
            실패한 뒤에도 아직 불러오는 중인 것처럼 보인다. (실패 사실은 아래 지수 섹션이 알린다) */}
        {asOf && <p className="text-sm text-neutral-600">{formatAsOf(new Date(asOf))}</p>}
        {!asOf && loading && <Skeleton className="h-4 w-64" />}
      </div>

      {/* text-display 는 DESIGN.md 상 이 히어로 한 곳에만 쓴다. */}
      <h1 className="text-display">
        내 종목이 왜 움직였는지
        <br />
        오늘 안에 이해합니다
      </h1>

      <StockSearchBox />
    </section>
  );
}
