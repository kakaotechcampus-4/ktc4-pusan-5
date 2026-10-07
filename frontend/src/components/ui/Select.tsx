import type { SelectHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

type SelectOption<T extends string> = { value: T; label: string };

type Props<T extends string> = Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  'value' | 'onChange' | 'children'
> & {
  label: string;
  options: SelectOption<T>[];
  value: T;
  onChange: (value: T) => void;
};

/** 드롭다운. 정렬처럼 옵션 중 하나를 고르는 자리에 쓴다. 라벨은 화면에 보이게 둔다. */
export function Select<T extends string>({
  label,
  options,
  value,
  onChange,
  className,
  id,
  ...rest
}: Props<T>) {
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-xs text-neutral-700">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className={cn(
          'min-h-9 rounded-md px-3 py-1.5 text-sm',
          'bg-surface text-ink border-divider border',
          'focus-visible:border-brand hover:border-neutral-400',
          className,
        )}
        {...rest}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
