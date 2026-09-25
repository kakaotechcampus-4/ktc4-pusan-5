"""뉴스 발췌 방식 비교 실행기. 순서와 이유는 __init__.py 를 본다.

    uv run python -m app.services.news_link.compare prepare
    uv run python -m app.services.news_link.compare run
    uv run python -m app.services.news_link.compare score

작업 폴더(--dir, 기본 eval_data/news_compare)의 파일:

    cases.csv    (사람이 채움)  url, 종목, 유형
    articles.json  prepare 가 만든다. 기사 본문과 문장 목록
    sheet.md       prepare 가 만든다. 번호 붙은 문장. 정답을 적을 때 읽는다
    labels.csv   (사람이 채움)  정답 문장 번호
    outputs.json   run 이 만든다. 세 방식의 결과. 이미 돌린 쌍은 다시 돌리지 않는다
    review.csv   (사람이 채움)  B·C 채점
    report.md      score 가 만든다

CSV 는 엑셀에서 열고 고친다고 보고 BOM 을 붙여 쓴다(utf-8-sig). 엑셀이 "CSV" 로
저장하면 cp949 가 되므로 읽을 때는 둘 다 받는다.
"""

import argparse
import asyncio
import csv
import hashlib
import json
import sys
from pathlib import Path

from app.core.config import settings
from app.llm.client import endpoint
from app.services.news_link.compare.methods import (
    SELECT_PROMPT,
    SUMMARY_PROMPT,
    method_a,
    method_b,
    method_c,
    numbered,
    prompt_sha,
    says_none,
    selected_text,
)
from app.services.news_link.compare.score import parse_answer, parse_mark, render_report
from app.services.news_link.compare.verify import verify_summary
from app.services.news_link.fetch import fetch_link_bodies
from app.services.news_link.sentence import split_sentences

DEFAULT_DIR = Path("eval_data/news_compare")

# prepare 는 본문 **전체**가 필요하다. fetch_link 에 상한을 사실상 없게 주면
# first_sentences 가 본문을 통째로 돌려준다. 수집 경로(리다이렉트·인코딩·정제)를
# 운영 코드와 똑같이 타게 하려고 따로 만들지 않았다.
WHOLE_BODY = 10**9

# 한꺼번에 보내는 LLM 호출 수. 한 쌍의 B·C 는 차례로 보낸다.
# 프로바이더에 한꺼번에 몰면 429 가 온다. Elice 속도 제한은 기관별이라 --concurrency 로 줄인다.
LLM_CONCURRENCY = 3

CASE_FIELDS = ["url", "종목", "유형", "메모"]
LABEL_FIELDS = ["id", "유형", "종목", "제목", "문장수", "이유(한 줄)", "정답 문장", "메모"]
REVIEW_FIELDS = ["id", "종목", "방식", "결과", "이유 포함", "원문에 없는 내용", "뜻 통함", "메모"]
# review.csv 에서 사람이 적는 칸 → score 가 쓰는 이름
REVIEW_MARKS = {"이유 포함": "reason", "원문에 없는 내용": "invented", "뜻 통함": "sense"}
# B 의 "이유 포함" 은 정답 번호로 자동 채점되고, "원문에 없는 내용" 은 구조상 없다.
AUTO = "(자동)"

LABEL_GUIDE = """\
# 정답 표시용 시트

각 (기사, 종목) 에 대해 labels.csv 에 두 칸을 적는다. **run 을 돌리기 전에 적는다.**

- **이유(한 줄)**: 이 기사가 말하는, 이 종목의 주가를 움직였거나 움직일 만한 원인
- **정답 문장**: 그 원인을 설명하는 데 **꼭 필요한** 문장 번호. `6,7,8` 또는 `6-8`
  - 고른 문장만 읽어도 뜻이 통해야 한다. "이 회사는" 처럼 앞을 가리키면 그 문장도 넣는다
  - 기사에 이 종목의 원인이 없으면 `-`

모델(B)에게 준 기준과 같다. 기준이 다르면 채점이 아니라 기준 차이를 재게 된다.
"""


def case_id(url: str, stock: str) -> str:
    """(url, 종목) 으로 정해지는 id. cases.csv 순서를 바꿔도 적어둔 정답이 안 어긋난다."""
    return hashlib.sha1(f"{url}|{stock}".encode()).hexdigest()[:6]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        sys.exit(f"{path.name} 의 인코딩을 읽지 못했다. 'CSV UTF-8' 로 다시 저장할 것")
    return [
        {k.strip(): (v or "").strip() for k, v in row.items() if k}
        for row in csv.DictReader(text.splitlines())
    ]


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# --- prepare ---------------------------------------------------------------


