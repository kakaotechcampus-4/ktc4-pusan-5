import { Link } from 'react-router-dom';
import { Card, Change, Empty, ErrorBox, Skeleton, SkeletonText, Tag } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatAsOf } from '@/lib/format';
import type { ReportListItem } from '@/lib/types';
import { VERDICT_LABEL } from '@/features/stock/components/reportLabels';
import { REPORT_HASH } from '@/features/stock/components/StockInsightSection';
import type { LatestReportsStatus } from '../useLatestReports';

const GRID_CLASS = 'grid list-none grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3';

/**
 * 종목별 최신 AI 보고서 목록. 카드를 누르면 그 종목의 상세(AI 보고서 탭)로 간다.
 * 카드 전체가 종목 이름 Link 하나의 stretched link 다.
 */
export function LatestReportsSection({
  status,
  items,
  onRetry,
}: {
  status: LatestReportsStatus;
  items: ReportListItem[];
  onRetry: () => void;
}) {
  return (
    <section className="flex flex-col gap-3">
      <SectionHead title="최신 AI 보고서" right={<Tag tone="ai">AI 생성</Tag>} />

      {status === 'loading' && (
        <ul className={GRID_CLASS} aria-busy>
          {Array.from({ length: 3 }).map((_, i) => (
            <li key={i} className="grid">
              <Card tone="plain">
                <Skeleton className="h-5 w-32" />
                <SkeletonText lines={2} />
              </Card>
            </li>
          ))}
        </ul>
      )}

      {status === 'error' && (
        <ErrorBox
          title="AI 보고서를 불러오지 못했습니다"
          description="잠시 후 다시 시도해주세요"
          onRetry={onRetry}
        />
      )}

      {status === 'success' && items.length === 0 && (
        <Empty
          title="아직 올라온 AI 보고서가 없습니다"
          description="장 마감 후 종목별 보고서가 만들어집니다"
        />
      )}

      {status === 'success' && items.length > 0 && (
        <ul className={GRID_CLASS}>
          {items.map((item) => (
            <li key={item.id} className="relative grid">
              <Card tone="plain">
                <div className="flex items-center gap-2">
                  <Link
                    to={`/stock/${item.code}${REPORT_HASH}`}
                    className="text-ink min-w-0 truncate font-semibold no-underline after:absolute after:inset-0"
                  >
                    {item.name ?? item.code}
                  </Link>
                  {item.changePct !== null && (
                    <span className="ml-auto flex-none">
                      <Change value={item.changePct} display="arrow" />
                    </span>
                  )}
                </div>
                <div>
                  <Tag tone={item.verdict === 'explained' ? 'brand' : 'neutral'}>
                    {VERDICT_LABEL[item.verdict]}
                  </Tag>
                </div>
                {item.headline && (
                  <p className="flex-1 text-sm text-neutral-700">{item.headline}</p>
                )}
                <p className="text-xs text-neutral-600">
                  {formatAsOf(new Date(item.asOf), '보고서 기준')}
                </p>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
