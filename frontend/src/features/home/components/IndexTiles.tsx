import { Change, ErrorBox, Skeleton } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatPrice } from '@/lib/format';
import type { MarketIndex } from '../mock';

export type IndexStatus = 'loading' | 'error' | 'success';

/**
 * 판단: <Stat /> 은 값 한 줄짜리라 지수·등락 두 줄인 타일에는 맞지 않는다.
 * 지금 스코프(홈·종목 브리핑)에서 지수 타일은 홈에만 쓰이므로 feature 안에 둔다.
 * 다른 화면에도 필요해지면 components/ui 로 올린다.
 *
 * 섹션 제목과 상태 분기를 이 파일이 함께 가진다. 시그널·관심 종목도 같은 모양이라
 * HomePage 는 어느 섹션이든 status 와 onRetry 만 넘기면 된다.
 */
export function IndexSection({
  status,
  indices,
  onRetry,
}: {
  status: IndexStatus;
  indices: MarketIndex[];
  onRetry: () => void;
}) {
  return (
    <section>
      <SectionHead title="주요 지수" />

      {status === 'loading' && <IndexTilesSkeleton />}

      {status === 'error' && (
        <ErrorBox
          title="지수를 불러오지 못했습니다"
          description="잠시 후 다시 시도해주세요"
          onRetry={onRetry}
        />
      )}

      {status === 'success' && <IndexTiles indices={indices} />}
    </section>
  );
}

const GRID = 'grid grid-cols-2 gap-2 sm:grid-cols-4';

function IndexTiles({ indices }: { indices: MarketIndex[] }) {
  return (
    <div className={GRID}>
      {indices.map((item) => (
        <div key={item.name} className="bg-surface flex flex-col gap-1 rounded-md p-3">
          <div className="text-kicker tracking-kicker font-semibold text-neutral-600">
            {item.name}
          </div>
          <div className="num text-h2 font-bold">{formatPrice(item.value)}</div>
          {/* 지수 타일은 화살표. 아래 종목 리스트는 부호. (DESIGN.md 2절) */}
          <Change value={item.change} display="arrow" />
        </div>
      ))}
    </div>
  );
}

/** 실제 타일 높이 100px(여백 24 + 라벨 16 + 값 33 + 등락 20 + 간격 8)에 맞춘다. */
function IndexTilesSkeleton() {
  return (
    <div className={GRID}>
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-25" />
      ))}
    </div>
  );
}
