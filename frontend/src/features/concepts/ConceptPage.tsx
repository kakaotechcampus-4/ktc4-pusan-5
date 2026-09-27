import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui';
import { ConceptDetail } from './ConceptDetail';

/** 라우트에서 slug 만 추출, 렌더링은 ConceptDetail */
export function ConceptPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  // key 가 'default' 면 앱 안에 이전 기록이 없는 첫 진입(공유 링크·새 탭)
  const hasHistory = location.key !== 'default';

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Button
          variant="ghost"
          onClick={() => (hasHistory ? navigate(-1) : navigate('/concepts'))}
        >
          {hasHistory ? '← 이전으로' : '← 개념 목록'}
        </Button>
      </div>
      <ConceptDetail slug={slug} />
    </div>
  );
}