async def prepare(work: Path) -> None:
    cases_path = work / "cases.csv"
    cases = [c for c in read_csv(cases_path) if c.get("url") and c.get("종목")]
    if not cases:
        if not cases_path.exists():
            write_csv(cases_path, CASE_FIELDS, [])
        sys.exit(
            f"{cases_path} 에 기사를 채운다. 한 줄 = (기사 url, 종목, 유형).\n"
            "  유형 예: 단일종목 / 시황 / 텔레그램. 같은 기사를 종목만 바꿔 여러 줄 넣어도 된다."
        )

    bodies = await fetch_link_bodies(
        list(dict.fromkeys(c["url"] for c in cases)), sentences=WHOLE_BODY, max_chars=WHOLE_BODY
    )
    by_url = {b.url: b for b in bodies}

    articles: dict[str, dict] = {}
    for case in cases:
        body = by_url.get(case["url"])
        text = (body.excerpt or "") if body else ""
        cid = case_id(case["url"], case["종목"])
        articles[cid] = {
            "id": cid,
            "url": case["url"],
            "stock": case["종목"],
            "kind": case.get("유형", ""),
            "status": body.status if body else "not_fetchable",
            "domain": body.domain if body else None,
            "final_url": body.final_url if body else None,
            "title": body.title if body else None,
            "fetched_at": body.fetched_at.isoformat() if body else None,
            "body": text,
            "sentences": split_sentences(text),
        }
    save_json(work / "articles.json", articles)

    usable = [a for a in articles.values() if a["sentences"]]
    sheet = [LABEL_GUIDE]
    for a in usable:
        sheet += [
            f"\n## {a['id']} · {a['stock']} · {a['kind'] or '유형 없음'}",
            f"\n{a['title'] or '(제목 없음)'} — {a['domain']}\n",
            "```",
            numbered(a["sentences"]),
            "```",
        ]
    (work / "sheet.md").write_text("\n".join(sheet) + "\n", encoding="utf-8")

    # 이미 적어둔 정답은 지키고 새 쌍만 덧붙인다. 기사를 추가하려고 prepare 를
    # 다시 돌렸다가 한 시간 들여 적은 정답이 날아가면 안 된다.
    existing = {row["id"]: row for row in read_csv(work / "labels.csv")}
    labels = []
    for a in usable:
        row = existing.get(a["id"], {})
        labels.append({
            "id": a["id"], "유형": a["kind"], "종목": a["stock"], "제목": a["title"],
            "문장수": len(a["sentences"]),
            "이유(한 줄)": row.get("이유(한 줄)", ""),
            "정답 문장": row.get("정답 문장", ""),
            "메모": row.get("메모", ""),
        })
    write_csv(work / "labels.csv", LABEL_FIELDS, labels)

    print(f"기사 {len(articles)}쌍 중 본문을 읽은 것 {len(usable)}쌍")
    for a in articles.values():
        if not a["sentences"]:
            print(f"  제외 {a['id']} {a['domain'] or a['url']} — {a['status']}")
    print(f"\n다음: {work / 'sheet.md'} 를 읽고 {work / 'labels.csv'} 에 정답을 적는다.")


# --- run -------------------------------------------------------------------


def load_answers(work: Path, articles: dict) -> dict[str, set[int]]:
    """정답을 읽는다. 하나라도 비어 있거나 범위를 벗어나면 멈춘다."""
    answers: dict[str, set[int]] = {}
    problems: list[str] = []
    for row in read_csv(work / "labels.csv"):
        article = articles.get(row.get("id", ""))
        if not article or not article["sentences"]:
            continue
        try:
            answer = parse_answer(row.get("정답 문장"))
        except ValueError as exc:
            problems.append(f"  {row['id']} {row.get('종목')}: {exc}")
            continue
        if answer is None:
            problems.append(f"  {row['id']} {row.get('종목')}: 정답 문장이 비어 있다")
            continue
        over = [n for n in answer if n > len(article["sentences"])]
        if over:
            problems.append(
                f"  {row['id']} {row.get('종목')}: {over} 번 문장이 없다 "
                f"(문장 {len(article['sentences'])}개)"
            )
            continue
        answers[row["id"]] = answer
    labeled = {row.get("id") for row in read_csv(work / "labels.csv")}
    missing = [a for a in articles.values() if a["sentences"] and a["id"] not in labeled]
    problems += [f"  {a['id']} {a['stock']}: labels.csv 에 줄이 없다" for a in missing]
    if problems:
        print("정답을 먼저 다 적어야 run 을 돌린다. 결과를 보고 적으면 측정이 아니게 된다.")
        print("\n".join(problems))
        sys.exit(1)
    return answers


