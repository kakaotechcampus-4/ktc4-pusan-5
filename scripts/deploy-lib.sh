#!/usr/bin/env bash
# deploy.sh · rollback.sh · backup-db.sh 가 같이 쓰는 함수. source 해서 쓴다.
# 서버에서 ubuntu 사용자로, 저장소 루트(docker-compose.yml 이 있는 곳)에서 실행한다고 가정한다.

# 마지막으로 배포가 끝까지 성공한 커밋(전체 SHA)과 그때의 DB 마이그레이션 버전. 한 줄: "<sha> <revision>"
# 서버의 HEAD 는 실패한 배포도 가리킬 수 있어서(git reset 이 먼저 일어난다) 되돌릴 대상으로 쓰지 않는다.
STATE_FILE="${DEPLOY_STATE_FILE:-$HOME/.basis-deploy-last-good}"
# 컨테이너가 healthy 가 된 배포는 먼저 후보로만 적는다. 외부 smoke test 까지 통과해야 promote.sh 가 STATE_FILE 로 올린다.
# (healthy 여도 Caddy/TLS/라우팅 문제로 외부에서는 안 될 수 있어서, 그런 SHA 가 되돌릴 곳으로 남지 않게 한다.)
CANDIDATE_FILE="${STATE_FILE}.candidate"
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

write_candidate() {
  printf '%s %s\n' "$1" "$2" > "$CANDIDATE_FILE"
}

# 후보의 SHA 가 $1 과 같을 때만 STATE_FILE 로 올린다. 다른 배포가 후보를 덮어썼다면 올리지 않는다.
promote_candidate() {
  local c_sha="" c_rev=""
  if [ -f "$CANDIDATE_FILE" ]; then
    read -r c_sha c_rev < "$CANDIDATE_FILE" || true
  fi
  if [ -z "$c_sha" ] || [ "$c_sha" != "$1" ]; then
    echo "promote: 후보 기록(${c_sha:0:7})이 대상(${1:0:7})과 다릅니다." >&2
    return 1
  fi
  write_state "$c_sha" "$c_rev" && rm -f "$CANDIDATE_FILE"
}

# 마지막 성공 SHA 로 코드를 되돌린다. read_state 를 먼저 불러 LAST_SHA·LAST_REV 가 채워져 있어야 한다.
# DB 마이그레이션 버전이 마지막 성공 때와 같을 때만 한다. 다르면 옛 코드가 시작하지 못하고
# downgrade 는 데이터를 지우므로 자동으로 하지 않고 rollback.sh 를 안내한다. 되돌리면 0, 아니면 1.
auto_rollback() {
  if [ -z "$LAST_SHA" ]; then
    echo "auto-rollback: 마지막 성공 기록($STATE_FILE)이 없어 자동 롤백하지 않습니다." >&2
    return 1
  fi

  local cur_rev
  cur_rev="$(db_revision)"
  if [ -z "$cur_rev" ] || [ "$cur_rev" != "$LAST_REV" ]; then
    echo "auto-rollback: DB 버전 ${LAST_REV:-?} -> ${cur_rev:-읽지 못함}. 마이그레이션이 적용됐을 수 있어 자동 롤백하지 않습니다." >&2
    echo "auto-rollback: 서버에서 'bash scripts/rollback.sh --yes' 로 DB 구조까지 되돌리세요." >&2
    return 1
  fi

  echo "auto-rollback: DB 구조가 그대로라 마지막 성공 ${LAST_SHA:0:7} 로 자동 롤백합니다."
  if checkout_sha "$LAST_SHA" && deploy_core; then
    start_collector
    echo "auto-rollback: 완료 (${LAST_SHA:0:7})."
    return 0
  fi
  echo "auto-rollback: 자동 롤백도 실패했습니다. 직접 확인이 필요합니다." >&2
  return 1
}

has_service() {
  docker compose config --services | grep -qx "$1"
}

checkout_sha() {
  git fetch origin "$1" && git reset --hard "$1"
}

# 빌드 + 핵심 서비스 기동. 빌드 실패는 2(실행 중인 컨테이너는 그대로), 기동 실패는 1.
# 마이그레이션은 backend 가 시작할 때 적용된다. 옛 수집기가 그 사이에 DB 를 쓰지 않도록 빌드가 끝난 뒤, 기동 직전에 멈춘다.
# 빌드하는 동안에는 수집기가 계속 돈다. 빌드가 실패하면 수집기는 건드리지 않았으므로 되살릴 필요도 없다.
deploy_core() {
  docker compose build || return 2
  stop_collector
  echo "up-wait-start: $(date +%T) timeout=${DEPLOY_WAIT_TIMEOUT:-120}"
  local rc=0
  # 2026-11-10 배포에서 up --wait 가 18초 걸렸다(캐시된 빌드, 마이그레이션 없음). 마이그레이션이 있는 배포는 더 걸리므로 여유를 둔다.
  # 기본 120초이고 DEPLOY_WAIT_TIMEOUT(초)으로 바꿀 수 있다. 120초는 docker-compose.yml 의 backend healthcheck(start_period 60s + interval 10s × retries 5 ≈ 110초)와 거의 같은 시점이다.
  # 마이그레이션이 60초를 넘기는 배포를 허용하려면 이 값을 올릴 때 backend 의 start_period 도 함께 올려야 한다.
  # 마이그레이션이 있는 배포의 up-wait-start/end 로그가 쌓이면 이 값을 실측으로 다시 확인한다.
  # shellcheck disable=SC2086
  docker compose up -d --wait --wait-timeout "${DEPLOY_WAIT_TIMEOUT:-120}" $CORE_SERVICES || rc=$?
  echo "up-wait-end: $(date +%T) rc=$rc"
  [ "$rc" -eq 0 ] || return 1
}

# 수집기(collector)가 compose 에 있을 때만 다룬다. 수집기 이상은 배포 실패로 치지 않는다.
# 멈추기만 하면 종료된 컨테이너가 프로젝트에 남아, 뒤이은 `up --wait` 가 그것을 어떻게 취급하는지에 기대게 된다.
# 컨테이너를 제거하면 그런 상태 자체가 없다. 수집기는 상태를 컨테이너에 두지 않고(작업 큐는 DB) 새 이미지로
# 어차피 다시 만들어지므로 추가 비용이 없다. 이전 컨테이너의 로그만 사라진다.
stop_collector() {
  if has_service collector; then
    docker compose rm -s -f collector || true
  fi
}

# 수집기는 첫 수집 한 바퀴가 끝나 heartbeat 가 생겨야 healthy 가 된다. 180초는 collector healthcheck 가 포기하는 시점
# (start_period 60s + interval 30s × retries 3 ≈ 150초)보다 조금 길게 잡은 값이다. 핵심 서비스도 같은 규칙(110초 → 120초)이다.
# 기다리다 실패해도 배포 실패로 치지 않고 로그만 남긴다.
start_collector() {
  if has_service collector; then
    docker compose up -d --wait --wait-timeout 180 collector || echo "collector-unhealthy"
  fi
}

# 배포가 성공한 뒤 이전 버전 이미지(이름 없는 이미지)와 7일 지난 빌드 캐시를 지운다.
# 실행 중인 컨테이너가 쓰는 이미지는 지워지지 않는다. 실패해도 배포 결과에는 영향이 없다.
# `docker image prune -a` 는 빌드 기반 이미지까지 지워 다음 빌드가 느려지므로 쓰지 않는다.
prune_docker() {
  docker image prune -f > /dev/null 2>&1 || true
  docker builder prune -f --filter until=168h > /dev/null 2>&1 || true
}
