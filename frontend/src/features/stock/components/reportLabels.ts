import type { ReportLayer, ReportStance, ReportStrength, ReportVerdict } from '@/lib/types';

/** 판정 문구. 매수·매도 같은 투자의견으로 읽히지 않게 "원인이 확인됐는가"만 말한다. */
export const VERDICT_LABEL: Record<ReportVerdict, string> = {
  explained: '원인 확인됨',
  partially_explained: '일부만 확인됨',
  no_clear_cause: '뚜렷한 원인 확인 안 됨',
};

/** 등락 색(빨강·파랑)과 섞이지 않게 방향이 아니라 "주가에 미친 영향"으로 적는다. */
export const STANCE_LABEL: Record<ReportStance, string> = {
  bullish: '주가에 긍정적',
  bearish: '주가에 부정적',
  neutral: '영향 중립',
};

export const LAYER_LABEL: Record<ReportLayer, string> = {
  move: '이 종목의 등락',
  relative: '시장·동종 대비',
};

export const STRENGTH_LABEL: Record<ReportStrength, string> = {
  sufficient: '근거 충분',
  partial: '근거 일부',
  insufficient: '근거 부족',
};

/** LLM 이 적재한 URL 이므로 http(s) 만 링크로 만든다. */
export function toSafeUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}
