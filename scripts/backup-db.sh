#!/usr/bin/env bash
# 배포 직전에 DB를 pg_dump 로 떠서 S3 에 올린다.
# 서버에서 ubuntu 사용자로, 저장소 루트(docker-compose.yml 이 있는 곳)에서 실행한다.
#   사용: bash scripts/backup-db.sh <마지막으로 성공한 커밋 SHA>
# 파일 이름: basis_<날짜시각>_<SHA 앞 7자>_<DB 마이그레이션 버전>.sql
# 그 SHA 와 버전이 롤백 때 되돌아갈 곳이다.
#
# - db 컨테이너가 떠 있지 않을 때 건너뛰는 건 첫 배포(마지막 성공 기록이 없음)뿐이다.
#   기록이 있는데 db 가 꺼져 있으면 백업 없이 마이그레이션이 적용될 수 있으므로 exit 1 로 멈춘다.
# - 업로드는 최대 3번 시도한다. 그 외의 실패(덤프 실패, 빈 파일, 업로드 3번 실패)는 exit 1 로 끝내 배포를 멈춘다.
# - 덤프에는 사용자 데이터가 들어 있다. 임시 파일은 권한 600 으로 만들고 끝나면 지운다. 저장소에 커밋하지 않는다.
set -euo pipefail
umask 077
. "$(dirname "$0")/deploy-lib.sh"

BUCKET="basis-db-backup-marketlit"
REGION="ap-northeast-2"
PREV_SHA="${1:-unknown}"

if [ -z "$(docker compose ps --status running -q db)" ]; then
  read_state
  if [ -n "$LAST_SHA" ]; then
    echo "backup: 마지막 성공 기록(${LAST_SHA:0:7})이 있는데 db 컨테이너가 실행 중이 아닙니다. 백업 없이 배포하지 않습니다." >&2
    echo "backup: db 를 먼저 확인하세요(docker compose ps, docker compose logs db)." >&2
    exit 1
  fi
  echo "backup: 첫 배포(마지막 성공 기록 없음)이고 db 컨테이너도 없어 건너뜁니다."
  exit 0
fi

REVISION="$(db_revision)"
KEY="basis_$(date +%Y%m%d-%H%M%S)_${PREV_SHA:0:7}_${REVISION:-unknown}.sql"
KEY="${KEY//,/+}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

# 컨테이너 안의 환경변수(POSTGRES_USER/DB)를 쓰므로 비밀 값을 여기에 적지 않는다.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$TMP"

if [ ! -s "$TMP" ]; then
  echo "backup: 덤프 파일이 비어 있습니다." >&2
  exit 1
fi

# 덤프는 이미 로컬에 있으므로 업로드만 다시 시도한다.
uploaded=0
for attempt in 1 2 3; do
  if aws s3 cp "$TMP" "s3://${BUCKET}/${KEY}" --region "$REGION"; then
    uploaded=1
    break
  fi
  echo "backup: 업로드 실패 (${attempt}/3)" >&2
  [ "$attempt" -lt 3 ] && sleep $((attempt * 5))
done
if [ "$uploaded" -ne 1 ]; then
  echo "backup: 업로드를 3번 시도했으나 실패했습니다." >&2
  exit 1
fi
echo "backup: 완료 s3://${BUCKET}/${KEY} ($(wc -c < "$TMP") bytes)"
