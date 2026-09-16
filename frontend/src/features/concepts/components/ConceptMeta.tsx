import { Tag } from '@/components/ui';
import { GuardrailNote } from '@/components/layout/GuardrailNote';
import { formatAsOf } from '@/lib/format';
import type { Concept } from '../types';

/**
 * 문서 하단 메타
 */
export function ConceptMeta({ concept }: { concept: Concept }) {
  const { updatedAt, generatedAt, sources } = concept;

  return (
    <footer className="border-divider flex flex-col gap-2 border-t pt-4 text-xs text-neutral-600">
      <div>{formatAsOf(new Date(updatedAt), '문서 갱신 기준')}</div>

      {generatedAt && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Tag tone="ai">AI 생성</Tag>
            <span>{formatAsOf(new Date(generatedAt), 'AI 생성')}</span>
          </div>
          <GuardrailNote />
        </>
      )}

      {sources.length > 0 && <div>출처 {sources.join(', ')}</div>}
    </footer>
  );
}
