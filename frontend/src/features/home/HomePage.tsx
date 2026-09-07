import { Link } from 'react-router-dom';
import { Card, CardBody, CardTitle, Change, Kicker } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatAsOf, formatPrice } from '@/lib/format';

/**
 * 홈 화면. 지금은 하네스가 제대로 붙었는지 확인하는 껍데기다.
 * 실제 데이터 연동은 담당자가 채운다.
 */

// 실제 API 붙일 때 삭제한다. mock 접두사로 구분.
const mockIndices = [
  { name: '코스피', price: 2841.32, change: 1.24 },
  { name: '코스닥', price: 812.45, change: -0.87 },
  { name: '코스피200', price: 384.11, change: 0.0 },
];

export function HomePage() {
  return (
    <>
      <section>
        <Kicker>TODAY</Kicker>
        <h1 className="text-h1">오늘 시장은 이렇게 움직였습니다</h1>
        <p className="text-sm text-neutral-600">{formatAsOf(new Date())}</p>
      </section>

      <section>
        <SectionHead title="주요 지수" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {mockIndices.map((item) => (
            <Card key={item.name} tone="plain">
              <CardMetaRow name={item.name} />
              <div className="num text-h2 font-bold">{formatPrice(item.price)}</div>
              <Change value={item.change} display="arrow" />
            </Card>
          ))}
        </div>
      </section>

      <section>
        <SectionHead title="관심 종목" />
        <Card>
          <CardTitle>삼성전자</CardTitle>
          <CardBody>여기에 브리핑 요약이 들어갑니다.</CardBody>
          <Link to="/stock/005930" className="text-sm">
            브리핑 보기
          </Link>
        </Card>
      </section>
    </>
  );
}

function CardMetaRow({ name }: { name: string }) {
  return <div className="text-sm text-neutral-600">{name}</div>;
}
