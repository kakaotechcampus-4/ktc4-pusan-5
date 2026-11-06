#!/usr/bin/env bash
# 서버에서 하는 배포 전체. 워크플로가 git fetch/reset 으로 코드를 맞춘 뒤 호출한다.
#   사용: bash scripts/deploy.sh <배포할 커밋 전체 SHA> <reset 전 서버 HEAD>
#
# 순서: 백업 → 빌드 → 수집기 정지 → 핵심 서비스 기동(healthy 까지 대기) → 수집기 기동 → 이전 이미지 정리
#   기동에 성공하면 "후보" 기록(SHA + DB 마이그레이션 버전)만 남긴다. "마지막 성공"은 그대로다.
#   외부 smoke test 까지 통과하면 워크플로가 scripts/promote.sh 로 후보를 "마지막 성공"으로 올린다.
#   기동에 실패하면:
#     - DB 마이그레이션 버전이 마지막 성공 때와 같으면 마지막 성공 SHA 로 자동 롤백한다.
#     - 다르면(마이그레이션이 적용됨) 옛 코드가 시작하지 못하므로 자동으로 하지 않고 rollback.sh 를 안내한다.
#   롤백으로 사이트가 살아나도 이번 배포는 실패이므로 exit 1 로 끝낸다.
#
# 이 파일은 git reset 으로 실행 중에 다른 버전으로 바뀔 수 있다. bash 는 파일을 읽으며 실행하므로
# 전체를 함수로 감싸 한 번에 읽히게 하고, 마지막 줄도 한 줄로 끝낸다.
set -uo pipefail
. "$(dirname "$0")/deploy-lib.sh"

main() {
  local sha="${1:?배포할 SHA 가 필요합니다}" head_before="${2:-unknown}"
  read_state
  echo "deploy: 대상 ${sha:0:7} / 마지막 성공 ${LAST_SHA:0:7} (DB ${LAST_REV:-기록 없음})"

  # 이전 배포가 승격되지 못하고 남긴 후보는 이번 배포와 상관없으니 지운다.
  rm -f "$CANDIDATE_FILE"

  # 백업이 실패하면 아무것도 바꾸지 않고 멈춘다.
  if ! bash scripts/backup-db.sh "${LAST_SHA:-$head_before}"; then
    echo "deploy: 백업 실패. 배포를 중단합니다." >&2
    return 1
  fi

  local rc=0
  deploy_core || rc=$?

  if [ "$rc" -eq 0 ]; then
    local rev
    rev="$(db_revision)"
    if [ -z "$rev" ]; then
      echo "deploy: 경고 - DB 버전을 읽지 못해 마지막 성공 기록에 버전이 비었습니다. 다음 배포의 자동 롤백이 동작하지 않습니다." >&2
    fi
    write_candidate "$sha" "$rev"
    start_collector
    prune_docker
    echo "deploy: 기동 성공. smoke test 통과 후 promote.sh 로 마지막 성공을 갱신합니다."
    return 0
  fi

  if [ "$rc" -eq 2 ]; then
    echo "deploy: 빌드 실패. 실행 중인 컨테이너(수집기 포함)는 바뀌지 않았습니다." >&2
    return 1
  fi

  echo "deploy: 기동 실패." >&2
  auto_rollback && echo "deploy: 롤백으로 사이트는 살아났지만 이번 배포는 실패입니다." >&2
  return 1
}

main "$@"; exit $?
