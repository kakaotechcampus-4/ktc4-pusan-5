import { cleanup, fireEvent, render as baseRender, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import type { Resource, StockReport } from '@/lib/types';
import { AiReportSection } from './AiReportSection';
import type { ReportScrapState } from '../useReportScrap';

afterEach(cleanup);

// 용어 풀이가 개념 페이지로 가는 Link 를 쓰므로 라우터 안에서 그린다.
function render(ui: ReactElement) {
  const wrap = (node: ReactElement) => <MemoryRouter>{node}</MemoryRouter>;
  const result = baseRender(wrap(ui));
  return { ...result, rerender: (next: ReactElement) => result.rerender(wrap(next)) };
}

const scrapState: ReportScrapState = {
  scrapped: false,
  ready: true,
  pending: false,
  toggle: async () => {},
};

const mockReport: StockReport = {
  id: 1,
  code: '005930',
  name: '삼성전자',
  asOf: '2026-11-09T06:30:00Z',
  changePct: -1.08,
  generatedAt: '2026-11-09T07:00:00Z',
  verdict: 'explained',
  relativeVerdict: 'partially_explained',
  summary: {
    move: 'mock 장 마감 기준 1.08% 내렸습니다.',
    mainCause: 'mock 주된 원인',
    relative: null,
    counter: null,
    unexplained: 'mock 설명되지 않은 부분',
  },
  factors: [
    {
      event: 'mock 사건',
      detail: '',
      stance: 'bearish',
      unconfirmed: false,
      links: [
        { layer: 'move', note: 'mock 방향 일치', directionMatch: true, strength: 'sufficient' },
      ],
      sources: [
        {
          channel: 'mock_channel',
          url: 'https://t.me/mock/1',
          datetimeKst: null,
          match: 'direct',
          isMarketRecap: false,
        },
        {
          channel: 'mock_unsafe',
          url: 'javascript:alert(1)',
          datetimeKst: null,
          match: null,
          isMarketRecap: null,
        },
      ],
    },
  ],
  terms: [
    { term: 'mock용어', plain: 'mock 풀이', conceptSlug: 'mock-slug' },
    { term: 'mock없는용어', plain: 'mock 풀이2', conceptSlug: null },
  ],
  background: {
    bullish: [],
    bearish: [],
    neutral: [{ text: 'mock 배경', sources: [], watch: true }],
  },
};

function resource(overrides: Partial<Resource<StockReport>>): Resource<StockReport> {
  return {
    status: 'ready',
    refreshing: false,
    data: mockReport,
    sourceAsOf: mockReport.asOf,
    collectedAt: null,
    retryAfterSeconds: null,
    ...overrides,
  };
}

const noop = () => {};

it('always shows the guardrail note, even while loading', () => {
  render(<AiReportSection resource={null} error={null} onRetry={noop} scrap={scrapState} />);
  expect(screen.getByText(/매수·매도 판단은 하지 않습니다/)).toBeTruthy();
});

it('shows the empty state when the report is not generated yet', () => {
  render(
    <AiReportSection
      resource={resource({ status: 'pending', data: null })}
      error={null}
      onRetry={noop}
      scrap={scrapState}
    />,
  );
  expect(screen.getByText('아직 보고서가 준비되지 않았습니다')).toBeTruthy();
});

it('shows the error box for a failed request and for an unavailable report', () => {
  const { rerender } = render(
    <AiReportSection
      resource={null}
      error={new Error('network')}
      onRetry={noop}
      scrap={scrapState}
    />,
  );
  expect(screen.getByText('보고서를 불러오지 못했습니다')).toBeTruthy();
  rerender(
    <AiReportSection
      resource={resource({ status: 'unavailable', data: null })}
      error={null}
      onRetry={noop}
      scrap={scrapState}
    />,
  );
  expect(screen.getByText('보고서를 불러오지 못했습니다')).toBeTruthy();
});

it('marks the report as AI generated and shows the as-of and generated times', () => {
  render(
    <AiReportSection resource={resource({})} error={null} onRetry={noop} scrap={scrapState} />,
  );
  expect(screen.getByText('AI 생성')).toBeTruthy();
  expect(screen.getByText(/2026\. 11\. 09 \(월\) · 보고서 기준/)).toBeTruthy();
  expect(screen.getByText(/2026\. 11\. 09 \(월\) 생성/)).toBeTruthy();
});

it('renders summary, factor, term and background content', () => {
  render(
    <AiReportSection resource={resource({})} error={null} onRetry={noop} scrap={scrapState} />,
  );
  expect(screen.getByText('원인 확인됨')).toBeTruthy();
  expect(screen.getByText('mock 장 마감 기준 1.08% 내렸습니다.')).toBeTruthy();
  expect(screen.getByText('mock 사건')).toBeTruthy();
  expect(screen.getByText('mock용어')).toBeTruthy();
  expect(screen.getByText(/mock 배경/)).toBeTruthy();
});

it('links only http(s) sources and shows other sources as plain text', () => {
  render(
    <AiReportSection resource={resource({})} error={null} onRetry={noop} scrap={scrapState} />,
  );
  const link = screen.getByRole('link', { name: 'mock_channel' });
  expect(link.getAttribute('href')).toBe('https://t.me/mock/1');
  expect(link.getAttribute('rel')).toContain('noopener');
  expect(screen.queryByRole('link', { name: 'mock_unsafe' })).toBeNull();
  expect(screen.getByText('mock_unsafe')).toBeTruthy();
});

it('links a term to its concept page only when a concept exists', () => {
  render(
    <AiReportSection resource={resource({})} error={null} onRetry={noop} scrap={scrapState} />,
  );
  expect(screen.getByRole('link', { name: 'mock용어' }).getAttribute('href')).toBe(
    '/concepts/mock-slug',
  );
  expect(screen.queryByRole('link', { name: 'mock없는용어' })).toBeNull();
  expect(screen.getByText('mock없는용어')).toBeTruthy();
});

it('shows the scrap button state and calls toggle when pressed', () => {
  let toggled = 0;
  const state: ReportScrapState = {
    ...scrapState,
    scrapped: true,
    toggle: async () => {
      toggled += 1;
    },
  };
  render(<AiReportSection resource={resource({})} error={null} onRetry={noop} scrap={state} />);
  const button = screen.getByRole('button', { name: /스크랩됨/ });
  expect(button.getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(button);
  expect(toggled).toBe(1);
});

it('disables the scrap button until its state is known', () => {
  const state: ReportScrapState = { ...scrapState, ready: false };
  render(<AiReportSection resource={resource({})} error={null} onRetry={noop} scrap={state} />);
  expect((screen.getByRole('button', { name: /스크랩/ }) as HTMLButtonElement).disabled).toBe(true);
});
