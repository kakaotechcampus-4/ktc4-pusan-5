# SETUP.md

클론 후 한 번만 하는 세팅. 팀원 전원 동일하게 맞춘다.

## 0. git hook 연결 (필수)

```bash
git config core.hooksPath .githooks
```

브랜치 규칙(main 직접 커밋 금지, `feature/*`·`refactor/*` 이름 규칙)과
프론트 디자인 검사·eslint 를 커밋 시점에 돌린다. 안 걸어두면 규칙은 문서로만 존재한다.

**Windows 사용자**: 훅은 Git Bash 로 실행되므로 Git for Windows 가 설치돼 있으면 그대로 동작한다.
`bad interpreter` 에러가 나면 줄바꿈이 CRLF 로 바뀐 경우다. `.gitattributes` 가 막아주지만
이미 받은 파일이 문제면 아래로 다시 받는다.

```bash
git rm --cached -r . && git reset --hard
```

## 1. frontend 프로젝트 생성

`frontend/` 에는 이미 `src/`, 설정 파일, CLAUDE.md, DESIGN.md 가 들어있다.
Vite 프로젝트 골격만 얹으면 된다.

```bash
cd frontend
npm create vite@latest . -- --template react-ts
# "현재 폴더에 파일이 있다" → 기존 파일 유지(Ignore files and continue) 선택
```

생성 후 이 저장소에 들어있던 `src/`, `vite.config.ts`, `eslint.config.js`,
`.prettierrc.json` 이 남아있는지 확인한다. Vite 가 덮어썼으면 git 에서 되살린다.

```bash
git checkout -- src vite.config.ts eslint.config.js .prettierrc.json
```

## 2. 의존성

```bash
cd frontend
npm install
npm i react-router-dom
npm i -D tailwindcss @tailwindcss/vite
npm i -D prettier prettier-plugin-tailwindcss eslint-config-prettier
```

`npm create vite` 가 eslint, typescript-eslint, eslint-plugin-react-hooks,
eslint-plugin-react-refresh, globals 는 이미 넣어준다. 위에 추가한 건 prettier 연동뿐이다.

## 3. package.json 스크립트

생성된 `frontend/package.json` 의 `scripts` 를 아래로 맞춘다.

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint .",
    "lint:fix": "eslint . --fix",
    "format": "prettier --write .",
    "check:design": "node scripts/check-design.mjs",
    "check": "npm run lint && npm run check:design"
  }
}
```

## 4. tsconfig 경로 별칭

`frontend/tsconfig.app.json` 의 `compilerOptions` 에 추가한다. `@/lib/format` 같은 import 가 이걸 쓴다.

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  }
}
```

## 5. 확인

```bash
cd frontend
npm run dev            # http://localhost:5173
npm run check          # lint + 디자인 규칙
```

## 6. VSCode

`.vscode/extensions.json` 에 권장 확장이 들어있다. VSCode 가 알림으로 물어보면 설치한다.

- ESLint
- Prettier
- Tailwind CSS IntelliSense — 토큰 유틸리티(`bg-surface`, `text-h2`)를 자동완성해준다. 이거 없으면 토큰 이름을 외워야 한다.

저장 시 자동 포맷·자동 수정은 `.vscode/settings.json` 에 이미 설정돼 있다.

## 7. 서버 DB 백업과 복구 (배포 담당)

팀원 전원이 할 일이 아니다. EC2 서버를 관리하는 사람이 맞춰 두는 설정이다.
DB 데이터는 서버 디스크(`pgdata` 볼륨)에만 있어서, 서버를 삭제하거나 디스크가 사라지면 같이 사라진다.
그래서 배포 때마다 DB 사본을 서버 밖(S3)에 남긴다. 마이그레이션은 테이블 구조만 다시 만들 뿐 데이터는 되살리지 못한다.

### 사전 준비 (서버에 한 번)

- AWS CLI v2 를 ubuntu 사용자가 쓸 수 있게 설치한다. `aws --version` 으로 확인한다.
- S3 버킷 `basis-db-backup-marketlit` (서울 리전, 퍼블릭 액세스 모두 차단).
  수명 주기 규칙으로 30일이 지난 파일을 지운다. 배포가 30일 이상 없으면 백업이 모두 지워질 수 있다.
