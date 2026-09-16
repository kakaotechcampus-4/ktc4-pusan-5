import { Link } from 'react-router-dom';
import { Card } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import type { ConceptRelation } from '../types';

/** 관련 개념 : 같은 페이지 안에서 slug 만 바뀌므로 useConcept 이 다시 불러옴 */
export function ConceptRelated({ relations }: { relations: ConceptRelation[] }) {
  return (
    <section>
      <SectionHead title="관련 개념" />
      <Card>
        <ul className="flex list-none flex-col gap-3">
          {relations.map((relation) => (
            <li key={relation.slug} className="flex flex-col gap-1">
              <Link
                to={`/concepts/${relation.slug}`}
                className="text-brand text-base font-semibold no-underline hover:underline"
              >
                {relation.name}
              </Link>
              <p className="text-sm text-neutral-700">{relation.reason}</p>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}
