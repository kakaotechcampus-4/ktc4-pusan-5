#!/usr/bin/env bash
# 외부 smoke test 가 실패했을 때 워크플로가 부른다. 서버에서 ubuntu 사용자로, 저장소 루트에서 실행한다.
#   사용: bash scripts/auto-rollback.sh <배포한 커밋 전체 SHA> <확인할 기준 주소(예: https://example.com)>
#
# smoke 는 GitHub 러너가 밖에서 확인하므로 러너 쪽 네트워크 문제로도 실패할 수 있다.
# 그래서 롤백 전에 서버가 같은 주소를 직접 한 번 더 확인한다.
#   - 서버에서도 실패하면 새 버전 문제로 보고 deploy-lib.sh 의 auto_rollback 으로 되돌린다
#     (DB 마이그레이션 버전이 마지막 성공 때와 같을 때만. 다르면 rollback.sh 를 안내한다).
#   - 서버에서는 정상이면 DNS·보안 그룹 같은 외부 접근 문제다. 코드를 되돌려도 고쳐지지 않으므로 롤백하지 않는다.
# 어느 쪽이든 후보 기록은 지운다(smoke 를 통과하지 못한 배포라 승격하지 않는다).
#
# deploy.sh 와 같은 이유로 전체를 함수로 감싼다(git reset 이 이 파일을 바꿀 수 있다).
set -uo pipefail
. "$(dirname "$0")/deploy-lib.sh"

# 배포 직후 잠깐 불안정할 수 있어 몇 번 재시도한다. 한 주소라도 끝까지 200 이 아니면 실패.
server_check() {
  local url code i
  for url in "$1/health" "$1/api/concepts"; do
    code=000
    for i in 1 2 3 4 5 6; do
      code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url" || echo 000)
      echo "server-check [$i] $url -> $code"
      [ "$code" = "200" ] && break
      sleep 5
    done
    [ "$code" = "200" ] || return 1
  done
}

main() {
  local sha="${1:?배포한 SHA 가 필요합니다}" base="${2:?확인할 기준 주소가 필요합니다}"
  base="${base%/}"
  rm -f "$CANDIDATE_FILE"

  if server_check "$base"; then
    echo "auto-rollback: 서버에서는 정상입니다. 외부 접근 문제(DNS·보안 그룹·러너 네트워크)로 보여 롤백하지 않습니다." >&2
    echo "auto-rollback: 이번 배포는 smoke 를 통과하지 못해 마지막 성공으로 확정하지 않았습니다." >&2
    return 0
  fi

  echo "auto-rollback: 서버에서도 ${base} 가 정상이 아닙니다. 새 버전 문제로 보고 롤백을 시도합니다." >&2
  read_state
  if [ "$LAST_SHA" = "$sha" ]; then
    echo "auto-rollback: 마지막 성공이 이번 배포(${sha:0:7})와 같아 되돌릴 이전 버전이 없습니다." >&2
    return 1
  fi
  auto_rollback
}

main "$@"; exit $?
