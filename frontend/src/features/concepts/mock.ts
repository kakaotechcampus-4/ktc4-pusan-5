/**
 * 목업 데이터. 실제 값이 아니다. 설명을 위해 임의로 쓴 문장이다.
 *
 * VITE_USE_MOCK=true 일 때만 useConcept 이 API 대신 이걸 읽는다.
 * 백엔드가 붙으면 이 파일은 지워도 화면이 그대로 돈다. (lib/api.ts 만 보면 된다)
 *
 * 선택 섹션(related·quiz)을 섞어둠
 *   treasury-stock : 둘 다 채움 + generatedAt 있음 (AI 표시·가드레일 확인용)
 *   dividend       : 둘 다 채움, generatedAt null (AI 표시 없음 확인용)
 *   per            : quiz 없음 (null 분기 확인용)
 */
import type { Concept } from './types';

export const mockConcepts: Record<string, Concept> = {
  'treasury-stock': {
    slug: 'treasury-stock',
    name: '자사주',
    aliases: ['자기주식'],
    category: {
      domain: { slug: 'shareholder-return', name: '주주환원' },
      subdomain: { slug: 'treasury-stock', name: '자사주' },
    },
    extraCategories: null,
    summary: '회사가 자기 돈으로 자기 회사 주식을 사들여 들고 있는 것.',
    body: [
      '회사가 번 돈을 쓰는 방법은 여러 가지다. 설비에 투자하거나, 빚을 갚거나, **주주에게 돌려주거나** 한다. 마지막 방법 중 하나가 자사주 매입이다. 시장에 나와 있는 자기 회사 주식을 회사 돈으로 사들이는 것이다.',
      '사들인 주식은 회사 금고에 남는다. 이 주식에는 의결권도 배당도 없다. 그래서 시장에서 실제로 거래되는 주식 수가 줄어든다. 같은 이익을 더 적은 주식이 나눠 갖게 되니 주당 가치는 올라간다.',
      '[배당](dividend) 과 자주 비교된다. 배당은 현금을 직접 나눠 주고, 자사주 매입은 주식 수를 줄여 남은 주식의 몫을 키운다. 둘 다 주주환원이지만 받는 방식이 다르다.',
      '매입한 자사주를 **소각**하면 주식 수가 영구히 줄어든다. 소각하지 않고 들고만 있으면 나중에 다시 시장에 팔 수도 있어서, 소각까지 발표했는지가 중요하게 읽힌다.',
    ].join('\n\n'),
    related: [
      { slug: 'dividend', name: '배당', reason: '자사주 매입과 함께 주주환원의 두 축을 이룬다.' },
      {
        slug: 'per',
        name: 'PER',
        reason: '주식 수가 줄면 주당순이익이 올라 PER 이 따라 움직인다.',
      },
    ],
    quiz: [
      {
        question: '회사가 매입한 자사주에도 의결권이 있다.',
        answer: false,
        explanation: '회사가 들고 있는 자기주식에는 의결권이 없다. 배당도 받지 않는다.',
      },
      {
        question: '자사주를 소각하면 발행 주식 수가 영구히 줄어든다.',
        answer: true,
        explanation:
          '소각한 주식은 사라진다. 매입만 하고 들고 있는 경우와 달리 되돌릴 수 없다는 점이 다르다.',
      },
    ],
    updatedAt: '2026-09-15T00:00:00+09:00',
    generatedAt: '2026-09-15T09:20:00+09:00',
    sources: ['한국거래소 공시', '금융감독원 전자공시'],
  },

  dividend: {
    slug: 'dividend',
    name: '배당',
    aliases: ['배당금', '현금배당'],
    category: {
      domain: { slug: 'shareholder-return', name: '주주환원' },
      subdomain: { slug: 'dividend', name: '배당' },
    },
    extraCategories: null,
    summary: '회사가 번 이익의 일부를 주주에게 현금으로 나눠 주는 것.',
    body: [
      '회사가 이익을 내면 그 돈을 회사에 남겨 다시 투자하거나, 주주에게 나눠 준다. 나눠 주는 쪽이 배당이다. 주식 한 주당 얼마씩 준다고 정해서 지급한다.',
      '배당을 받으려면 **배당기준일**에 주주 명부에 이름이 올라 있어야 한다. 기준일 다음 날부터 산 주식에는 그해 배당이 붙지 않는다. 그래서 기준일이 지나면 배당만큼 주가가 내려가는 일이 흔하다.',
      '주가 대비 배당이 얼마인지를 배당수익률이라고 한다. 주가가 내려가면 배당수익률은 올라간다. 수익률만 높다고 좋은 배당주는 아니다. 회사가 어려워져 주가가 빠진 결과일 수도 있다.',
      '[자사주](treasury-stock) 매입과 함께 주주환원의 두 축으로 묶여 이야기된다.',
    ].join('\n\n'),
    related: [
      {
        slug: 'treasury-stock',
        name: '자사주',
        reason: '같은 현금을 나눠 쓰는 관계라 둘을 함께 본다.',
      },
    ],
    quiz: [
      {
        question: '배당기준일 다음 날에 주식을 사도 그해 배당을 받는다.',
        answer: false,
        explanation:
          '기준일에 주주 명부에 올라 있어야 받는다. 하루라도 늦으면 다음 배당을 기다려야 한다.',
      },
    ],
    updatedAt: '2026-09-12T00:00:00+09:00',
    generatedAt: null,
    sources: [],
  },

  per: {
    slug: 'per',
    name: 'PER',
    aliases: ['주가수익비율'],
    category: {
      domain: { slug: 'valuation', name: '기업가치 평가' },
      subdomain: { slug: 'multiple', name: '배수 지표' },
    },
    extraCategories: null,
    summary: '주가가 주당순이익의 몇 배인지를 나타내는 숫자.',
    body: [
      '지금 주가를 주당순이익으로 나눈 값이다. PER 이 10이라면 지금 벌고 있는 이익으로 주가를 회수하는 데 10년이 걸린다는 뜻으로 읽을 수 있다.',
      'PER 이 낮으면 싸다고 흔히 말하지만, 시장이 앞으로 이익이 줄어들 것이라고 보고 있어서 낮은 경우도 많다. 반대로 높은 PER 은 앞으로 이익이 크게 늘 거라는 기대가 이미 주가에 들어가 있다는 뜻이다.',
      '**같은 업종끼리 비교할 때만 의미가 있다.** 성장 속도와 이익 구조가 다른 업종을 PER 숫자만으로 견주면 엉뚱한 결론이 나온다.',
    ].join('\n\n'),
    related: [
      {
        slug: 'treasury-stock',
        name: '자사주',
        reason: '자사주 소각으로 주식 수가 줄면 주당순이익이 올라 PER 이 낮아진다.',
      },
    ],
    quiz: null,
    updatedAt: '2026-09-10T00:00:00+09:00',
    generatedAt: '2026-09-10T08:00:00+09:00',
    sources: ['한국거래소'],
  },
};
