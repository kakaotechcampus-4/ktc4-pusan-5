import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import { Link } from 'react-router-dom';

/**
 * 서버가 내려준 마크다운을 그리는 공용 렌더러, 개념 본문·브리핑·챗봇 답변에 사용
 *
 * remark 플러그인 X, 문단·볼드·링크만 적용
 * 개념 사이의 링크는 href 에 slug 만 ([배당](dividend))
 * http 로 시작하지 않는 href 는 /concepts/{slug} 로 보냄
 */
const CONCEPT_PATH_PREFIX = '/concepts/';

function isExternalHref(href: string): boolean {
  return href.startsWith('http');
}

function MarkdownLink({ href, children }: { href?: string; children?: ReactNode }) {
  if (!href) return <>{children}</>;

  if (isExternalHref(href)) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className="text-brand underline">
        {children}
      </a>
    );
  }

  return (
    <Link to={`${CONCEPT_PATH_PREFIX}${href}`} className="text-brand underline">
      {children}
    </Link>
  );
}

function MarkdownParagraph({ children }: { children?: ReactNode }) {
  return <p className="text-ink text-base leading-relaxed">{children}</p>;
}

function MarkdownStrong({ children }: { children?: ReactNode }) {
  return <strong className="font-semibold">{children}</strong>;
}

/** 재사용을 위한 모듈 상수 */
const MARKDOWN_COMPONENTS = {
  a: MarkdownLink,
  p: MarkdownParagraph,
  strong: MarkdownStrong,
};

export function Markdown({ children }: { children: string }) {
  // 문단 사이 간격
  return (
    <div className="flex flex-col gap-3">
      <ReactMarkdown components={MARKDOWN_COMPONENTS}>{children}</ReactMarkdown>
    </div>
  );
}
