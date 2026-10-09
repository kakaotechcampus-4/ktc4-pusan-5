import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button, Empty, ErrorBox, Kicker, Skeleton, Tabs } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { LoginModal } from '@/features/auth/LoginModal';
import { ProfileBand, ProfileBandSkeleton } from './components/ProfileBand';
import { ScrapTab } from './components/ScrapTab';
import { WatchlistTab } from './components/WatchlistTab';
import { useMyScraps } from './useMyScraps';
import { useMyWatchlist } from './useMyWatchlist';

type MyPageTab = 'scraps' | 'watchlist';

const TABS: { value: MyPageTab; label: string }[] = [
  { value: 'scraps', label: 'AI 보고서 스크랩' },
  { value: 'watchlist', label: '관심 종목' },
];

function parseTab(value: string | null): MyPageTab {
  return value === 'watchlist' ? 'watchlist' : 'scraps';
}

function PageTitle() {
  return (
    <div className="flex flex-col gap-1">
      <Kicker>MY PAGE</Kicker>
      <h1 className="text-h1">마이페이지</h1>
    </div>
  );
}

export function MyPage() {
  const { status, user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [loginOpen, setLoginOpen] = useState(false);
  const tab = parseTab(searchParams.get('tab'));

  // 훅은 여기서 둘 다 부른다. 탭 컴포넌트 안에서 부르면 탭 전환 때 언마운트되어 상태가 사라진다.
  // enabled 는 해당 탭이 처음 열릴 때 로딩을 시작시키고, 이후에는 결과를 유지한다.
  const authenticated = status === 'authenticated';
  const scraps = useMyScraps(authenticated && tab === 'scraps');
  const watchlist = useMyWatchlist(authenticated && tab === 'watchlist');

  function changeTab(next: MyPageTab) {
    setSearchParams({ tab: next }, { replace: true });
  }

  if (status === 'loading') {
    return (
      <>
        <PageTitle />
        <ProfileBandSkeleton />
        <Skeleton className="h-10" />
        <Skeleton className="h-40" />
      </>
    );
  }

  if (status === 'unauthenticated') {
    return (
      <>
        <PageTitle />
        <Empty
          title="로그인하면 관심 종목과 스크랩한 AI 보고서를 모아 볼 수 있습니다"
          action={
            <Button variant="primary" onClick={() => setLoginOpen(true)}>
              로그인
            </Button>
          }
        />
        <LoginModal open={loginOpen} onClose={() => setLoginOpen(false)} />
      </>
    );
  }

  if (status === 'error' || !user) {
    return (
      <>
        <PageTitle />
        <ErrorBox
          title="로그인 상태를 확인하지 못했습니다"
          description="잠시 후 다시 시도해주세요"
          onRetry={() => window.location.reload()}
        />
      </>
    );
  }

  return (
    <>
      <PageTitle />
      <ProfileBand user={user} />
      <div className="flex flex-col gap-4">
        <Tabs tabs={TABS} value={tab} onChange={changeTab} />
        {tab === 'scraps' ? (
          <ScrapTab
            status={scraps.status}
            items={scraps.items}
            removedIds={scraps.removedIds}
            onToggleRemoved={scraps.toggleRemoved}
            onRetry={scraps.retry}
          />
        ) : (
          <WatchlistTab
            status={watchlist.status}
            watchlist={watchlist.watchlist}
            removedIds={watchlist.removedIds}
            onToggleRemoved={watchlist.toggleRemoved}
            onRetry={watchlist.retry}
          />
        )}
      </div>
    </>
  );
}
