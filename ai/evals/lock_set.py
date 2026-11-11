"""eval 세트 잠금 기록. 케이스 입력·gold 의 해시를 `gold.lock.json` 에 남기고, 잠금 뒤 변경됐는지 확인한다.

    python3 evals/lock_set.py --write --version v0 [--provisional]   # 잠금 기록 작성
    python3 evals/lock_set.py --check                                # 기록과 현재 파일 비교(다르면 종료 코드 1)

해시 대상: 케이스마다 case.json, provenance.json, gold.json(`verification` 칸과 `status` 는 뺀 내용).
케이스 폴더: cases/(안 A, 구형 입력)와 cases_live/(안 B, 실서비스 형식 입력). 기록 키는 cases/ 케이스는 폴더 이름 그대로,
cases_live/ 케이스는 `cases_live/<폴더>` 다. cases/ 키를 그대로 두어 cases/ 만 잠근 예전 기록도 --check 로 비교할 수 있다.
cases_live_pending/(사람 검증 전 보류 케이스)은 잠그지 않는다.
`verification` 은 검증을 진행하며 채우는 칸이라 해시에 넣으면 검증 기록을 쓰는 순간 잠금이 깨진다.
표준 라이브러리만 쓴다. ai/ 폴더에서 실행한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

EVALS = Path(__file__).parent
CASES = EVALS / "cases"
# (폴더, 기록 키 접두사). 폴더가 없으면 건너뛴다
CASE_ROOTS = ((CASES, ""), (EVALS / "cases_live", "cases_live/"))
LOCK = EVALS / "gold.lock.json"
EXCLUDE_GOLD_KEYS = ("verification", "status")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def case_hashes(d: Path) -> dict:
    gold = json.loads((d / "gold.json").read_text(encoding="utf-8"))
    for k in EXCLUDE_GOLD_KEYS:
        gold.pop(k, None)
    return {
        "case_json": sha(canonical(json.loads((d / "case.json").read_text(encoding="utf-8")))),
        "provenance_json": sha(canonical(json.loads((d / "provenance.json").read_text(encoding="utf-8")))),
        "gold_json": sha(canonical(gold)),
    }


def current() -> dict:
    out = {}
    for root, prefix in CASE_ROOTS:
        if not root.is_dir():
            continue
        for d in sorted(d for d in root.iterdir() if d.is_dir() and (d / "gold.json").exists()):
            out[prefix + d.name] = case_hashes(d)
    return out


def set_hash(cases: dict) -> str:
    return sha(canonical(cases))


def write(version: str, provisional: bool) -> int:
    cases = current()
    kst = timezone(timedelta(hours=9))
    lock = {
        "set_version": version,
        "lock_status": "provisional" if provisional else "locked",
        "locked_at": datetime.now(kst).isoformat(timespec="seconds"),
        "set_hash": set_hash(cases),
        "n_cases": len(cases),
        "note": (
            "잠정 잠금. 체크리스트·블라인드 재라벨링·verification 이 끝나지 않음. 정식 잠금 전에 gold 를 고치면 "
            "--write 로 기록을 다시 만들고 세트 버전을 올림"
            if provisional
            else "정식 잠금. 이후 gold 를 고치면 세트 버전을 올리고 baseline 을 다시 돌림"
        ),
        "hash_scope": "case.json, provenance.json, gold.json(verification·status 제외), JSON 정규화(키 정렬) 후 sha256",
        "case_roots": [root.relative_to(EVALS).as_posix() for root, _ in CASE_ROOTS if root.is_dir()],
        "cases": cases,
    }
    LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"기록함: {LOCK.name}  버전 {version}  상태 {lock['lock_status']}  세트 해시 {lock['set_hash'][:12]}…  케이스 {len(cases)}건")
    return 0


def check() -> int:
    if not LOCK.exists():
        print("gold.lock.json 이 없음")
        return 1
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    now = current()
    diffs = []
    for name in sorted(set(lock["cases"]) | set(now)):
        old, new = lock["cases"].get(name), now.get(name)
        if old is None:
            diffs.append(f"{name}: 잠금 기록에 없는 새 케이스")
        elif new is None:
            diffs.append(f"{name}: 잠금 뒤 사라진 케이스")
        else:
            for k in old:
                if old[k] != new.get(k):
                    diffs.append(f"{name}: {k.replace('_json', '.json')} 가 잠금 뒤 바뀜")
    print(f"세트 버전 {lock['set_version']} ({lock['lock_status']}), 기록 시각 {lock['locked_at']}")
    if diffs:
        print("잠금 이후 변경됨:")
        for m in diffs:
            print(f"  ✗ {m}")
        print("정상 변경이면 세트 버전을 올리고 --write 로 다시 기록함")
        return 1
    print(f"변경 없음 (세트 해시 {lock['set_hash'][:12]}…)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="eval 세트 잠금 기록·확인")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true", help="잠금 기록 작성")
    g.add_argument("--check", action="store_true", help="기록과 현재 파일 비교")
    ap.add_argument("--version", help="세트 버전(예: v0). --write 에 필요")
    ap.add_argument("--provisional", action="store_true", help="잠정 잠금으로 기록")
    args = ap.parse_args()
    if args.write:
        if not args.version:
            ap.error("--write 에는 --version 이 필요함")
        return write(args.version, args.provisional)
    return check()


if __name__ == "__main__":
    sys.exit(main())
