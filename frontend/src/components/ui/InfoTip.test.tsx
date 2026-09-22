import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { InfoTip } from './InfoTip';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it('renders hover help outside a clipping table and closes after leaving', () => {
  vi.useFakeTimers();
  const { container } = render(
    <div className="overflow-x-auto">
      <InfoTip description="결산연월 설명" />
    </div>,
  );
  const trigger = screen.getByRole('button', { name: '개념 설명' });
  fireEvent.mouseEnter(trigger);
  const tooltip = screen.getByRole('tooltip');
  expect(tooltip.textContent).toBe('결산연월 설명');
  expect(tooltip.parentElement).toBe(document.body);
  expect(container.contains(tooltip)).toBe(false);
  expect(trigger.getAttribute('aria-describedby')).toBe(tooltip.id);
  fireEvent.mouseLeave(trigger);
  fireEvent.mouseEnter(tooltip);
  act(() => vi.advanceTimersByTime(150));
  expect(screen.getByRole('tooltip')).toBeTruthy();
  fireEvent.mouseLeave(tooltip);
  act(() => vi.advanceTimersByTime(150));
  expect(screen.queryByRole('tooltip')).toBeNull();
});

it('opens on keyboard focus and dismisses with Escape', () => {
  render(<InfoTip description="거래대금 설명" />);
  const trigger = screen.getByRole('button', { name: '개념 설명' });
  fireEvent.focus(trigger);
  expect(screen.getByRole('tooltip').textContent).toBe('거래대금 설명');
  fireEvent.keyDown(trigger, { key: 'Escape' });
  expect(screen.queryByRole('tooltip')).toBeNull();
  expect(trigger.getAttribute('aria-describedby')).toBeNull();
});
