/**
 * 개념 API 응답 타입. 백엔드와 합의된 계약 그대로다.
 *
 * 원래 자리는 lib/types.ts 지만 아직 없다. 그 파일이 생기면 여기 타입을 그대로 옮긴다.
 * 백엔드는 값을 가공하지 않고 주고, 표시 문구·포맷은 프론트가 만든다. (루트 CLAUDE.md)
 */

/** 분류 트리의 한 마디. 도메인·서브도메인이 같은 모양이다. */
export type ConceptCategoryNode = {
  slug: string;
  name: string;
};

export type ConceptCategory = {
  domain: ConceptCategoryNode;
  subdomain: ConceptCategoryNode;
};

/** 관련 개념 링크 : slug -> /concepts/{slug} */
export type ConceptRelation = {
  slug: string;
  name: string;
  reason: string;
};

/** O/X 퀴즈 한 문항 */
export type ConceptQuizItem = {
  question: string;
  answer: boolean;
  explanation: string;
};

export type Concept = {
  slug: string;
  name: string;
  aliases: string[];
  category: ConceptCategory;
  extraCategories: ConceptCategory[] | null;
  summary: string;
  /** 마크다운 */
  body: string;
  related: ConceptRelation[] | null;
  quiz: ConceptQuizItem[] | null;
  /** ISO 8601 */
  updatedAt: string;
  /** ISO 8601 */
  generatedAt: string | null;
  sources: string[];
};

/** 목록 응답 원소, 아직 미구현 */
export type ConceptListItem = Pick<Concept, 'slug' | 'name' | 'aliases' | 'summary' | 'category'>;

export type ConceptListResponse = {
  items: ConceptListItem[];
};
