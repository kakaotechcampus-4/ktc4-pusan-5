#!/usr/bin/env bash
# ai/ 배치를 서버에서 한 줄로 실행한다. 저장소 어디서 불러도 된다.
#   사용: bash ai/run.sh <명령>
#
#   bash ai/run.sh build                                    이미지를 (다시) 빌드한다. ai 코드가 바뀐 뒤 한 번 한다
#   bash ai/run.sh -m app.collectors.sources show 12        python -m <모듈> 의 줄임말
#   bash ai/run.sh -m app.collectors.analyst_report --days 1
#   bash ai/run.sh alembic current                          alembic 줄임말 (읽기 명령)
#   bash ai/run.sh <그 밖의 명령>                           컨테이너 안에서 그대로 실행한다
#
# - 컨테이너는 실행하는 동안만 뜨고 끝나면 지워진다(--rm). 계속 떠 있는 것은 없다.
# - db 는 이미 떠 있다고 가정하고 건드리지 않는다(--no-deps). 운영 컨테이너를 재생성하지 않는다.
# - 설정값은 저장소 루트 .env(DB 계정)와 ai/.env(수집 키)에서 읽는다. ai/.env 는 없어도 실행된다.
# - 이 스크립트는 배포(scripts/deploy.sh)와 무관하다. 배포 때 ai 이미지는 빌드되지 않는다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

compose() {
  docker compose -f docker-compose.yml -f docker-compose.ai.yml "$@"
}

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

case "${1:-}" in
  ""|-h|--help|help)
    usage
    exit 0
    ;;
  build)
    compose build ai
    exit 0
    ;;
  -m)
    shift
    set -- /app/.venv/bin/python -m "$@"
    ;;
  alembic)
    shift
    set -- /app/.venv/bin/alembic "$@"
    ;;
esac

# 운영 DB 구조를 바꾸는 alembic 명령은 일부러 한 번 더 확인한다.
# (current, history, heads, show 같은 읽기 명령은 그대로 된다.)
if [ "${1:-}" = "/app/.venv/bin/alembic" ]; then
  case "${2:-}" in
    upgrade|downgrade|stamp|revision|merge)
      if [ "${AI_ALLOW_MIGRATE:-}" != "1" ]; then
        echo "ai/run.sh: 'alembic ${2}' 는 DB 구조를 바꿉니다. 의도한 것이면 AI_ALLOW_MIGRATE=1 을 붙여 다시 실행하세요." >&2
        echo "ai/run.sh: 운영 DB 에 적용하기 전에 백업(scripts/backup-db.sh)이 있는지 먼저 확인하세요." >&2
        exit 2
      fi
      ;;
  esac
fi

exec docker compose -f docker-compose.yml -f docker-compose.ai.yml run --rm --no-deps ai "$@"