- EC2 에 붙은 IAM 역할(`ktc-ec2`)이 이 버킷에 읽기·쓰기·삭제를 할 수 있어야 한다. 별도 키는 저장하지 않는다.
- 롤백이 되돌아갈 곳을 적은 파일 `~/.basis-deploy-last-good` 을 한 번 만든다. 내용은 "지금 배포돼 있는 커밋 전체 SHA 와 DB 마이그레이션 버전" 한 줄이다.
  외부 smoke test 까지 통과한 배포마다 `scripts/promote.sh` 가 갱신하지만, 처음 성공하기 전에 실패하면 자동 롤백이 안 되므로 미리 적어 둔다.
  서버가 지금 배포된 커밋(`git rev-parse HEAD`)인지 먼저 확인한다.

```bash
cd ~/ktc4-pusan-5
echo "$(git rev-parse HEAD) $(echo 'select version_num from alembic_version;' | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At')" > ~/.basis-deploy-last-good
cat ~/.basis-deploy-last-good
```

### 동작

`backend-deploy.yml` 은 코드를 서버에 맞춘 뒤 `scripts/deploy.sh` 를 호출한다. 서버에서의 배포는 이 스크립트가 한다.

```
백업(S3) → 빌드 → 수집기 제거(있으면) → db·backend·caddy 기동(healthy 까지 대기) → 수집기 기동(있으면) → 이전 이미지 정리 → (워크플로) 외부 smoke test → 마지막 성공 확정(promote.sh)
```

- 백업: `pg_dump` 결과를 `s3://basis-db-backup-marketlit/basis_<날짜시각>_<마지막 성공 SHA 7자>_<DB 마이그레이션 버전>.sql` 로 올린다.
  서버의 임시 파일은 바로 지운다. db 컨테이너가 없을 때 건너뛰는 건 첫 배포(마지막 성공 기록이 없음)뿐이다. 기록이 있는데 db 가 꺼져 있으면 백업 없이 마이그레이션이 적용될 수 있어 배포를 멈춘다.
  업로드는 최대 3번 시도하고, 그래도 실패하거나 그 외 단계가 실패하면 아무것도 바꾸지 않고 배포를 멈춘다.
- 수집기는 빌드가 끝난 뒤, backend 를 시작(마이그레이션)하기 직전에 멈추고 컨테이너를 제거한다(`docker compose rm -s -f collector`). 빌드하는 동안에는 계속 돈다.
  종료된 컨테이너를 남기지 않아 `up --wait` 가 그것에 영향받지 않게 하려는 것이고, 새 이미지로 어차피 다시 만들어지므로 추가 비용은 없다. 이전 컨테이너의 `docker logs` 만 사라진다.
- 기동에 성공하면 `~/.basis-deploy-last-good.candidate` 에 "이 커밋 + 그때의 DB 버전"을 **후보**로만 적는다. 컨테이너가 healthy 여도 Caddy/TLS/라우팅 문제로 외부에서는 안 될 수 있어서다.
  워크플로의 외부 smoke test(`/health`, `/api/concepts`)를 통과하면 `scripts/promote.sh <SHA>` 가 후보를 `~/.basis-deploy-last-good` 로 올린다. smoke 가 실패하면 올리지 않아 롤백 대상은 이전 정상 SHA 로 남는다.
  서버의 `HEAD` 는 실패한 배포도 가리킬 수 있어서 되돌릴 곳으로 쓰지 않는다.
- 수집기 이상(unhealthy)은 로그에 `collector-unhealthy` 만 남기고 배포 실패로 치지 않는다.
- 성공하면 이전 버전 이미지(이름 없는 이미지)와 7일 지난 빌드 캐시를 지운다(`docker image prune -f`, `docker builder prune --filter until=168h`). 실행 중인 컨테이너의 이미지는 지워지지 않는다.

덤프에는 사용자 데이터가 들어 있다. 저장소에 커밋하지 않고, 서버에 파일로 남길 때는 권한을 600 으로 둔다.

### 롤백

기동에 실패했을 때 DB 마이그레이션 버전이 "마지막 성공" 때와 같은지로 갈린다.

