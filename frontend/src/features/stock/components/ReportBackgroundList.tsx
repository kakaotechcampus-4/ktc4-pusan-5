import { Kicker } from '@/components/ui';
import type { ReportBackground, ReportBackgroundItem } from '@/lib/types';
import { ReportSourceLinks } from './ReportSourceLinks';

const GROUPS: { key: keyof ReportBackground; label: string }[] = [
  { key: 'bullish', label: '긍정적으로 볼 배경' },
  { key: 'bearish', label: '부정적으로 볼 배경' },
  { key: 'neutral', label: '함께 알아둘 배경' },
];

function ReportBackgroundRow({ item }: { item: ReportBackgroundItem }) {
  return (
    <li className="flex flex-col gap-1 text-sm leading-relaxed text-neutral-700">
      <span>
        {item.text}
        {item.watch && <span className="text-xs text-neutral-600"> · 앞으로 지켜볼 점</span>}
      </span>
      <ReportSourceLinks sources={item.sources} />
    </li>
  );
}

export function ReportBackgroundList({ background }: { background: ReportBackground }) {
  const groups = GROUPS.filter((group) => background[group.key].length > 0);
  if (groups.length === 0) return null;
  return (
    <div className="flex flex-col gap-3">
      {groups.map((group) => (
        <section key={group.key} className="flex flex-col gap-2">
          <Kicker>{group.label}</Kicker>
          <ul className="flex flex-col gap-2">
            {background[group.key].map((item, index) => (
              <ReportBackgroundRow key={`${item.text}-${index}`} item={item} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
