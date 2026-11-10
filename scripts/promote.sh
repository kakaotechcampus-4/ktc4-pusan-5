#!/usr/bin/env bash
# 외부 smoke test 를 통과한 배포를 "마지막 성공"으로 확정한다. 서버에서 ubuntu 사용자로, 저장소 루트에서 실행한다.
#   사용: bash scripts/promote.sh <배포한 커밋 전체 SHA>
#
# deploy.sh 가 남긴 후보(SHA + DB 마이그레이션 버전)의 SHA 가 인자와 같을 때만 승격한다.
# smoke test 가 실패하면 이 스크립트를 부르지 않으므로 "마지막 성공"은 이전 값으로 남는다.
#
# deploy.sh 와 같은 이유로 전체를 함수로 감싼다(git reset 이 이 파일을 바꿀 수 있다).
set -uo pipefail
. "$(dirname "$0")/deploy-lib.sh"

main() {
  local sha="${1:?승격할 SHA 가 필요합니다}"
  if promote_candidate "$sha"; then
    echo "promote: 마지막 성공 -> ${sha:0:7}"
    return 0
  fi
  return 1
}

main "$@"; exit $?
