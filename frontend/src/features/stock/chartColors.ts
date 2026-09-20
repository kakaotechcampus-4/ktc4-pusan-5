/**
 * lightweight-charts는 캔버스 렌더링이라 Tailwind 클래스를 못 받는다.
 * 그렇다고 차트 파일에 hex를 박으면 DESIGN.md 임의값 금지 규칙과 부딪힌다.
 * theme.css의 CSS 커스텀 프로퍼티를 런타임에 읽어써서, 색의 진실은 여전히 theme.css에 둔다.
 * 이 프로젝트의 lightweight-charts 컴포넌트(PriceVolumeChart)가 공유한다.
 */
export function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}