| 상황 | DB 구조 | 옛 코드가 시작하나 | 처리 |
|---|---|---|---|
| 빌드 실패 | 그대로 | (컨테이너가 안 바뀜) | 롤백 없음 |
| 새 코드가 이상함, 마이그레이션 없음 | 그대로 | 된다 | **자동**으로 마지막 성공 SHA 를 다시 배포한다 |
| 마이그레이션 도중 실패 | 그대로 (트랜잭션으로 되돌려짐) | 된다 | **자동** |
| 마이그레이션이 적용된 뒤 새 코드가 이상함 | 새 구조 | **안 된다** (옛 backend 가 시작 때 `alembic upgrade head` 에서 "Can't locate revision" 으로 실패) | 자동으로 하지 않는다. 아래 수동 롤백 |

외부 smoke test 가 실패했을 때도 워크플로가 `scripts/auto-rollback.sh` 를 불러 같은 규칙으로 되돌린다. smoke 는 GitHub 러너가 밖에서 확인해서 러너 쪽 네트워크 문제로도 실패할 수 있으므로, 롤백 전에 서버가 같은 주소(`/health`, `/api/concepts`)를 직접 한 번 더 확인한다.

- 서버에서도 실패하면 새 버전 문제로 보고, DB 버전이 마지막 성공 때와 같을 때만 자동으로 되돌린다. 다르면 위 표의 마지막 행처럼 `rollback.sh --yes` 를 안내한다.
- 서버에서는 정상이면 DNS·보안 그룹 같은 외부 접근 문제다. 코드를 되돌려도 고쳐지지 않으므로 롤백하지 않고 로그에 "서버에서는 정상"이라고 남긴다.
- 어느 경우든 이번 배포는 마지막 성공으로 확정되지 않고, Actions 는 실패로 끝난다.

자동 롤백으로 사이트가 살아나도 새 버전 배포는 실패이므로 Actions 는 실패로 끝난다. 마지막 성공 기록이 없거나 DB 버전을 읽지 못하면 자동 롤백하지 않는다.

- 서버에서 `git`·`docker compose` 로 직접 배포하면 마지막 성공 기록이 갱신되지 않는다. 직접 배포한 뒤에는 위 "사전 준비"의 명령으로 기록을 다시 적는다.
  `deploy.sh` 만 직접 돌렸다면 후보만 남은 상태이므로, 외부 주소를 직접 확인한 뒤 `bash scripts/promote.sh <SHA>` 로 확정한다.
- `scripts/` 가 없던 커밋(이 기능이 들어가기 전)으로 롤백하면 서버 저장소에서 스크립트가 사라진다. 다음 배포 전까지 `rollback.sh` 를 쓸 수 없으므로 그때는 위 표의 내용을 손으로 한다.
- 되돌리는 대상은 `backend` 의 마이그레이션(`alembic_version`)뿐이다. `ai/` 의 마이그레이션(`alembic_version_ai`)은 다루지 않는다.

**수동 롤백** — 서버의 `~/ktc4-pusan-5` 에서 ubuntu 사용자로 실행한다.

```bash
bash scripts/rollback.sh          # DB 버전이 같으면 코드만 되돌린다
bash scripts/rollback.sh --yes    # DB 버전이 다르면 alembic downgrade 로 구조를 되돌린 뒤 마지막 성공 SHA 를 배포한다
```

- `downgrade` 는 새 버전이 만든 컬럼·표의 **데이터를 지운다.** 그래서 `--yes` 없이는 진행하지 않는다. 기존 데이터는 남는다.
- 새 backend 를 멈추고, 지금 빌드된 새 이미지로 `downgrade` 를 한다(새 마이그레이션 파일이 그 이미지에 있다).
- `downgrade` 가 실패하면 backend 는 멈춘 상태로 남는다. 이때 마지막 성공 SHA·DB 버전과 현재 DB 버전을 함께 출력한다. 아래 "최후 수단"을 따른다.
- **트랜잭션 밖에서 도는 DDL 의 한계.** Postgres 의 alembic 마이그레이션은 기본적으로 트랜잭션 안에서 돌아, 실패하면 통째로 되돌아가고 `alembic_version` 도 그대로다.
  `autocommit_block` 으로 `CREATE INDEX CONCURRENTLY` 같은 문장을 쓰는 마이그레이션은 중간에 실패하면 버전은 그대로인데 스키마만 일부 바뀐 채 남을 수 있다(현재 그런 마이그레이션은 없다).
  이때 자동 롤백은 버전이 같다는 이유로 코드만 되돌리므로 스키마가 일부 바뀐 상태는 알아채지 못한다.
  그런 마이그레이션을 쓸 때는 revision 하나에 문장 하나만 두고 `IF NOT EXISTS` 로 다시 실행해도 안전하게 쓴다. 상태가 의심되면 배포 전 백업으로 되돌린다(아래 "최후 수단").

