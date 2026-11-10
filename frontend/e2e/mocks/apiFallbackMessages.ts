/**
 * 서버 메시지를 쓸 수 없을 때 src/lib/api.ts 가 대신 넣는 ApiError.message.
 * mockReply.malformed·networkError 를 넣었을 때 화면에 나올 문구라 목업 응답 옆에 둔다.
 * api.ts 의 문구가 바뀌면 여기만 고친다.
 */
export const apiFallbackMessages = {
  /** 응답을 받지 못함 (NETWORK_ERROR) */
  networkError: '서버에 연결하지 못했습니다',
  /** 오류 응답인데 본문이 고정 에러 형태가 아님 (INVALID_RESPONSE) */
  unreadableErrorBody: '요청을 처리하지 못했습니다',
  /** 정상 응답인데 본문을 JSON 으로 읽지 못함 (INVALID_RESPONSE) */
  unparsableBody: '응답을 해석하지 못했습니다',
} as const;
