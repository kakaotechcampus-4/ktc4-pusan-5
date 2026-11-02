#!/usr/bin/env bash
# 배포 직전에 DB를 pg_dump 로 떠서 S3 에 올린다.
# 서버에서 ubuntu 사용자로, 저장소 루트(docker-compose.yml 이 있는 곳)에서 실행한다.
#   사용: bash scripts/backup-db.sh <마지막으로 성공한 커밋 SHA>
# 파일 이름: basis_<날짜시각>_<SHA 앞 7자>_<DB 마이그레이션 버전>.sql
# 그 SHA 와 버전이 롤백 때 되돌아갈 곳이다.
#
# - db 컨테이너가 떠 있지 않으면(첫 배포 등) 건너뛴다.
# - 그 외의 실패(덤프 실패, 빈 파일, 업로드 실패)는 exit 1 로 끝내 배포를 멈춘다.
# - 덤프에는 사용자 데이터가 들어 있다. 임시 파일은 권한 600 으로 만들고 끝나면 지운다. 저장소에 커밋하지 않는다.
set -euo pipefail
umask 077
. "$(dirname "$0")/deploy-lib.sh"

BUCKET="basis-db-backup-marketlit"
REGION="ap-northeast-2"
PREV_SHA="${1:-unknown}"

if [ -z "$(docker compose ps --status running -q db)" ]; then
  echo "backup: db 컨테이너가 실행 중이 아니어서 건너뜁니다."
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

aws s3 cp "$TMP" "s3://${BUCKET}/${KEY}" --region "$REGION"
echo "backup: 완료 s3://${BUCKET}/${KEY} ($(wc -c < "$TMP") bytes)"
