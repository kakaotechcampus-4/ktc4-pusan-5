import { Button } from '@/components/ui';

/** 종목 상세 헤더의 관심 종목 담기/빼기 토글. 상태는 바깥에서 받는다. */
export function WatchlistToggleButton({
  watched,
  disabled,
  onToggle,
}: {
  watched: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <Button variant="secondary" aria-pressed={watched} disabled={disabled} onClick={onToggle}>
      <span aria-hidden="true">{watched ? '★' : '☆'}</span>
      관심 종목
    </Button>
  );
}
