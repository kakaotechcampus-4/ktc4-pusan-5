import { cleanup, fireEvent, render } from '@testing-library/react';
import { WatchlistToggleButton } from './WatchlistToggleButton';

afterEach(cleanup);

it('shows an empty star when the stock is not in the watchlist', () => {
  const { getByRole } = render(
    <WatchlistToggleButton watched={false} disabled={false} onToggle={() => {}} />,
  );
  const button = getByRole('button', { name: /관심 종목/ });
  expect(button.getAttribute('aria-pressed')).toBe('false');
  expect(button.textContent).toContain('☆');
});

it('shows a filled star when the stock is in the watchlist', () => {
  const { getByRole } = render(
    <WatchlistToggleButton watched disabled={false} onToggle={() => {}} />,
  );
  const button = getByRole('button', { name: /관심 종목/ });
  expect(button.getAttribute('aria-pressed')).toBe('true');
  expect(button.textContent).toContain('★');
});

it('calls onToggle when clicked and ignores clicks while disabled', () => {
  const onToggle = vi.fn();
  const { getByRole, rerender } = render(
    <WatchlistToggleButton watched={false} disabled={false} onToggle={onToggle} />,
  );
  fireEvent.click(getByRole('button'));
  expect(onToggle).toHaveBeenCalledTimes(1);

  rerender(<WatchlistToggleButton watched={false} disabled onToggle={onToggle} />);
  fireEvent.click(getByRole('button'));
  expect(onToggle).toHaveBeenCalledTimes(1);
});
