import { useEffect, useState } from 'react';
import { getStockOverview, getStockReport } from '@/lib/api';
import type { StockReport } from '@/lib/types';

/**
 * 홈의 개별 종목 시그널.
 *
 * 판단: 시그널 종목을 고르는 API 가 아직 없어서 종목 다섯 개를 고정한다.
 * 시세는 종목 상세와 같은 /overview, 한 줄 요약은 같은 종목의 변동 요인 보고서에서 가져온다.
 * 보고서가 아직 없으면 summary 가 null 이고, 화면은 "준비 중"으로 보여준다.
 */
const SIGNAL_STOCKS = [
  { code: '032830', name: '삼성생명', initial: '생' },
  { code: '000660', name: 'SK하이닉스', initial: 'SK' },
  { code: '005930', name: '삼성전자', initial: '삼' },
  { code: '373220', name: 'LG에너지솔루션', initial: 'LG' },
  { code: '009150', name: '삼성전기', initial: '전' },
] as const;

export type HomeSignal = {
  code: string;
  name: string;
  /** 로고 배지에 넣는 이니셜. 백엔드가 주는 값이 아니라 프론트에서 정한다. */
  initial: string;
  /** 시세를 받지 못하면 null */
  price: number | null;
  /** 등락률(%). 시세를 받지 못하면 null */
  change: number | null;
  /** 왜 움직였는지 한 줄. LLM 생성물이다. 보고서가 없으면 null */
  summary: string | null;
};

export type SignalBoard = {
  signals: HomeSignal[];
  /** 한 줄 요약이 하나라도 있을 때, 그중 가장 최근 생성 시각 */
  generatedAt: string | null;
  /** 한 줄 요약에 쓰인 보고서들의 출처 채널 */
  sources: string[];
};

export type SignalBoardStatus = 'loading' | 'error' | 'success';

/** 백엔드 최신 보고서 목록의 headline 과 같은 규칙: 핵심 원인, 없으면 등락 설명 */
function headline(report: StockReport): string | null {
  return report.summary.mainCause || report.summary.move || null;
}

function sourceChannels(report: StockReport): string[] {
  return report.factors.flatMap((factor) =>
    factor.sources.flatMap((source) => (source.channel ? [source.channel] : [])),
  );
}

async function loadSignalBoard(signal: AbortSignal): Promise<SignalBoard> {
  const rows = await Promise.all(
    SIGNAL_STOCKS.map(async (stock) => {
      const [overview, report] = await Promise.allSettled([
        getStockOverview(stock.code, signal),
        getStockReport(stock.code, signal),
      ]);
      const quote = overview.status === 'fulfilled' ? overview.value.quote.data : null;
      const ready = report.status === 'fulfilled' && report.value.data ? report.value.data : null;
      return { stock, quote, report: ready, failed: overview.status === 'rejected' };
    }),
  );

  // 다섯 종목 모두 시세 요청이 실패했으면 섹션 전체를 에러로 본다.
  if (rows.every((row) => row.failed)) throw new Error('signal board unavailable');

  const signals: HomeSignal[] = rows.map(({ stock, quote, report }) => ({
    ...stock,
    price: quote?.price ?? null,
    change: quote?.change ?? null,
    summary: report ? headline(report) : null,
  }));

  const reports = rows.flatMap((row) => (row.report && headline(row.report) ? [row.report] : []));
  const generatedAt =
    reports
      .map((report) => report.generatedAt)
      .filter((value): value is string => value !== null)
      .sort()
      .at(-1) ?? null;
  const sources = [...new Set(reports.flatMap(sourceChannels))];

  return { signals, generatedAt, sources };
}

export function useSignalBoard() {
  const [status, setStatus] = useState<SignalBoardStatus>('loading');
  const [board, setBoard] = useState<SignalBoard | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    loadSignalBoard(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setBoard(result);
        setStatus('success');
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setStatus('error');
      });
    return () => controller.abort();
  }, [attempt]);

  function retry() {
    setStatus('loading');
    setAttempt((n) => n + 1);
  }

  return { status, board, retry };
}
