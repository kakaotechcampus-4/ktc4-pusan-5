import { useState, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button, Input, StockAvatar } from '@/components/ui';
import { useSearch } from '../useSearch';

/**
 * 종목·개념 자동완성 검색창. 히어로의 타이틀·기준시각 표시와 책임을 분리해서
 * 입력·드롭다운 상태는 여기서만 관리한다. 검색 요청은 useSearch 가 맡는다.
 */
export function StockSearchBox() {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { status, stocks, concepts } = useSearch(query);

  const hasResults = stocks.length > 0 || concepts.length > 0;
  const showDropdown = open && status !== 'idle';

  // 엔터는 첫 번째 결과로 이동한다. 결과가 없으면 아무 일도 일어나지 않는다.
  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (stocks.length > 0) navigate(`/stock/${stocks[0].code}`);
    else if (concepts.length > 0) navigate(`/concepts/${concepts[0].slug}`);
  }

  return (
    <div className="flex max-w-lg flex-col gap-2">
      <div className="relative">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            placeholder="종목 · 개념 · 용어 검색"
            aria-label="종목 또는 개념 검색"
            aria-describedby="home-search-note"
            role="combobox"
            aria-expanded={showDropdown && hasResults}
            aria-autocomplete="list"
            autoComplete="off"
          />
          <Button type="submit" variant="primary">
            검색
          </Button>
        </form>

        {showDropdown && (
          <ul
            role="listbox"
            className="border-divider bg-canvas absolute top-full right-0 left-0 z-20 mt-1 flex max-h-80 list-none flex-col overflow-y-auto rounded-md border shadow-md"
          >
            {status === 'loading' && <SearchMessage>검색 중입니다</SearchMessage>}
            {status === 'error' && (
              <SearchMessage>검색하지 못했습니다. 잠시 후 다시 시도해주세요</SearchMessage>
            )}
            {status === 'success' && !hasResults && (
              <SearchMessage>검색 결과가 없습니다</SearchMessage>
            )}

            {status === 'success' && stocks.length > 0 && (
              <>
                <SearchGroupLabel>종목</SearchGroupLabel>
                {stocks.map((stock) => (
                  <li key={stock.code} role="option" aria-selected={false}>
                    <Link
                      to={`/stock/${stock.code}`}
                      className="text-ink flex items-center gap-2 px-3 py-2 no-underline hover:bg-neutral-100"
                    >
                      <StockAvatar initial={stock.name.charAt(0)} size="sm" />
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold">
                        {stock.name}
                      </span>
                      <span className="num flex-none text-xs text-neutral-500">{stock.code}</span>
                    </Link>
                  </li>
                ))}
              </>
            )}

            {status === 'success' && concepts.length > 0 && (
              <>
                <SearchGroupLabel>개념</SearchGroupLabel>
                {concepts.map((concept) => (
                  <li key={concept.slug} role="option" aria-selected={false}>
                    <Link
                      to={`/concepts/${concept.slug}`}
                      className="text-ink flex flex-col gap-1 px-3 py-2 no-underline hover:bg-neutral-100"
                    >
                      <span className="text-sm font-semibold">{concept.name}</span>
                      <span className="truncate text-xs text-neutral-600">{concept.summary}</span>
                    </Link>
                  </li>
                ))}
              </>
            )}
          </ul>
        )}
      </div>

      <p id="home-search-note" className="text-xs text-neutral-600">
        종목을 고르면 종목 상세로, 개념을 고르면 개념 페이지로 이동합니다.
      </p>
    </div>
  );
}

function SearchMessage({ children }: { children: ReactNode }) {
  return (
    <li role="status" className="px-3 py-2 text-sm text-neutral-600">
      {children}
    </li>
  );
}

function SearchGroupLabel({ children }: { children: ReactNode }) {
  return (
    <li
      role="presentation"
      className="text-kicker tracking-kicker px-3 pt-2 font-semibold text-neutral-600"
    >
      {children}
    </li>
  );
}
