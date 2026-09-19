import { Markdown } from '@/components/ui';

/**
 * 개념 본문, 서버가 마크다운으로 넘겨줌
 * 본문 안의 개념 링크는 Markdown 렌더러가 /concepts/{slug} 로 보냄
 */
export function ConceptBody({ body }: { body: string }) {
  return (
    <section>
      <Markdown>{body}</Markdown>
    </section>
  );
}
