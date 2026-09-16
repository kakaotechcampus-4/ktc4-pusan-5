import { Card, Change, InfoTip, Kicker } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatPrice, formatRatio } from '@/lib/format';
import type { MarginBalance, ShortSelling } from '../mock';

/** 공매도와 신용잔고 둘 다 추이 차트 없이 현재 수치 + 등락만 보여준다. */
export function ShortMarginSection({
  shortSelling,
  marginBalance,
}: {
  shortSelling: ShortSelling;
  marginBalance: MarginBalance;
}) {
  return (
    <section>
      <SectionHead title="공매도 · 신용잔고" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Card tone="plain">
          <div className="flex items-center gap-1">
            <Kicker>공매도 비중</Kicker>
            <InfoTip description="주식을 빌려 먼저 판 뒤 나중에 되사서 갚는 매매의 비중입니다. 주가 하락에 베팅하는 거래입니다." />
          </div>
          <div className="num text-h2 font-bold">{formatRatio(shortSelling.ratio, 2)}</div>
          <Change value={shortSelling.changePct} display="arrow" />
        </Card>
        <Card tone="plain">
          <div className="flex items-center gap-1">
            <Kicker>신용잔고</Kicker>
            <InfoTip description="투자자가 증권사에서 돈을 빌려 산(신용거래) 주식이 아직 갚지 않고 남아있는 수량입니다." />
          </div>
          <div className="num text-h2 font-bold">{formatPrice(marginBalance.quantity)}주</div>
          <Change value={marginBalance.changePct} display="arrow" />
        </Card>
      </div>
    </section>
  );
}
