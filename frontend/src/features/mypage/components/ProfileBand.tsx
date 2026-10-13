import { Card, Skeleton, StockAvatar, Tag } from '@/components/ui';
import type { User } from '@/lib/types';

export function ProfileBand({ user }: { user: User }) {
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3">
        <StockAvatar initial={user.nickname.slice(0, 1)} />
        <span className="min-w-0 truncate text-base font-semibold">{user.nickname}</span>
        <div className="ml-auto">
          <Tag tone="neutral">카카오 계정으로 로그인</Tag>
        </div>
      </div>
    </Card>
  );
}

/** 실제 띠와 같은 높이: 아바타 32px 한 줄 */
export function ProfileBandSkeleton() {
  return (
    <Card>
      <div className="flex items-center gap-3">
        <Skeleton className="size-8 flex-none" />
        <Skeleton className="h-6 w-32" />
      </div>
    </Card>
  );
}
