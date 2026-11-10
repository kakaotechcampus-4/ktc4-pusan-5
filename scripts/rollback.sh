#!/usr/bin/env bash
# 마지막으로 성공한 배포로 수동 롤백한다. 서버에서 ubuntu 사용자로, 저장소 루트에서 실행한다.
#   사용: bash scripts/rollback.sh [--yes]
#
# 마지막 성공 기록(SHA + DB 마이그레이션 버전)은 deploy.sh 가 남긴다.
#   - 지금 DB 버전이 기록과 같으면 코드만 되돌린다.
#   - 다르면(마이그레이션이 적용됨) 옛 코드가 시작하지 못하므로 먼저 `alembic downgrade` 로 DB 구조를 되돌린다.
#     downgrade 는 새 버전이 만든 컬럼·표의 데이터를 지우므로 --yes 가 있어야 진행한다.
#     downgrade 에 실패하면 SETUP.md 의 백업 복원 절차를 따른다(최후 수단, 백업 이후 데이터는 사라진다).
#
# deploy.sh 와 같은 이유로 전체를 함수로 감싼다(git reset 이 이 파일을 바꿀 수 있다).
set -uo pipefail
. "$(dirname "$0")/deploy-lib.sh"

main() {
  local yes=0
  [ "${1:-}" = "--yes" ] && yes=1

  read_state
  if [ -z "$LAST_SHA" ] || [ -z "$LAST_REV" ]; then
    echo "rollback: 마지막 성공 기록($STATE_FILE)이 없습니다." >&2
    return 1
  fi

  local cur_rev
  cur_rev="$(db_revision)"
  echo "rollback: 마지막 성공 ${LAST_SHA:0:7} (DB ${LAST_REV}) / 현재 DB ${cur_rev:-읽지 못함}"
  if [ -z "$cur_rev" ]; then
    echo "rollback: 현재 DB 버전을 읽지 못했습니다. db 컨테이너를 먼저 확인하세요." >&2
    return 1
  fi

  if [ "$cur_rev" != "$LAST_REV" ] && [ "$yes" -ne 1 ]; then
    echo "rollback: DB 구조를 ${cur_rev} -> ${LAST_REV} 로 되돌려야 합니다." >&2
    echo "rollback: downgrade 는 새 버전이 만든 컬럼·표의 데이터를 지웁니다. 진행하려면 --yes 를 붙여 다시 실행하세요." >&2
    return 2
  fi

  stop_collector

  if [ "$cur_rev" != "$LAST_REV" ]; then
    # 문제가 있는 새 backend 를 먼저 멈춘다. downgrade 는 지금 빌드된 새 이미지로 한다(새 마이그레이션 파일이 거기 있다).
    docker compose stop backend || true
    if ! docker compose run --rm --no-deps backend /app/.venv/bin/alembic downgrade "$LAST_REV"; then
      echo "rollback: downgrade 실패. backend 가 멈춘 상태입니다. SETUP.md 의 '복구' 절차(백업 복원)를 따르세요." >&2
      echo "rollback: 복원 정보 - 마지막 성공 SHA ${LAST_SHA} / 마지막 성공 DB 버전 ${LAST_REV} / 현재 DB 버전 $(db_revision || true)" >&2
      return 1
    fi
    local after
    after="$(db_revision)"
    if [ "$after" != "$LAST_REV" ]; then
      echo "rollback: downgrade 후 DB 버전이 ${after:-읽지 못함} 입니다(기대 ${LAST_REV}). 중단합니다." >&2
      return 1
    fi
  fi

  if ! checkout_sha "$LAST_SHA"; then
    echo "rollback: ${LAST_SHA:0:7} 로 코드를 맞추지 못했습니다." >&2
    return 1
  fi
  if ! deploy_core; then
    echo "rollback: 이전 버전 기동에 실패했습니다. 직접 확인이 필요합니다." >&2
    return 1
  fi
  start_collector
  echo "rollback: 완료 (${LAST_SHA:0:7}, DB ${LAST_REV})"
  return 0
}

main "$@"; exit $?
