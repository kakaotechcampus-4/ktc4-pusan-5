import { cn } from '@/lib/cn';

type Tab<T extends string> = { value: T; label: string };

/**
 * value 는 부모가 들고 있는 제어 컴포넌트 — 탭 자체는 상태를 갖지 않음
 */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: Tab<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div role="tablist" className="border-divider flex gap-1 overflow-x-auto border-b">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          role="tab"
          aria-selected={tab.value === value}
          onClick={() => onChange(tab.value)}
          className={cn(
            '-mb-px shrink-0 border-b-2 px-3 py-2 text-sm font-semibold whitespace-nowrap',
            tab.value === value
              ? 'border-brand text-brand'
              : 'hover:text-ink border-transparent text-neutral-600',
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
