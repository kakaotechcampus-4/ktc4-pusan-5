export const HOME_SEARCH_INPUT_ID = 'home-search-input';

/** 관심 종목 담기는 종목을 검색해서 고르는 데서 시작하므로, 홈 검색창으로 화면을 옮기고 포커스를 준다. */
export function focusHomeSearch() {
  const input = document.getElementById(HOME_SEARCH_INPUT_ID);
  if (!input) return;
  input.scrollIntoView({ behavior: 'smooth', block: 'center' });
  input.focus({ preventScroll: true });
}