**최후 수단: 운영 DB 를 백업으로 되돌리기** — `downgrade` 가 안 될 때만 한다. **백업 이후에 쌓인 데이터는 모두 사라진다.**
백업 파일 이름의 SHA 와 버전이 되돌아갈 곳이다. 한 줄씩 실행한다.

```bash
docker compose stop backend collector
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE \"$POSTGRES_DB\" WITH (FORCE)" -c "CREATE DATABASE \"$POSTGRES_DB\""'
(umask 077; aws s3 cp s3://basis-db-backup-marketlit/<파일 이름> ~/restore.sql --region ap-northeast-2)
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -v ON_ERROR_STOP=1' < ~/restore.sql
rm ~/restore.sql
# ~/.basis-deploy-last-good 의 첫 번째 값(전체 SHA)으로 코드를 맞춘다. 백업 파일 이름의 SHA 는 7자라 fetch 에 쓸 수 없다.
git fetch origin <전체 SHA> && git reset --hard <전체 SHA>
docker compose up -d --build
```

이 절차의 DB 삭제·재생성 부분은 시험하지 않았다. 백업을 빈 DB 에 복원하는 부분만 임시 DB 로 시험했다.

### 복구

서버를 새로 만든 경우다. 서버의 `/home/ubuntu/ktc4-pusan-5` 에서 ubuntu 사용자로 한 줄씩 실행한다.

```bash
# 1. 저장소를 받고 .env 를 준비한 뒤 db 만 띄운다. backend 를 먼저 띄우면 마이그레이션이 테이블을 만들어 복구가 충돌한다.
docker compose up -d db

# 2. 백업 목록에서 복구할 파일을 고른다. 이름의 날짜가 가장 최근인 것이 보통이다.
aws s3 ls s3://basis-db-backup-marketlit/ --region ap-northeast-2

# 3. 받아서 권한을 600 으로 둔다.
(umask 077; aws s3 cp s3://basis-db-backup-marketlit/<파일 이름> ~/restore.sql --region ap-northeast-2)

# 4. 빈 DB 에 복구한다.
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -v ON_ERROR_STOP=1' < ~/restore.sql

# 5. 확인한다. 마이그레이션 버전과 테이블 수를 본다.
echo "select version_num from alembic_version;" | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At'

# 6. 전체를 띄우고 복구 파일을 지운다.
docker compose up -d --build
rm ~/restore.sql
```

복구 후 마이그레이션 버전이 백업 시점의 값과 같아야 한다. 코드가 그보다 새 마이그레이션을 가지고 있으면
6번에서 backend 가 시작하면서 나머지를 적용한다.

### 복구 시험

운영 DB 를 건드리지 않고 확인하려면 같은 Postgres 안에 임시 DB 를 만들어 복구한 뒤 지운다.

```bash
echo "CREATE DATABASE restore_test;" | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres'
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d restore_test -q -v ON_ERROR_STOP=1' < ~/restore.sql
echo "DROP DATABASE restore_test;" | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres'
```

2026-11-02 에 이 방법으로 `pg_dump` → S3 업로드 → 다운로드 → 임시 DB 복구를 확인했다.
테이블 수(26)와 마이그레이션 버전(`20261005_01`)이 운영 DB 와 같았다.
새 서버에서 처음부터 복구하는 전체 과정은 시험하지 않았다.

## 8. 수집기(collector) 서버 배포 (배포 담당)

