import { useParams } from 'react-router-dom';
import { ConceptDetail } from './ConceptDetail';

/** 라우트에서 slug 만 추출, 렌더링은 ConceptDetail */
export function ConceptPage() {
  const { slug } = useParams();
  return <ConceptDetail slug={slug} />;
}
