/**
 * 숫자·날짜 포맷은 전부 여기서만 한다.
 * 화면 코드에서 toFixed / toLocaleString 을 직접 부르지 않는다.
 */

export type Direction = 'up' | 'down' | 'flat';

/** 등락 방향. 0은 보합이며 상승도 하락도 아니다. */
export function direction(value: number): Direction {
  if (value > 0) return 'up';
  if (value < 0) return 'down';
  return 'flat';
}

/** 마이너스 기호는 하이픈(-)이 아니라 U+2212(−)를 쓴다. 자릿수가 흔들리지 않는다. */
const MINUS = '\u2212';

/** 주가·금액. 12345 → "12,345" */
export function formatPrice(value: number): string {
  const abs = Math.abs(value).toLocaleString('ko-KR');
  return value < 0 ? `${MINUS}${abs}` : abs;
}

/** 등락률. -1.084 → "−1.08%" (부호 방식) */
export function formatPct(value: number): string {
  const abs = Math.abs(value).toFixed(2);
  if (value > 0) return `+${abs}%`;
  if (value < 0) return `${MINUS}${abs}%`;
  return `${abs}%`;
}

/** 등락률. -1.084 → "▼ 1.08%" (화살표 방식) */
export function formatPctArrow(value: number): string {
  const abs = Math.abs(value).toFixed(2);
  if (value > 0) return `\u25B2 ${abs}%`;
  if (value < 0) return `\u25BC ${abs}%`;
  return `${abs}%`;
}

/** \uBC30\uC218 \uC9C0\uD45C(PER\u00B7PBR). 11.4 \u2192 "11.40\uBC30" */
export function formatMultiple(value: number): string {
  return `${value.toFixed(2)}\uBC30`;
}

/** \uB4F1\uB77D\uC774 \uC544\uB2CC \uBD80\uD638 \uC5C6\uB294 \uBE44\uC728(\uC678\uAD6D\uC778 \uBCF4\uC720\uC728, \uACF5\uB9E4\uB3C4 \uBE44\uC911 \uB4F1). 51.2 \u2192 "51.2%" */
export function formatRatio(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`;
}

/** 시가총액 등 큰 금액. 12430000000000 → "12조 4,300억" (음수는 -410000000000 → "−4,100억") */
export function formatCompactKRW(value: number): string {
  const JO = 1_0000_0000_0000;
  const EOK = 1_0000_0000;
  const sign = value < 0 ? MINUS : '';
  const abs = Math.abs(value);
  if (abs >= JO) {
    const jo = Math.floor(abs / JO);
    const eok = Math.floor((abs % JO) / EOK);
    return eok > 0 ? `${sign}${jo}조 ${eok.toLocaleString('ko-KR')}억` : `${sign}${jo}조`;
  }
  if (abs >= EOK) {
    return `${sign}${Math.floor(abs / EOK).toLocaleString('ko-KR')}억`;
  }
  return formatPrice(value);
}

const WEEKDAY = ['일', '월', '화', '수', '목', '금', '토'];

/** "2026. 08. 21 (금)" */
export function formatDate(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}. ${mm}. ${dd} (${WEEKDAY[d.getDay()]})`;
}

/**
 * 시세·브리핑에 항상 붙이는 기준 시각 문구.
 * "2026. 08. 21 (금) · 장 마감 기준"
 */
export function formatAsOf(d: Date, note = '장 마감 기준'): string {
  return `${formatDate(d)} · ${note}`;
}

export function formatCollectedAt(value: string): string {
  return `${formatDate(new Date(value))} 수집 시각`;
}

/** 원천 기준일은 시간대 변환 없이 표시한다. */
export function formatMarketDate(value: string): string {
  return value.replaceAll('-', '. ');
}

export function formatFiscalPeriod(value: string): string {
  return value.replace('-', '.');
}

export function formatMarketValue(value: number, unit: string | null): string {
  const formatted = value.toLocaleString('ko-KR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return unit === 'KRW/USD' ? `${formatted}원` : formatted;
}
