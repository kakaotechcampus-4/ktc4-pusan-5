import { Card, CardBody, CardTitle } from '@/components/ui';
import { GuardrailNote } from '@/components/layout/GuardrailNote';

export function ConceptChatPanel() {
  return (
    <Card tone="plain">
      <GuardrailNote />
      <CardTitle>모르는 개념 물어보기</CardTitle>
      <CardBody>챗 패널이 들어갈 자리입니다.</CardBody>
    </Card>
  );
}
