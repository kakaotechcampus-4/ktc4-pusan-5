import { Kicker, Tag } from '@/components/ui';
import type { ReportSummary, ReportVerdict } from '@/lib/types';
import { VERDICT_LABEL } from './reportLabels';

const ROWS: { key: keyof Omit<ReportSummary, 'move'>; label: string }[] = [
  { key: 'mainCause', label: '주된 원인' },
  { key: 'relative', label: '시장·동종 대비' },
  { key: 'counter', label: '반대로 볼 수 있는 점' },
  { key: 'unexplained', label: '설명되지 않은 부분' },
];

export function ReportSummaryBlock({
  summary,
  verdict,
  relativeVerdict,
}: {
  summary: ReportSummary;
  verdict: ReportVerdict;
  relativeVerdict: ReportVerdict | null;
}) {
  const rows = ROWS.filter((row) => summary[row.key]);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Tag tone={verdict === 'explained' ? 'brand' : 'neutral'}>{VERDICT_LABEL[verdict]}</Tag>
        {relativeVerdict && <Tag tone="neutral">대비 판단 · {VERDICT_LABEL[relativeVerdict]}</Tag>}
      </div>
      {summary.move && (
        <p className="text-ink text-base leading-relaxed font-semibold">{summary.move}</p>
      )}
      {rows.length > 0 && (
        <dl className="flex flex-col gap-3">
          {rows.map((row) => (
            <div key={row.key} className="flex flex-col gap-1">
              <dt>
                <Kicker>{row.label}</Kicker>
              </dt>
              <dd className="text-sm leading-relaxed text-neutral-700">{summary[row.key]}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
