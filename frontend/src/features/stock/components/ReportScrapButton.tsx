import { Button } from '@/components/ui';
import type { ReportScrapState } from '../useReportScrap';

/** AI 보고서 머리줄의 스크랩 토글. 상태는 바깥에서 받는다. */
export function ReportScrapButton({ scrap }: { scrap: ReportScrapState }) {
  return (
    <Button
      variant="secondary"
      aria-pressed={scrap.scrapped}
      disabled={!scrap.ready || scrap.pending}
      onClick={scrap.toggle}
    >
      <span aria-hidden="true">{scrap.scrapped ? '★' : '☆'}</span>
      {scrap.scrapped ? '스크랩됨' : '스크랩'}
    </Button>
  );
}
