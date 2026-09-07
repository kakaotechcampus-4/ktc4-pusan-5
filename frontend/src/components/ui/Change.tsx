import { direction, formatPct, formatPctArrow, formatPrice } from '@/lib/format';
import { cn } from '@/lib/cn';

type Props = {
  /** 등락률(%) 또는 등락액(원) */
  value: number;
  /** 'pct' 등락률 | 'price' 등락액 */
  unit?: 'pct' | 'price';
  /** 'sign' 부호(+/−) — 표·리스트 | 'arrow' 화살표(▲/▼) — 카드·지수 */
  display?: 'sign' | 'arrow';
  /** 기본 text-sm. 큰 헤더 숫자에만 키운다. */
  size?: 'xs' | 'sm' | 'base' | 'h2';
  className?: string;
};

/**
 * ⚠️ 등락 숫자는 반드시 이 컴포넌트로 그린다.
 * 상승 빨강 / 하락 파랑 / 보합 회색 규칙이 프로젝트에서 여기 한 곳에만 있다.
 * 화면 코드에서 text-up / text-down 을 직접 쓰지 않는다.
 */
const TONE = {
  up: 'text-up',
  down: 'text-down',
  flat: 'text-flat',
} as const;

const SIZE = {
  xs: 'text-xs',
  sm: 'text-sm',
  base: 'text-base',
  h2: 'text-h2',
} as const;

export function Change({
  value,
  unit = 'pct',
  display = 'sign',
  size = 'sm',
  className,
}: Props) {
  const dir = direction(value);

  let text: string;
  if (unit === 'price') {
    text = formatPrice(value);
    if (value > 0) text = `+${text}`;
  } else {
    text = display === 'arrow' ? formatPctArrow(value) : formatPct(value);
  }

  return (
    <span className={cn('num font-semibold', TONE[dir], SIZE[size], className)}>
      {text}
    </span>
  );
}
