import type { ReportTerm } from '@/lib/types';

/** 초보자가 모르는 용어를 그 자리에서 풀어 준다. */
export function ReportTermList({ terms }: { terms: ReportTerm[] }) {
  if (terms.length === 0) return null;
  return (
    <dl className="flex flex-col gap-2 text-sm">
      {terms.map((item, index) => (
        <div key={`${item.term}-${index}`} className="flex flex-col gap-0.5">
          <dt className="text-ink font-semibold">{item.term}</dt>
          <dd className="leading-relaxed text-neutral-700">{item.plain}</dd>
        </div>
      ))}
    </dl>
  );
}
