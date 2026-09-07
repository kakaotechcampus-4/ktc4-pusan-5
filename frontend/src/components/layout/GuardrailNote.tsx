/** AI 브리핑·챗봇 영역 상단에 항상 노출한다. 조건부로 숨기지 않는다. */
export function GuardrailNote({ on = true }: { on?: boolean }) {
  return (
    <div className="text-xs leading-relaxed text-neutral-600">
      {on
        ? '초보 가드레일 ON · 매수·매도 판단은 하지 않습니다'
        : '가드레일 OFF · 개념 설명 모드'}
    </div>
  );
}