async def run(work: Path, rerun: bool, concurrency: int = LLM_CONCURRENCY) -> None:
    articles = load_json(work / "articles.json")
    if not articles:
        sys.exit("articles.json 이 없다. prepare 를 먼저 돌린다.")
    load_answers(work, articles)
    try:
        endpoint()  # 키·주소가 없으면 호출 전에 멈춘다
    except RuntimeError as exc:
        sys.exit(str(exc))
    print(f"모델: {settings.summary_model} ({settings.llm_provider}) · "
          f"추론 강도: {settings.summary_reasoning_effort}")

    outputs = {} if rerun else load_json(work / "outputs.json")

    current_sha = {"b": prompt_sha(SELECT_PROMPT), "c": prompt_sha(SUMMARY_PROMPT)}

    def needs(cid: str, method: str) -> bool:
        """아직 안 돌렸거나, 호출이 실패했거나, **프롬프트가 바뀐** 방식만 다시 돌린다.

        성공한 쪽까지 다시 돌리면 그만큼 비용을 또 낸다. 실패한 호출은 토큰이 0 이라
        다시 돌려도 이중 과금이 아니다. 프롬프트를 고쳤는데 옛 결과를 재사용하면
        "고쳤는데 결과가 그대로" 라는 착시가 생긴다.
        """
        old = outputs.get(cid)
        return (old is None or bool(old[method].get("error"))
                or old[method].get("prompt_sha") != current_sha[method])

    todo = [a for a in articles.values()
            if a["sentences"] and (needs(a["id"], "b") or needs(a["id"], "c"))]
    semaphore = asyncio.Semaphore(concurrency)

    async def one(a: dict) -> tuple[str, dict]:
        cid = a["id"]
        args = (a["stock"], a["title"], a["sentences"], a["body"])
        old = outputs.get(cid, {})
        async with semaphore:
            b = await method_b(*args) if needs(cid, "b") else old["b"]
            c = await method_c(*args) if needs(cid, "c") else old["c"]
        return cid, {"a": method_a(a["body"]), "b": b, "c": c}

    # 한 쌍 끝날 때마다 저장한다. 중간에 죽어도 이미 낸 호출 비용을 다시 쓰지 않는다.
    failed: list[str] = []
    for done, task in enumerate(asyncio.as_completed([one(a) for a in todo]), 1):
        cid, result = await task
        outputs[cid] = result
        save_json(work / "outputs.json", outputs)
        errors = [f"{m.upper()} {result[m]['error']}" for m in ("b", "c") if result[m].get("error")]
        if errors:
            failed.append(errors[0])
            flag = " (호출 실패)"
        elif result["b"]["fallback"]:
            flag = " (B 규칙 위반 → A 대체)"
        else:
            flag = ""
        print(f"  {done}/{len(todo)} {cid} {articles[cid]['stock']}{flag}")

    if failed:
        # 같은 원인이면 메시지가 전부 같다. 첫 줄만 보여줘도 무엇을 고칠지 보인다.
        print(f"\n호출 실패 {len(failed)}쌍. 첫 오류:\n  {failed[0]}")
        print("원인을 고친 뒤 run 을 다시 돌리면 **실패한 호출만** 다시 한다.")
        sys.exit(1)
    write_review(work, articles, outputs)
    print(f"\n다음: {work / 'review.csv'} 에 B·C 를 채점하고 score 를 돌린다.")


