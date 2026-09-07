import { useParams } from 'react-router-dom';
import {
  Card,
  CardBody,
  CardTitle,
  Change,
  Kicker,
  SkeletonText,
  Stat,
  StatGrid,
  Tag,
} from '@/components/ui';
import { SectionHead, SplitLayout } from '@/components/layout/PageShell';
import { GuardrailNote } from '@/components/layout/GuardrailNote';
import { formatAsOf, formatCompactKRW, formatPrice } from '@/lib/format';

/**
 * 개별 종목 브리핑. 지금은 껍데기다.
 * 실제 연동 시 로딩·빈 상태·에러 3종을 반드시 유지한다. (DESIGN.md 6번)
 */

// 실제 API 붙일 때 삭제한다.
const mockStock = {
  name: '삼성전자',
  code: '005930',
  price: 62400,
  change: -1.08,
  changeAmount: -680,
  marketCap: 372000000000000,
  per: 11.4,
  pbr: 1.32,
  volume: 14203000,
};

export function StockBriefingPage() {
  const { code } = useParams();

  return (
    <SplitLayout
      main={
        <>
          <section>
            <Kicker>종목 브리핑</Kicker>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-h1">{mockStock.name}</h1>
              <Tag>{code ?? mockStock.code}</Tag>
            </div>
            <div className="mt-2 flex items-baseline gap-3">
              <span className="num text-h1 font-bold">{formatPrice(mockStock.price)}</span>
              <Change value={mockStock.changeAmount} unit="price" size="base" />
              <Change value={mockStock.change} size="base" />
            </div>
            <p className="text-sm text-neutral-600">{formatAsOf(new Date())}</p>
          </section>

          <section>
            <StatGrid>
              <Stat label="시가총액" value={formatCompactKRW(mockStock.marketCap)} />
              <Stat label="PER" value={mockStock.per} />
              <Stat label="PBR" value={mockStock.pbr} />
              <Stat label="거래량" value={formatPrice(mockStock.volume)} />
            </StatGrid>
          </section>

          <section>
            <SectionHead title="왜 움직였나" right={<Tag tone="ai">AI 요약</Tag>} />
            <Card>
              {/* 실제 연동 시 로딩 중에만 보이도록 바꾼다 */}
              <SkeletonText lines={4} />
            </Card>
          </section>
        </>
      }
      side={
        <Card tone="plain">
          <GuardrailNote />
          <CardTitle>모르는 개념 물어보기</CardTitle>
          <CardBody>챗 패널이 들어갈 자리입니다.</CardBody>
        </Card>
      }
    />
  );
}
