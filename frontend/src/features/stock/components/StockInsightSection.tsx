import { Card, Empty, Kicker } from '@/components/ui';

/** AI reports and financial trends are intentionally unavailable until their API is ready. */
export function StockInsightSection() {
  return (
    <section>
      <Kicker>AI 보고서 및 재무 추이</Kicker>
      <Card tone="plain">
        <Empty
          title="이 기능은 준비 중입니다"
          description="현재 시세와 주요 지표를 먼저 제공하고 있습니다."
        />
      </Card>
    </section>
  );
}
