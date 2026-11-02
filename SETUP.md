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

### 동작

`backend-deploy.yml` 이 컨테이너를 바꾸기 전에 `scripts/backup-db.sh` 를 실행한다.

- `pg_dump` 결과를 `s3://basis-db-backup-marketlit/basis_<날짜시각>_<배포 전 SHA>.sql` 로 올린다.
- 서버의 임시 파일은 바로 지운다.
- db 컨테이너가 없으면(첫 배포) 건너뛴다. 그 외 단계가 실패하면 배포를 멈춘다.

덤프에는 사용자 데이터가 들어 있다. 저장소에 커밋하지 않고, 서버에 파일로 남길 때는 권한을 600 으로 둔다.

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
