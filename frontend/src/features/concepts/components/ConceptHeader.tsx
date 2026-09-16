import { Kicker, Skeleton, Tag } from '@/components/ui';
import type { Concept } from '../types';

/** 분류 경로 · 이름 · 한 줄 요약 · 별칭. 화면에서 가장 먼저 읽히는 자리다. */
export function ConceptHeader({ concept }: { concept: Concept }) {
  const { category, name, summary, aliases } = concept;

  return (
    <section className="flex flex-col gap-2">
      <Kicker>
        {category.domain.name} · {category.subdomain.name}
      </Kicker>
      <h1 className="text-h1">{name}</h1>
      <p className="text-base text-neutral-700">{summary}</p>
      {aliases.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {aliases.map((alias) => (
            <Tag key={alias}>{alias}</Tag>
          ))}
        </div>
      )}
    </section>
  );
}

export function ConceptHeaderSkeleton() {
  return (
    <section className="flex flex-col gap-2">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-6 w-3/5" />
    </section>
  );
}
