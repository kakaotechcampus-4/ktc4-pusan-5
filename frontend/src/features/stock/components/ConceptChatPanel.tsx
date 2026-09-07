import { useState, type FormEvent } from 'react';
import { Button, Card, CardBody, CardTitle, Input } from '@/components/ui';
import { GuardrailNote } from '@/components/layout/GuardrailNote';

export function ConceptChatPanel() {
  const [message, setMessage] = useState('');

  // 판단: 챗 백엔드가 아직 없어서 전송은 입력창을 비우는 것까지만 한다.
  // 실제 연동 시 이 자리에 API 호출을 넣는다.
  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!message.trim()) return;
    setMessage('');
  }

  return (
    <Card tone="plain">
      <GuardrailNote />
      <CardTitle>모르는 개념 물어보기</CardTitle>
      <CardBody>챗 패널이 들어갈 자리입니다.</CardBody>
      <form onSubmit={handleSubmit} className="flex gap-2">
        <Input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="예: PER이 뭐예요?"
          aria-label="개념 질문 입력"
        />
        <Button type="submit" variant="primary">
          전송
        </Button>
      </form>
    </Card>
  );
}
