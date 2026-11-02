#!/usr/bin/env bash
# 서버에서 하는 배포 전체. 워크플로가 git fetch/reset 으로 코드를 맞춘 뒤 호출한다.
#   사용: bash scripts/deploy.sh <배포할 커밋 전체 SHA> <reset 전 서버 HEAD>
#
# 순서: 백업 → 수집기 정지 → 빌드 → 핵심 서비스 기동(healthy 까지 대기) → 수집기 기동
#   성공하면 "마지막 성공" 기록(SHA + DB 마이그레이션 버전)을 갱신한다.
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

  # 백업이 실패하면 아무것도 바꾸지 않고 멈춘다.
  if ! bash scripts/backup-db.sh "${LAST_SHA:-$head_before}"; then
    echo "deploy: 백업 실패. 배포를 중단합니다." >&2
    return 1
  fi

  # 옛 수집기가 마이그레이션 도중에 DB 를 쓰지 않게 먼저 멈춘다.
  stop_collector

  local rc=0
  deploy_core || rc=$?

  if [ "$rc" -eq 0 ]; then
    write_state "$sha" "$(db_revision)"
    start_collector
    echo "deploy: 성공"
    return 0
  fi

  if [ "$rc" -eq 2 ]; then
    echo "deploy: 빌드 실패. 실행 중인 컨테이너는 바뀌지 않았습니다." >&2
    start_collector
    return 1
  fi

  echo "deploy: 기동 실패." >&2
  if [ -z "$LAST_SHA" ]; then
    echo "deploy: 마지막 성공 기록($STATE_FILE)이 없어 자동 롤백하지 않습니다." >&2
    return 1
  fi

  local cur_rev
  cur_rev="$(db_revision)"
  if [ -z "$cur_rev" ] || [ "$cur_rev" != "$LAST_REV" ]; then
    echo "deploy: DB 버전 ${LAST_REV:-?} -> ${cur_rev:-읽지 못함}. 마이그레이션이 적용됐을 수 있어 자동 롤백하지 않습니다." >&2
    echo "deploy: 서버에서 'bash scripts/rollback.sh --yes' 로 DB 구조까지 되돌리세요." >&2
    return 1
  fi

  echo "deploy: DB 구조가 그대로라 마지막 성공 ${LAST_SHA:0:7} 로 자동 롤백합니다."
  if checkout_sha "$LAST_SHA" && deploy_core; then
    start_collector
    echo "deploy: 자동 롤백 완료. 이번 배포는 실패입니다." >&2
  else
    echo "deploy: 자동 롤백도 실패했습니다. 직접 확인이 필요합니다." >&2
  fi
  return 1
}

main "$@"; exit $?
