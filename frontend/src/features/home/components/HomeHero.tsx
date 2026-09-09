import { useState, type FormEvent } from 'react';
import { Button, Input, Kicker, Skeleton } from '@/components/ui';
import { formatAsOf } from '@/lib/format';

export function HomeHero({ asOf, loading = false }: { asOf?: string; loading?: boolean }) {
  const [query, setQuery] = useState('');

  // 판단: 검색 인덱스가 아직 없어서 제출은 아무것도 하지 않는다.
  // 입력·포커스·키보드 제출까지는 실제로 동작시킨다. disabled 로 막지 않는다.
  // 실제 연동 시 이 자리에 검색 호출을 넣고, 결과 없음 처리도 여기에 붙는다.
  function handleSubmit(e: FormEvent) {
    e.preventDefault();
  }

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

      <div className="flex max-w-lg flex-col gap-2">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="종목 · 개념 · 용어 검색"
            aria-label="종목 또는 개념 검색"
            aria-describedby="home-search-note"
          />
          <Button type="submit" variant="primary">
            검색
          </Button>
        </form>
        <p id="home-search-note" className="text-xs text-neutral-600">
          검색은 아직 동작하지 않습니다. 화면만 먼저 만들어 두었습니다.
        </p>
      </div>
    </section>
  );
}