수집기는 `python -m app.collectors.market --loop` 로 도는 별도 프로세스다. 홈 지표(환율·금·랭킹·수급·지수)와 30개 종목의 현재가·재무·차트를 외부에서 받아 DB 에 채운다.
API 서버는 외부를 호출하지 않고 DB 를 읽기만 하므로, **수집기가 없으면 현재가가 갱신되지 않고 `/api/stocks` 도 종목 목록 준비 중(503)으로 남는다.**

### 구성

- `docker-compose.yml` 의 `collector`: backend 와 같은 이미지(`ktc4-backend:latest`)를 쓰고 명령만 다르다. `init: true`, `restart: unless-stopped`.
- 한 번에 하나만 돈다(DB advisory lock). 두 번째가 뜨면 "Another market worker is already running" 을 남기고 바로 종료한다.
- 하트비트 헬스체크: 수집 루프가 DB 오류 없이 한 바퀴 돌 때마다 `/tmp/collector-heartbeat` 를 갱신하고, 헬스체크는 5분 안에 갱신됐는지 본다.
  **수집기가 살아 있는지(liveness)만 본다.** KIS/KRX/FRED 같은 외부 소스가 계속 실패해도 오류는 결과값으로 흡수되므로 healthy 로 남을 수 있다.
  **unhealthy 가 되어도 도커는 재시작하지 않는다.** 멈춘 것을 알려 줄 뿐이라 직접 `docker compose restart collector` 를 해야 한다.
- 마지막 수집 성공 시각: 홈 시장 데이터가 한 건이라도 오류 없이 저장되면 `/tmp/collector-last-success` 를 갱신한다(헬스체크는 보지 않는다).
  `docker compose exec collector stat -c '%y' /tmp/collector-last-success` 로 확인한다. 수집할 만기가 없는 반복(장외 등)에서는 갱신하지 않으므로,
  오래됐다고 곧바로 이상은 아니다. 그 시각이 오래됐는데 `docker compose logs collector` 에 같은 오류가 반복되면 외부 소스 문제다.
- 로그는 파일당 10MB, 3개까지만 남긴다(collector·backend).
- 배포(`scripts/deploy.sh`): 마이그레이션이 적용되기 전에 수집기를 멈추고, backend 가 healthy 가 된 뒤 다시 띄운다.
  수집기 이상은 배포 실패로 치지 않고 로그에 `collector-unhealthy` 만 남긴다. 마이그레이션이 적용된 뒤 실패해서 자동 롤백을 하지 않는 경우에는 수집기도 멈춘 채로 남는다.

### 사전 준비 (서버)

- `backend/.env` 에 `KIS_APP_KEY`, `KIS_APP_SECRET`(필수), `KRX_AUTH_KEY`, `FRED_API_KEY` 가 있어야 한다. 값은 출력하지 않는다.
- **같은 KIS 앱키를 쓰는 다른 곳(팀원의 로컬 수집기 등)이 동시에 돌면 호출 한도를 나눠 쓰게 되어** 초당 제한 오류(`EGW00201`)가 난다.
- `docker compose up --help | grep -i wait` 에 `--wait-timeout` 이 있어야 한다.
- 권장: 스왑이 없으면 메모리가 바닥났을 때 리눅스가 프로세스를 강제 종료하고, 그 대상이 DB 일 수도 있다. 2GB 정도 안전망을 둔다.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -m
```

### 첫 배포 후 확인

```bash
docker compose ps                         # collector 가 healthy 인지(처음 1~2분은 starting)
docker compose logs collector --tail 50   # "stock catalog: N saved" 가 있어야 한다
docker stats --no-stream                  # 메모리. collector 의 mem_limit(1g)은 임시값이다
```

- 종목 목록이 동기화되면 `/api/stocks` 가 503 에서 풀리고, 30개 종목의 현재가가 쌓이는 데 한 바퀴(약 30초 이상)가 걸린다.
- 호출량(코드 기준): KIS 홈 지표 분당 약 8건(장 시간과 무관하게 항상) + 종목 현재가 장중 분당 최대 30건. 한도(간격 1초 = 분당 60건)의 약 60% 라 장중에는 재무·차트 작업이 늦어질 수 있다.

### 수동 제어

```bash
docker compose stop collector       # 멈춘다. 다음 배포 때 deploy.sh 가 다시 띄운다
docker compose up -d collector      # 다시 띄운다
docker compose restart collector    # unhealthy 일 때
```
