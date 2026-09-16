import { Card, Change, Kicker, Stat } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import type { InvestorFlow } from '../mock';

/** 개인/외국인/기관 수급 숫자만. 기간별 변화는 차트 없이 등락률로만 보여줌 */
export function InvestorFlowSection({ flow }: { flow: InvestorFlow }) {
  return (
    <section>
      <SectionHead title="수급 동향" />
      <Card tone="plain">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <Stat label="개인" value={<FlowValue value={flow.individual} />} />
          <Stat label="외국인" value={<FlowValue value={flow.foreign} />} />
          <Stat label="기관" value={<FlowValue value={flow.institutional} />} />
        </div>
        <div className="border-divider flex items-center gap-2 border-t pt-3">
          <Kicker>기간별 수급 변화</Kicker>
          <Change value={flow.periodChangePct} display="arrow" />
        </div>
      </Card>
    </section>
  );
}

function FlowValue({ value }: { value: number }) {
  return (
    <span className="flex items-baseline gap-0.5">
      <Change value={value} unit="price" size="base" />
      <span className="text-xs text-neutral-600">주</span>
    </span>
  );
}
