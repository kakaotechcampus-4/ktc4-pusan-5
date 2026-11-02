#!/usr/bin/env bash
# deploy.sh · rollback.sh · backup-db.sh 가 같이 쓰는 함수. source 해서 쓴다.
# 서버에서 ubuntu 사용자로, 저장소 루트(docker-compose.yml 이 있는 곳)에서 실행한다고 가정한다.

# 마지막으로 배포가 끝까지 성공한 커밋(전체 SHA)과 그때의 DB 마이그레이션 버전. 한 줄: "<sha> <revision>"
# 서버의 HEAD 는 실패한 배포도 가리킬 수 있어서(git reset 이 먼저 일어난다) 되돌릴 대상으로 쓰지 않는다.
STATE_FILE="${DEPLOY_STATE_FILE:-$HOME/.basis-deploy-last-good}"
CORE_SERVICES="db backend caddy"

# 현재 DB 의 alembic 버전. 읽지 못하면 빈 문자열.
db_revision() {
  docker compose exec -T db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "select version_num from alembic_version"' \
    2>/dev/null | tr -d '\r' | paste -sd, - || true
}

read_state() {
  LAST_SHA=""
  LAST_REV=""
  if [ -f "$STATE_FILE" ]; then
    read -r LAST_SHA LAST_REV < "$STATE_FILE" || true
  fi
}

write_state() {
  printf '%s %s\n' "$1" "$2" > "$STATE_FILE"
}

has_service() {
  docker compose config --services | grep -qx "$1"
}

checkout_sha() {
  git fetch origin "$1" && git reset --hard "$1"
}

# 빌드 + 핵심 서비스 기동. 빌드 실패는 2(실행 중인 컨테이너는 그대로), 기동 실패는 1.
deploy_core() {
  docker compose build || return 2
  echo "up-wait-start: $(date +%T)"
  local rc=0
  # shellcheck disable=SC2086
  docker compose up -d --wait $CORE_SERVICES || rc=$?
  echo "up-wait-end: $(date +%T) rc=$rc"
  [ "$rc" -eq 0 ] || return 1
}

# 수집기(collector)가 compose 에 있을 때만 다룬다. 수집기 이상은 배포 실패로 치지 않는다.
stop_collector() {
  if has_service collector; then
    docker compose stop collector || true
  fi
}

start_collector() {
  if has_service collector; then
    docker compose up -d --wait --wait-timeout 180 collector || echo "collector-unhealthy"
  fi
}
