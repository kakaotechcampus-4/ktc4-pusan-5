import type { InputHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

type Props = InputHTMLAttributes<HTMLInputElement> & { label?: string };

export function Input({ label, className, id, ...rest }: Props) {
  const input = (
    <input
      id={id}
      className={cn(
        'w-full min-h-9 rounded-md px-3 py-1.5 text-sm',
        'bg-surface text-ink caret-brand border border-divider',
        'hover:border-neutral-400 focus-visible:border-brand',
        'placeholder:text-neutral-500',
        className,
      )}
      {...rest}
    />
  );
  if (!label) return input;
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs text-neutral-700">
        {label}
      </label>
      {input}
    </div>
  );
}
