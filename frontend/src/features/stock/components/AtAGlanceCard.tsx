import { Card, InfoTip, Kicker } from '@/components/ui';
import { formatCompactKRW, formatMultiple, formatPrice, formatRatio } from '@/lib/format';
import type { StockDetail, StockQuote } from '../mock';

type Row = { label: string; value: string; description?: string };

/**
 * stock·detail을 라벨-값 리스트로 바꾸는 순수 함수.
 * 렌더링과 분리 -> 항목 구성이 바뀔 때 이 함수만 보면 됨
 */
function buildRows(stock: StockQuote, detail: StockDetail): Row[] {
  const a = detail.atAGlance;
  return [
    { label: '시가총액', value: formatCompactKRW(stock.marketCap) },
    { label: '거래량', value: `${formatPrice(stock.volume)}주` },
    {
      label: '거래대금',
      value: formatCompactKRW(detail.tradingValue),
      description: '그날 거래된 주식 수에 가격을 곱한 총 금액입니다.',
    },
    {
      label: '외국인 보유',
      value: formatRatio(detail.foreignOwnership),
      description: '전체 발행주식 중 외국인 투자자가 보유한 비율입니다.',
    },
    {
      label: 'PER',
      value: formatMultiple(a.per),
      description:
        '주가를 주당순이익(EPS)으로 나눈 값. 낮을수록 이익 대비 주가가 저평가됐다고 봅니다.',
    },
    {
      label: 'PBR',
      value: formatMultiple(a.pbr),
      description:
        '주가를 주당순자산(BPS)으로 나눈 값. 1보다 낮으면 장부가치보다 싸게 거래된다는 뜻입니다.',
    },
    {
      label: 'EPS',
      value: `${formatPrice(a.eps)}원`,
      description: '한 주당 벌어들인 순이익입니다.',
    },
    {
      label: 'BPS',
      value: `${formatPrice(a.bps)}원`,
      description: '한 주당 순자산(자본금) 가치입니다.',
    },
    { label: '52주 최고', value: `${formatPrice(a.week52High)}원` },
    { label: '52주 최저', value: `${formatPrice(a.week52Low)}원` },
  ];
}

/* 헤더 근처의 요약 리스트 */
export function AtAGlanceCard({ stock, detail }: { stock: StockQuote; detail: StockDetail }) {
  const rows = buildRows(stock, detail);

  return (
    <Card tone="plain" className="flex-1">
      <Kicker>AT A GLANCE · 주요 지표</Kicker>
      <dl className="flex flex-1 flex-col justify-center">
        {rows.map((row) => (
          <div
            key={row.label}
            className="border-divider flex items-center justify-between border-b py-2 last:border-b-0"
          >
            <dt className="flex items-center gap-1 text-sm text-neutral-600">
              {row.label}
              {row.description && <InfoTip description={row.description} />}
            </dt>
            <dd className="num text-sm font-semibold">{row.value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
