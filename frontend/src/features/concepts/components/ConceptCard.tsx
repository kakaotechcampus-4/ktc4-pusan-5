import { Link } from 'react-router-dom';
import { Card, CardBody, CardTitle, Kicker, Skeleton } from '@/components/ui';
import type { ConceptListItem } from '../types';

/**
 * 개념 목록 카드
 */
export function ConceptCard({ item }: { item: ConceptListItem }) {
  const { slug, name, summary, category } = item;

  return (
    <Link to={`/concepts/${slug}`} className="text-ink block h-full rounded-lg no-underline">
      <Card className="h-full transition-shadow hover:shadow-sm">
        <Kicker>
          {category.domain.name} · {category.subdomain.name}
        </Kicker>
        <CardTitle>{name}</CardTitle>
        <CardBody>{summary}</CardBody>
      </Card>
    </Link>
  );
}

// ConceptCard 와 같은 자리&높이의 스켈레톤
export function ConceptCardSkeleton() {
  return (
    <Card className="h-full">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-5 w-32" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-4/5" />
    </Card>
  );
}
