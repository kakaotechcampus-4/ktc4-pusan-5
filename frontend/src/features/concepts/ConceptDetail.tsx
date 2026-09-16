import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Empty, ErrorBox, SkeletonText } from '@/components/ui';
import { useConcept } from './useConcept';
import { ConceptHeader, ConceptHeaderSkeleton } from './components/ConceptHeader';
import { ConceptBody } from './components/ConceptBody';
import { ConceptRelated } from './components/ConceptRelated';
import { ConceptQuiz } from './components/ConceptQuiz';
import { ConceptMeta } from './components/ConceptMeta';

/**
 * 개념 페이지 렌더링
 * 나중에 종목 브리핑 옆 패널에서 컴포넌트 재사용
 * 선택 섹션은 서버가 null 로 주면 자리 동적으로 없앰
 */
export function ConceptDetail({ slug }: { slug: string | undefined }) {
  const navigate = useNavigate();
  const { status, concept, retry } = useConcept(slug);

  // 서버 저장으로 바꿀 때 ConceptQuiz 는 건드리지 않음
  const [quizAnswers, setQuizAnswers] = useState<Record<number, boolean>>({});

  // 관련 개념 링크로 이동하면 앞 개념에서 고른 답이 남지 않게 렌더링 중에 비움
  const [trackedSlug, setTrackedSlug] = useState(slug);
  if (slug !== trackedSlug) {
    setTrackedSlug(slug);
    setQuizAnswers({});
  }

  function handleQuizAnswer(index: number, picked: boolean) {
    setQuizAnswers((previous) => ({ ...previous, [index]: picked }));
  }

  if (status === 'loading') {
    return <ConceptDetailSkeleton />;
  }

  // 없는 개념 페이지
  if (status === 'notFound') {
    return (
      <Empty
        title="개념을 찾을 수 없습니다"
        description="주소가 맞는지 확인하거나 홈에서 다시 찾아보세요"
        action={
          <Button variant="primary" onClick={() => navigate('/')}>
            홈으로
          </Button>
        }
      />
    );
  }

  if (status === 'error') {
    return (
      <ErrorBox
        title="개념을 불러오지 못했습니다"
        description="잠시 후 다시 시도해주세요"
        onRetry={retry}
      />
    );
  }

  // status 가 success 면 concept 이 함께 들어옴 (useConcept 이 둘을 한 번에 세팅)
  if (!concept) return null;

  return (
    <article className="flex flex-col gap-8">
      <ConceptHeader concept={concept} />
      <ConceptBody body={concept.body} />

      {concept.related && <ConceptRelated relations={concept.related} />}
      {concept.quiz && (
        <ConceptQuiz items={concept.quiz} answers={quizAnswers} onAnswer={handleQuizAnswer} />
      )}

      <ConceptMeta concept={concept} />
    </article>
  );
}

/** 페이지 스켈레톤 : 제목·요약·본문 4 line */
export function ConceptDetailSkeleton() {
  return (
    <article className="flex flex-col gap-8">
      <ConceptHeaderSkeleton />
      <section>
        <SkeletonText lines={4} />
      </section>
    </article>
  );
}