def write_review(work: Path, articles: dict, outputs: dict) -> None:
    """사람 채점표. 이미 적은 칸은 **결과가 그대로일 때만** 지킨다.

    프롬프트를 고쳐 다시 돌리면 결과 글이 바뀐다. 옛 글에 매긴 Y/N 을 새 글에 붙여 두면
    채점하지 않은 결과가 채점된 것처럼 셈해진다.
    """
    existing = {(r["id"], r["방식"]): r for r in read_csv(work / "review.csv")}
    rows = []
    for cid, out in outputs.items():
        a = articles[cid]
        b_text = selected_text(a["sentences"], out["b"]["selected"])
        for method, text in (("B", b_text or "(빈 목록 — 원인 없음)"),
                             ("C", out["c"]["text"] or f"(오류: {out['c']['error']})")):
            old = existing.get((cid, method), {})
            if old.get("결과") != text:
                old = {}
            row = {"id": cid, "종목": a["stock"], "방식": method, "결과": text,
                   "메모": old.get("메모", "")}
            for field in REVIEW_MARKS:
                auto = method == "B" and field in ("이유 포함", "원문에 없는 내용")
                row[field] = AUTO if auto else old.get(field, "")
            rows.append(row)
    write_csv(work / "review.csv", REVIEW_FIELDS, rows)


# --- score -----------------------------------------------------------------


def score(work: Path) -> None:
    articles = load_json(work / "articles.json")
    outputs = load_json(work / "outputs.json")
    if not outputs:
        sys.exit("outputs.json 이 없다. run 을 먼저 돌린다.")
    # 호출 실패를 채점에 넣으면 B 는 A 로, C 는 빈 글로 셈해져 둘 다 억울하게 진다.
    failed = [cid for cid, out in outputs.items() if out["b"].get("error") or out["c"].get("error")]
    if failed:
        sys.exit(f"호출이 실패한 쌍 {len(failed)}개가 남아 있다. run 을 다시 돌려 채운 뒤 채점한다.")
    answers = load_answers(work, articles)
    review: dict[str, dict] = {}
    for r in read_csv(work / "review.csv"):
        for column, field in REVIEW_MARKS.items():
            mark = parse_mark(r.get(column))
            if mark is not None:
                review.setdefault(r["id"], {})[(r["방식"], field)] = mark

    rows = []
    for cid, out in outputs.items():
        a = articles[cid]
        rows.append({
            "id": cid, "kind": a["kind"], "stock": a["stock"], "answer": answers[cid],
            "a": out["a"], "b": out["b"]["selected"], "b_fallback": out["b"]["fallback"],
            "a_chars": len(selected_text(a["sentences"], out["a"])),
            "b_chars": len(selected_text(a["sentences"], out["b"]["selected"])),
            "c_chars": len(out["c"]["text"]),
            "c_none": says_none(out["c"]["text"]),
            # 채점할 때 계산한다. LLM 을 다시 부르지 않고 규칙만 바꿔 다시 볼 수 있다.
            "c_flags": verify_summary(out["c"]["text"], a["stock"], a["title"], a["body"]),
            # 앞 문장을 코드가 몇 개 붙였나. 옛 outputs(v1)에는 model_selected 가 없다.
            "b_context_added": len(out["b"]["selected"])
            - len(out["b"].get("model_selected") or out["b"]["selected"]),
            "b_cost": out["b"]["cost"], "c_cost": out["c"]["cost"],
            "review": review.get(cid, {}),
        })
    skipped = [a for a in articles.values() if not a["sentences"]]
    report = render_report(rows, skipped)
    (work / "report.md").write_text(report, encoding="utf-8")
    print(report)


def main() -> None:
    parser = argparse.ArgumentParser(description="뉴스 발췌 방식 비교 (A 앞 3문장 / B 번호 선택 / C 요약)")
    parser.add_argument("step", choices=["prepare", "run", "score"])
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="작업 폴더")
    parser.add_argument("--rerun", action="store_true", help="run: 이미 돌린 쌍도 다시 돌린다 (비용 발생)")
    parser.add_argument("--concurrency", type=int, default=LLM_CONCURRENCY,
                        help="run: 한꺼번에 보내는 호출 수. 429(속도 제한)가 나면 1 로 줄인다")
    args = parser.parse_args()
    args.dir.mkdir(parents=True, exist_ok=True)
    # 한국어 Windows 콘솔은 cp949 라 '—' 같은 글자에서 print 가 죽는다.
    # 출력 한 글자 때문에 다 받아둔 기사를 저장 못 하고 끝나면 안 된다.
    sys.stdout.reconfigure(errors="replace")

    if args.step == "prepare":
        asyncio.run(prepare(args.dir))
    elif args.step == "run":
        asyncio.run(run(args.dir, args.rerun, max(args.concurrency, 1)))
    else:
        score(args.dir)


if __name__ == "__main__":
    main()
