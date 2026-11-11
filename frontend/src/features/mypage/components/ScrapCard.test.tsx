import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { UnavailableScrap } from '../types';
import { ScrapCard } from './ScrapCard';

afterEach(cleanup);

const mockUnavailableScrap: UnavailableScrap = {
  scrapId: '13',
  reportId: 4,
  reportType: 'STOCK',
  available: false,
  stockCode: null,
  stockName: null,
  changePct: null,
  asOf: null,
  targetDate: null,
  headline: null,
  generatedAt: null,
  sources: [],
  scrappedAt: '2026-11-10T00:00:00Z',
};

describe('ScrapCard', () => {
  it('읽을 수 없는 보고서는 목록에서 빼지 않고 찾을 수 없음 안내를 카드 안에 보여준다', () => {
    render(
      <MemoryRouter>
        <ul>
          <ScrapCard scrap={mockUnavailableScrap} removed={false} onToggleRemoved={() => {}} />
        </ul>
      </MemoryRouter>,
    );

    expect(screen.getByText('보고서를 찾을 수 없습니다')).toBeTruthy();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('읽을 수 없는 보고서도 스크랩을 해제할 수 있다', () => {
    const onToggleRemoved = vi.fn();
    render(
      <MemoryRouter>
        <ul>
          <ScrapCard
            scrap={mockUnavailableScrap}
            removed={false}
            onToggleRemoved={onToggleRemoved}
          />
        </ul>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: '스크랩 해제' }));
    expect(onToggleRemoved).toHaveBeenCalledWith('13');
  });
});
