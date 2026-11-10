import { Card, Tag } from '@/components/ui';
import type { ReportFactor } from '@/lib/types';
import { LAYER_LABEL, STANCE_LABEL, STRENGTH_LABEL } from './reportLabels';
import { ReportSourceLinks } from './ReportSourceLinks';

function ReportFactorItem({ factor }: { factor: ReportFactor }) {
  const notes = factor.links.filter((link) => link.note);
  return (
    <Card tone="plain">
      <div className="flex flex-wrap items-center gap-2">
        {factor.stance && <Tag tone="neutral">{STANCE_LABEL[factor.stance]}</Tag>}
        {factor.unconfirmed && <Tag tone="outline">확인되지 않은 내용</Tag>}
      </div>
      <div className="text-ink font-semibold">{factor.event}</div>
      {factor.detail && <p className="text-sm leading-relaxed text-neutral-700">{factor.detail}</p>}
      {notes.length > 0 && (
        <ul className="flex flex-col gap-2 text-sm text-neutral-700">
          {notes.map((link, index) => (
            <li key={`${link.layer}-${index}`} className="flex flex-col gap-0.5">
              <span className="text-xs text-neutral-600">
                {LAYER_LABEL[link.layer]}
                {link.strength && ` · ${STRENGTH_LABEL[link.strength]}`}
              </span>
              <span className="leading-relaxed">{link.note}</span>
            </li>
          ))}
        </ul>
      )}
      <ReportSourceLinks sources={factor.sources} />
    </Card>
  );
}

export function ReportFactorList({ factors }: { factors: ReportFactor[] }) {
  if (factors.length === 0) return null;
  return (
    <ul className="flex flex-col gap-2">
      {factors.map((factor, index) => (
        <li key={`${factor.event}-${index}`}>
          <ReportFactorItem factor={factor} />
        </li>
      ))}
    </ul>
  );
}
