import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Button, Input, StockAvatar } from '@/components/ui';
import { mockSearchIndex } from '../mock';

const MAX_SUGGESTIONS = 6;

/**
 * 종목 자동완성 검색창. 히어로의 타이틀·기준시각 표시와 책임을 분리해서
 * 입력·필터링·드롭다운 상태는 여기서만 관리한다.
 */
export function StockSearchBox() {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);

  const trimmed = query.trim();
  const suggestions = trimmed
    ? mockSearchIndex
        .filter((stock) => stock.name.toLowerCase().includes(trimmed.toLowerCase()))
        .slice(0, MAX_SUGGESTIONS)
    : [];
  const showSuggestions = open && suggestions.length > 0;
  const showEmpty = open && trimmed.length > 0 && suggestions.length === 0;

  // 판단: 자동완성에서 고르지 않고 그냥 제출하면(엔터) 갈 곳이 없다.
  // 검색 자체는 아직 자유 검색을 지원하지 않는다고 알린다.
  function handleSubmit(e: FormEvent) {
    e.preventDefault();
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
            aria-expanded={showSuggestions}
            aria-autocomplete="list"
            autoComplete="off"
          />
          <Button type="submit" variant="primary">
            검색
          </Button>
        </form>

        {(showSuggestions || showEmpty) && (
          <ul
            role="listbox"
            className="border-divider bg-canvas absolute top-full right-0 left-0 z-20 mt-1 flex list-none flex-col overflow-hidden rounded-md border shadow-md"
          >
            {showEmpty && (
              <li className="px-3 py-2 text-sm text-neutral-600">검색 결과가 없습니다</li>
            )}
            {suggestions.map((stock) => (
              <li key={stock.code} role="option">
                <Link
                  to={`/stock/${stock.code}`}
                  className="text-ink flex items-center gap-2 px-3 py-2 no-underline hover:bg-neutral-100"
                >
                  <StockAvatar initial={stock.initial} size="sm" />
                  <span className="text-sm font-semibold">{stock.name}</span>
                  <span className="num ml-auto text-xs text-neutral-500">{stock.code}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p id="home-search-note" className="text-xs text-neutral-600">
        자동완성에서 종목을 선택하면 상세 페이지로 이동합니다. 자유 검색은 아직 동작하지 않습니다.
      </p>
    </div>
  );
}
