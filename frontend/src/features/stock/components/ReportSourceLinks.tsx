import type { ReportSource } from '@/lib/types';
import { toSafeUrl } from './reportLabels';

/** 근거 출처 목록. 링크가 없는 출처는 채널 이름만 보여준다. */
export function ReportSourceLinks({ sources }: { sources: ReportSource[] }) {
  if (sources.length === 0) return null;
  return (
    <ul className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-600">
      <li className="font-semibold">출처</li>
      {sources.map((source, index) => {
        const href = toSafeUrl(source.url);
        const label = source.channel ?? '출처';
        return (
          <li key={`${source.url ?? label}-${index}`}>
            {href ? (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-brand underline"
              >
                {label}
              </a>
            ) : (
              label
            )}
            {source.match === 'indirect' && ' (간접 관련)'}
          </li>
        );
      })}
    </ul>
  );
}
