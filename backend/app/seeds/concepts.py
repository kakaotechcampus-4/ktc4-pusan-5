"""개념 시드(seeds/concepts/*.json)를 DB 에 넣는다.

    uv run alembic upgrade head                    # concepts 테이블이 먼저 있어야 한다
    uv run python -m app.seeds.concepts            # 비어 있을 때만 적재
    uv run python -m app.seeds.concepts --force    # 이미 있어도 전부 갱신

검증 로직(load_raw_seeds·validate_seeds)은 DB 없이 단위테스트할 수 있게 분리해 뒀다.
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import ProgrammingError

from app.core.database import SessionLocal, engine
from app.core.taxonomy import SEEDS_DIR, Taxonomy, get_taxonomy
from app.repositories.concept import ConceptRepository
from app.schemas.concept import OPTIONAL_SECTIONS, ConceptSeed

CONCEPTS_DIR = SEEDS_DIR / "concepts"

# 본문의 [텍스트](slug) 링크. href 자리에 slug 만 쓴다.
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]*)\)")


def load_raw_seeds(directory: Path = CONCEPTS_DIR) -> tuple[dict[str, Any], list[str]]:
    """파일명 → 파싱된 JSON. 읽지 못한 파일은 오류 문자열로 돌려준다."""
    raw: dict[str, Any] = {}
    errors: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            raw[path.name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: 읽을 수 없습니다 — {exc}")
    return raw, errors


def validate_seeds(
    raw: dict[str, Any],
    taxonomy: Taxonomy,
) -> tuple[list[ConceptSeed], list[str]]:
    """검증을 통과한 시드와 오류 목록. 오류가 하나라도 있으면 아무것도 쓰면 안 된다."""
    parsed: list[tuple[str, ConceptSeed]] = []
    errors: list[str] = []

    for filename, data in raw.items():
        try:
            seed = ConceptSeed.model_validate(data)
        except ValidationError as exc:
            errors.extend(f"{filename}: {_format_error(detail)}" for detail in exc.errors())
            continue
        parsed.append((filename, seed))

    known_slugs = {seed.slug for _, seed in parsed}
    for filename, seed in parsed:
        errors.extend(
            f"{filename}: {reason}" for reason in _check(filename, seed, taxonomy, known_slugs)
        )

    if errors:
        return [], errors
    return [seed for _, seed in parsed], []


def collect_seeds(
    directory: Path = CONCEPTS_DIR,
    taxonomy: Taxonomy | None = None,
) -> tuple[list[ConceptSeed], list[str]]:
    raw, errors = load_raw_seeds(directory)
    seeds, validation_errors = validate_seeds(raw, taxonomy or get_taxonomy())
    return seeds, errors + validation_errors


def _format_error(detail: dict[str, Any]) -> str:
    location = ".".join(str(part) for part in detail["loc"]) or "(최상위)"
    return f"{location} — {detail['msg']}"


def _check(filename: str, seed: ConceptSeed, taxonomy: Taxonomy, known: set[str]) -> list[str]:
    reasons: list[str] = []

    if Path(filename).stem != seed.slug:
        reasons.append(f"파일명이 slug 와 다릅니다 (slug={seed.slug})")

    if not taxonomy.has(seed.category):
        reasons.append(f"taxonomy 에 없는 분류입니다: {seed.category}")
    for category in seed.extra_categories or []:
        if not taxonomy.has(category):
            reasons.append(f"taxonomy 에 없는 분류입니다(extraCategories): {category}")

    for item in seed.related or []:
        if item.slug not in known:
            reasons.append(f"related 가 없는 개념을 가리킵니다: {item.slug}")

    for slug in LINK_RE.findall(seed.body):
        if slug not in known:
            reasons.append(f"본문 링크가 없는 개념을 가리킵니다: {slug}")

    for section in OPTIONAL_SECTIONS:
        if getattr(seed, section) == []:
            reasons.append(f"선택 섹션이 빈 배열입니다({section}). 없으면 null 로 둡니다")

    return reasons


async def run(force: bool) -> int:
    seeds, errors = collect_seeds()
    if errors:
        print("시드 검증 실패. 아무것도 쓰지 않았습니다.", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    if not seeds:
        print(f"{CONCEPTS_DIR} 에 시드 파일이 없습니다.", file=sys.stderr)
        return 1

    try:
        async with SessionLocal() as session:
            repository = ConceptRepository(session)
            existing = await repository.count()
            if existing and not force:
                print(f"이미 {existing}개 있음, --force 로 갱신")
                return 0
            written = await repository.upsert_many([seed.to_row() for seed in seeds])
            await session.commit()
    except OSError as exc:
        print(f"DB 에 연결할 수 없습니다 — {exc}", file=sys.stderr)
        print("docker compose up -d 로 DB 를 먼저 띄웁니다.", file=sys.stderr)
        return 1
    except ProgrammingError as exc:
        print(f"concepts 테이블에 접근할 수 없습니다 — {exc}", file=sys.stderr)
        print("uv run alembic upgrade head 로 스키마를 먼저 맞춥니다.", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    print(f"개념 {written}개 적재 완료")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="개념 시드를 DB 에 적재한다")
    parser.add_argument("--force", action="store_true", help="이미 들어 있어도 전부 갱신한다")
    args = parser.parse_args()
    return asyncio.run(run(args.force))


if __name__ == "__main__":
    raise SystemExit(main())
