/** GET /api/watchlist 목업. 로그인한 사용자의 관심 종목 */
import type { WatchlistResponse } from '../../src/lib/types';
import { mergeDeep, type DeepPartial } from './deepMerge';
import { mockAsOf, mockPrimaryStock } from './sharedMocks';

export function mockWatchlist(overrides?: DeepPartial<WatchlistResponse>): WatchlistResponse {
  return mergeDeep<WatchlistResponse>(
    {
      items: [
        {
          code: mockPrimaryStock.code,
          name: mockPrimaryStock.name,
          market: mockPrimaryStock.market,
          quote: { price: 62400, change: -1.08, changeAmount: -680 },
          quoteStatus: 'ready',
          asOf: mockAsOf,
        },
      ],
    },
    overrides,
  );
}
