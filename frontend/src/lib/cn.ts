/** 조건부 className 합치기. 외부 의존성 없음. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}
