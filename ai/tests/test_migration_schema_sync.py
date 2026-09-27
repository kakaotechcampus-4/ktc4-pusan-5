"""`stock_move_analysis*` 네 표의 모델과 마이그레이션이 어긋나지 않았는지 본다.

**DB 없이 돈다.** 이게 요점이다 — `tests/test_migrations.py` 의 PostgreSQL 테스트는
`MIGRATION_TEST_ADMIN_URL` 이 없으면 전부 skip 되므로, DB 가 없는 환경에서는
"모델에 칼럼을 더하고 마이그레이션을 안 만든" 실수를 잡는 장치가 하나도 없게 된다.
이 파일이 그 자리를 메운다. 오프라인 모드(`alembic upgrade head --sql`)로
마이그레이션이 내놓을 DDL 을 받아, 같은 모델을 SQLAlchemy 로 직접 컴파일한 DDL 과
맞춰 본다.

**`analyst_reports` 는 일부러 뺐다.** 그 표는 `0001` 이 만든 뒤 `0018` 이 ALTER 로
고치는 식으로 진화해서, "CREATE TABLE 한 방" 과 비교할 수가 없다. 그쪽 검증은
실제 DB 에 전체 리비전을 올린 뒤 `alembic check` 로 보는 test_migrations.py 담당이다.

**이 테스트가 못 잡는 것:** 이미 돌고 있는 DB 의 실제 스키마와 모델의 차이.
그건 DB 를 띄우고 `uv run alembic check` 을 돌려야 한다.

alembic 을 같은 프로세스에서 부르지 않고 하위 프로세스로 돌린다. env.py 가 로깅을
다시 설정하고 sys.path 를 건드려서, 같은 프로세스에서 부르면 다른 테스트에 영향이 남는다.
"""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import app.models  # noqa: F401  — Base.metadata 에 모델을 등록한다
from app.core.database import Base

AI_DIR = Path(__file__).resolve().parents[1]
DIALECT = postgresql.dialect()

# 이 파일이 보는 표. 접두사로 고르므로 다섯 번째 표가 생겨도 자동으로 포함된다.
PREFIX = "stock_move_analysis"


def managed_tables() -> dict:
    tables = {n: t for n, t in Base.metadata.tables.items() if n.startswith(PREFIX)}
    # 표 이름을 또 바꾸면 이 테스트가 조용히 아무것도 안 보게 된다. 그때 여기서 걸린다.
    assert tables, f"{PREFIX}* 로 시작하는 표가 없다 — PREFIX 가 낡았다"
    return tables


def _alembic(*args: str) -> str:
    """하위 프로세스로 alembic 을 부르고 표준출력을 돌려준다.

    PYTHONIOENCODING 을 박아 둔다. 한국어 Windows 는 자식 프로세스의 출력을 cp949 로
    쓰는데, alembic 이 리비전 제목을 로그에 찍으므로 그대로 두면 읽는 쪽에서
    UnicodeDecodeError 가 난다.
    """
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=AI_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        # 실패를 예외가 아니라 assert 로 보고한다. stderr 를 메시지에 실어야
        # "왜 alembic 이 죽었나" 가 테스트 출력에 바로 보인다.
        check=False,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} 실패:\n{result.stderr}"
    return result.stdout


