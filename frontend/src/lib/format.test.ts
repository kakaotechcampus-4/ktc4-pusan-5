import { formatMarketValue } from './format';

describe('formatMarketValue', () => {
  it('shows gold as a whole-number won per gram price', () => {
    expect(formatMarketValue(182770, 'KRW/g')).toBe('182,770원/g');
  });

  it('keeps two decimals for the exchange rate and index points', () => {
    expect(formatMarketValue(1344.2, 'KRW/USD')).toBe('1,344.20원');
    expect(formatMarketValue(7003.74, 'points')).toBe('7,003.74');
  });
});
