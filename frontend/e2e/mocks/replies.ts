/**
 * 목업이 돌려줄 응답의 종류. 정상 응답·고정 에러 형태·깨진 본문·네트워크 오류.
 * 실제 전송은 fixtures/apiMock.ts 가 한다. 여기는 "무엇을 돌려줄지"만 정한다.
 *
 * 에러 형태는 루트 CLAUDE.md 의 API 규약을 따른다.
 *   { "error": { "code": "STOCK_NOT_FOUND", "message": "..." } }
 */
import type { ApiErrorBody } from '../../src/lib/types';

/** TResponse 는 정상 응답 본문의 타입. 에러·깨진 본문·네트워크 오류는 어느 엔드포인트에나 넣을 수 있다 */
export type MockReply<TResponse> =
  | { readonly kind: 'json'; readonly status: number; readonly body: TResponse }
  | { readonly kind: 'apiError'; readonly status: number; readonly body: ApiErrorBody }
  | { readonly kind: 'malformed'; readonly status: number }
  | { readonly kind: 'networkError' };

export type MockApiFailure = {
  readonly status: number;
  readonly body: ApiErrorBody;
};

/** JSON 으로 읽을 수 없는 본문. mockReply.malformed 가 보낸다 */
export const mockMalformedBody = '{"error": {"code": "BROKEN';

function mockFailure(status: number, code: string, message: string): MockApiFailure {
  return { status, body: { error: { code, message } } };
}

/**
 * 백엔드가 실제로 내는 코드에 맞춘 고정 에러 형태 (backend/app 의 AppError).
 * message 는 "목업"을 넣어 화면 고정 문구와 구별되게 한다. 그래야 화면이 서버 메시지를 썼는지
 * 고정 문구를 썼는지 단언으로 가를 수 있다.
 */
export const mockApiErrors = {
  internal: (message = '목업 서버 오류입니다. 잠시 후 다시 시도해주세요') =>
    mockFailure(500, 'INTERNAL_SERVER_ERROR', message),
  unauthorized: () => mockFailure(401, 'UNAUTHORIZED', '로그인이 필요합니다'),
  kakaoAuthFailed: () => mockFailure(401, 'KAKAO_AUTH_FAILED', '목업: 카카오 로그인에 실패했습니다'),
  stockNotFound: () => mockFailure(404, 'STOCK_NOT_FOUND', '목업: 등록되지 않은 종목입니다.'),
  conceptNotFound: () => mockFailure(404, 'CONCEPT_NOT_FOUND', '목업: 개념이 없습니다'),
  /** 목업 목록에 없는 요청을 막을 때 쓴다. 실제 백엔드에는 없는 코드다 */
  unmocked: (request: string) =>
    mockFailure(501, 'E2E_UNMOCKED_REQUEST', `목업되지 않은 요청입니다: ${request}`),
};

export const mockReply = {
  /**
   * 정상 응답. 본문 타입은 인자가 아니라 넣을 자리(api.reply 의 엔드포인트)에서 정해진다.
   * 그래서 api.reply(apiEndpoints.authMe, mockReply.ok({ ...오타 키 })) 도 컴파일 에러가 난다.
   * 자리 없이 변수에 먼저 담으면 검사가 빠지므로 바로 api.reply·hold 인자로 넣는다.
   */
  ok: <TResponse>(body: NoInfer<TResponse>, status = 200): MockReply<TResponse> => ({
    kind: 'json',
    status,
    body,
  }),
  apiError: (failure: MockApiFailure): MockReply<never> => ({
    kind: 'apiError',
    status: failure.status,
    body: failure.body,
  }),
  /** JSON 으로 읽을 수 없는 본문. 응답 코드는 정상(200)·실패(500) 어느 쪽이든 줄 수 있다 */
  malformed: (status: number): MockReply<never> => ({ kind: 'malformed', status }),
  /** 응답 없이 연결이 끊긴 경우 (route.abort) */
  networkError: (): MockReply<never> => ({ kind: 'networkError' }),
};