def _squash(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().rstrip(";").lower()


def _statements(sql: str) -> list[str]:
    """오프라인 출력에서 SQL 문만 끊어 낸다.

    alembic 은 리비전마다 `-- Running upgrade ...` 주석을 앞에 붙인다. 그대로 두면
    그 리비전의 첫 CREATE TABLE 이 주석에 딸려 들어가 "create table" 로 시작하지
    않게 되고, 표가 통째로 안 보인다.
    """
    stripped = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [s for s in stripped.split(";") if s.strip()]


def _split_clauses(body: str) -> set[str]:
    """CREATE TABLE 괄호 안을 쉼표로 가르되 괄호 안의 쉼표는 건드리지 않는다.

    `NUMERIC(8, 2)` 나 `UNIQUE (a, b)` 가 쪼개지면 안 된다. 절의 **순서**는 비교에서
    뺀다 — alembic 은 FK 를 UNIQUE 앞에 놓고 SQLAlchemy 는 뒤에 놓는데, 만들어지는
    표는 같다. 순서까지 맞추라고 하면 의미 없는 실패만 난다.
    """
    clauses, depth, buf = set(), 0, ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            clauses.add(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        clauses.add(buf.strip())
    return clauses


def _table_shape(sql: str) -> tuple[str, set[str]]:
    """`create table x (...)` → (표 이름, 절 집합)."""
    m = re.match(r"create table (\S+) \((.*)\)$", _squash(sql), re.DOTALL)
    assert m, f"CREATE TABLE 을 못 읽었다: {sql[:80]}"
    return m.group(1), _split_clauses(m.group(2))


@pytest.fixture(scope="module")
def migration_sql() -> str:
    """빈 DB 에 head 까지 올렸을 때 나갈 SQL. DB 에 붙지 않는다."""
    return _alembic("upgrade", "head", "--sql")


def test_every_model_table_is_created_by_a_migration(migration_sql: str) -> None:
    """모델에 있는 표가 마이그레이션에 빠지면 배포 후에야 드러난다.

    칼럼 하나하나까지 맞춰 본다 — 표 이름만 보면 '칼럼 추가하고 마이그레이션 안 씀'
    이 그대로 통과한다.
    """
    emitted = {
        _table_shape(stmt)[0]: _table_shape(stmt)[1]
        for stmt in _statements(migration_sql)
        if _squash(stmt).startswith("create table ")
    }
    for name, table in managed_tables().items():
        assert name in emitted, f"{name} 을 만드는 마이그레이션이 없다"
        want = _table_shape(str(CreateTable(table).compile(dialect=DIALECT)))[1]
        assert want == emitted[name], (
            f"{name} 이 모델과 다르다\n"
            f"  모델에만: {sorted(want - emitted[name])}\n"
            f"  마이그레이션에만: {sorted(emitted[name] - want)}"
        )


def test_every_model_index_is_created_by_a_migration(migration_sql: str) -> None:
    """인덱스는 빠져도 기능이 돌아서 더 늦게 드러난다. 느려질 뿐이다.

    verify_status = passed 부분 인덱스처럼 조건이 붙은 것도 여기서 같이 본다 —
    WHERE 절이 빠지면 인덱스는 생기는데 의도한 물건이 아니다.
    """
    emitted = {
        _squash(s) for s in _statements(migration_sql) if _squash(s).startswith("create index")
    }
    for table in managed_tables().values():
        for index in table.indexes:
            want = _squash(str(CreateIndex(index).compile(dialect=DIALECT)))
            assert want in emitted, f"{index.name} 을 만드는 마이그레이션이 없다\n  모델: {want}"


def test_managed_tables_covers_every_model_table() -> None:
    """env.py 의 MANAGED_TABLES 에 빠진 표는 autogenerate 와 `alembic check` 이
    아예 보지 않는다. 마이그레이션이 없어도 check 가 '변경 없음' 이라고 해서,
    빠뜨리면 이 레포의 스키마 검증이 통째로 헛돈다.

    env.py 를 import 하면 마이그레이션이 실행되므로 ast 로 읽기만 한다.
    """
    tree = ast.parse((AI_DIR / "alembic/env.py").read_text(encoding="utf-8"))
    managed: set[str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "MANAGED_TABLES" for t in node.targets
        ):
            managed = set(ast.literal_eval(node.value))
    assert managed is not None, "env.py 에서 MANAGED_TABLES 를 찾지 못했다"

    missing = set(Base.metadata.tables) - managed
    assert not missing, f"MANAGED_TABLES 에 빠진 표: {sorted(missing)}"
