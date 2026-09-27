import { cn } from '@/lib/cn';

type FilterChip<T extends string> = { value: T; label: string };


// 전체 개념 목록을 대분류 조건으로 필터링(현재 단일)
export function FilterChips<T extends string>({
  label,
  chips,
  value,
  onChange,
}: {
  label: string;
  chips: FilterChip<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {chips.map((chip) => (
        <button
          key={chip.value}
          type="button"
          aria-pressed={chip.value === value}
          onClick={() => onChange(chip.value)}
          className={cn(
            'rounded-full px-4 py-2 text-sm font-semibold whitespace-nowrap',
            chip.value === value
              ? 'bg-brand text-white hover:bg-brand-500 active:bg-brand-700'
              : 'bg-canvas text-ink border border-divider hover:border-brand hover:bg-brand-100 hover:text-brand',
          )}
        >
          {chip.label}
        </button>
      ))}
    </div>
  );
}
