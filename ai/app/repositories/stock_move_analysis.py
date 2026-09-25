"""보고서 JSON 을 읽어 DB 에 넣는다. 파싱 → 정규화 → (받아온 판정과 함께) INSERT.

## 이 모듈이 파이프라인의 어디인가

    ① 텔레그램 수집       증권 채널 메시지를 긁는다
    ② 필터 · 태깅         종목·시각으로 거르고 메시지마다 direct/indirect 를 붙인다
    ③ 보고서 생성 (LLM)   입력 JSON 하나를 주고 보고서 JSON 하나를 받는다
    ④ 실행 기록 래핑      러너가 보고서를 실행 지표로 감싸 runs/<타임스탬프>/parsed/ 에 쓴다
    ⑤ 근거 검증 · 점검    quote 가 원문에 정말 있는지, 상한을 지켰는지 본다
  ▶ ⑥ 적재  ← 이 파일    파일을 읽어 DB 에 넣는다. 판정은 ⑤ 에서 받아온다
    ⑦ 조회 (backend)     verify_status = passed 인 행만 읽어 화면에 낸다

①~⑤ 는 실험 레포에 있고 이번에 옮겨오지 않았다. 지금은 ④ 의 산출물을 **사람이**
runs/ 에서 복사해 두면 ⑥ 이 읽는다. ⑤ 와의 연결도 후속 PR 이라, verify_status 는
이 모듈이 정하지 않고 인자로 받는다.

입력 테이블을 따로 두지 않는 이유: ③ 의 결과는 매 실행마다 새로 만들어지는 일회성
산출물이라 원본을 DB 에 쌓을 이유가 없다. 수집 원본(analyst_reports, news)이 DB 에
있는 것과는 성격이 다르다. 원본이 필요하면 적재된 행의 raw_json 에 통째로 있다.

## 보고서 한 편이 무엇인가

"2026-09-18 15:30 기준으로 삼성전자가 왜 3.37% 올랐나" 에 답하는 문서 하나다.
LLM 은 ② 가 넘긴 메시지 묶음 **안에서만** 근거를 찾는다(웹 검색을 막아 뒀다).
같은 종목이라도 그 시각까지 들어온 메시지가 다르면 다른 보고서가 나온다.

칸은 여섯이고 화면에서 가는 곳이 다르다.

    verdict      판정. 화면 맨 위
    summary      맨 위 요약 네 칸 (move / main_cause / counter / unexplained)
    factors      아래 「이유」 절. main_cause 의 상세판이다
    terms        본문의 풀어 쓴 표현에 색을 입히고, 올리면 원래 전문용어를 띄운다
    background   「참고」 절. 원인은 아니지만 그날 있었던 재료
    not_found    **검수자만 본다.** 화면에 나가지 않는다

판정은 세 종류다. 어느 것이냐에 따라 뒤 칸의 모양이 달라진다.

    explained            사건 하나만으로 등락 폭이 설명된다
    partially_explained  방향은 맞지만 폭의 일부만 설명한다
    no_clear_cause       원인을 못 찾았다. factors 가 **빈 배열**이고 counter 는 null 이다
                         (등락률이 ±1% 이내면 무조건 여기다 — 그 구간의 질문은
                          "왜 움직였나" 가 아니라 "큰 재료가 있었는데 왜 안 움직였나" 다)

## 입력 파일은 2단이다

바깥은 ④ 가 씌운 실행 기록 래퍼고, 보고서 JSON 은 `final_text` 안에 **문자열로**
들어 있다. 래퍼를 열고 → final_text 를 다시 파싱한다. 한 번만 파싱하면 보고서가
아니라 실행 지표가 나온다.

래퍼에서 읽는 것은 다섯 개뿐이다.

    final_text       보고서 JSON 문자열. 적재 대상
    json_status      러너가 본 파싱 상태. clean 이 정상
    schema_problems  점검 스크립트가 찾은 스키마 위반 목록
    is_error         실행 자체가 실패
    asked_question   모델이 사람에게 되물었다. 자동 실행이라 답할 사람이 없어 금지돼 있다

나머지는 의도적으로 흘려보낸다.

    - 툴 지표(n_tool_calls·tool_sequence·queries·n_urls_seen)는 툴을 막아 둬서 언제나 0 이다
    - pubdate_* 는 당일 생성으로 바뀌면서 의미가 없어졌다. **실패 판정에 쓰지 않는다**
    - verdict·n_factors·n_sources 는 final_text 안의 값을 러너가 다시 센 것이다.
      두 군데 두면 어긋났을 때 무엇을 믿을지 문제가 된다. 단일 출처는 final_text 다
    - duration_ms·cost_usd 는 운영 지표라 보고서 표에 넣지 않는다

래퍼는 실험 환경 산출물이라 필드가 늘거나 준다. 모르는 필드에 걸려 죽으면 적재가
통째로 멈추므로 위 다섯 개만 보고 나머지는 쳐다보지 않는다.

## 깨진 건도 버리지 않는다

파싱 실패·스키마 위반·실행 실패 전부 상태만 달아 적재한다. 왜 깨졌는지는 그 행을
봐야 알 수 있는데, 버리면 그 자료가 사라진다. 그래서 정규화 칼럼은 거의 전부
nullable 이고 값이 이상하면 NULL 로 빠진다. 원본은 raw_json 에 남는다.

`parse_status` 는 적재가 본 것이고 `verify_status` 는 ⑤ 의 판정이다. 둘은 다르다 —
문법은 멀쩡한데 인용문이 원문에 없는 보고서가 있고(parse ok / verify failed),
스키마를 어겼지만 근거는 멀쩡한 보고서도 있다.
"""

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock_move_analysis import (
    StockMoveAnalysis,
    StockMoveAnalysisFactor,
    StockMoveAnalysisFactorSource,
)

logger = logging.getLogger(__name__)

# 프롬프트의 as_of 는 "HH:MM" 뿐이라 날짜와 합칠 때 타임존을 우리가 붙여야 한다.
# 대상이 한국 증시 장중 시각이므로 KST 고정이다. 루트 CLAUDE.md 가 naive datetime 을 금지한다.
KST = timezone(timedelta(hours=9))

# 시스템 프롬프트가 정한 상한이다. 본문보다 참고란이 길면 읽히지 않아서 걸어 둔 것이지
# 기술적 제약이 아니다. **초과해도 잘라내지 않는다** — 자세한 근거는 아래 함수에 있다.
MAX_FACTORS = 4  # 원인. 중요도 순
MAX_TERMS = 8  # 용어 풀이
MAX_BACKGROUND_TOTAL = 6  # 참고 재료 전체
MAX_BACKGROUND_PER_SLOT = 3  # 참고 재료, 칸 하나당

# background 는 사건 자체의 성질로 세 칸에 나뉜다. 그날 등락 방향과는 무관한 분류다 —
# 주가를 올릴 성질이면 bullish, 내릴 성질이면 bearish, 단정하기 어려우면 neutral.
BACKGROUND_SLOTS = ("bullish", "bearish", "neutral")


class ParsedAnalysis:
    """파일 하나를 편 결과. DB 에 넣기 직전 형태다.

    파싱이 깨진 건도 여기까지는 온다 — 버리지 않고 상태만 달아 적재하기 때문이다.
    그때 `analysis` 는 비고 `raw_json` 에 래퍼가 통째로 들어 있다.
    """

    def __init__(
        self,
        *,
        run_id: str | None,
        analysis: dict[str, Any],
        raw_json: dict[str, Any],
        parse_status: str,
        parse_error: str | None,
    ) -> None:
        # 러너가 붙인 실행 식별자. `<종목>-<날짜>-<조건>__<반복>` 꼴이라 이 값 하나로
        # runs/<타임스탬프>/parsed/<run_id>.json 을 다시 열 수 있다.
        self.run_id = run_id
        self.analysis = analysis  # final_text 를 편 보고서 본문. 실패하면 빈 dict
        self.raw_json = raw_json  # 통째로 보존할 원본
        self.parse_status = parse_status  # ok | schema_violation | parse_failed
        self.parse_error = parse_error


def _failed(run_id: str | None, raw_json: dict[str, Any], reason: str) -> ParsedAnalysis:
    """파싱이 깨진 건. **버리지 않는다** — 원인 분석 자료가 사라진다."""
    return ParsedAnalysis(
        run_id=run_id, analysis={}, raw_json=raw_json, parse_status="parse_failed", parse_error=reason
    )


def parse_analysis_file(path: Path) -> ParsedAnalysis:
    """래퍼 파일 하나를 연다. 어떤 입력이 와도 예외를 던지지 않는다.

    적재가 멈추면 안 되는 자리다. 배치가 수십 건을 도는 중에 파일 하나가 깨졌다고
    예외가 올라가면 뒤의 멀쩡한 건까지 못 들어간다. 파일이 JSON 이 아니든 final_text 가
    없든 상태만 달아 넘기고, 원본은 raw_json 에 남긴다.
    """
    text = path.read_text(encoding="utf-8")
    try:
        wrapper = json.loads(text)
    except json.JSONDecodeError as e:
        # 파일 자체가 JSON 이 아니면 JSONB 에 넣을 객체가 없다. 원문을 감싸서라도 남긴다.
        return _failed(path.stem, {"_unparsed_text": text}, f"래퍼 JSON 파싱 실패: {e}")
    if not isinstance(wrapper, dict):
        return _failed(
            path.stem, {"_unparsed_text": text}, f"래퍼가 객체가 아니다: {type(wrapper).__name__}"
        )
    # run_id 는 래퍼 안에도 있지만 없을 수 있어 파일명을 예비로 넘긴다.
    return parse_wrapper(wrapper, fallback_run_id=path.stem)


def parse_wrapper(wrapper: dict[str, Any], *, fallback_run_id: str | None = None) -> ParsedAnalysis:
    """실행 기록 래퍼에서 보고서 JSON 을 꺼낸다. 다섯 필드만 본다(모듈 docstring 참고)."""
    run_id = wrapper.get("run_id") or fallback_run_id

    # 프롬프트가 "첫 글자는 { 이고 마지막 글자는 }" 라고 못박아 뒀지만 모델이 코드펜스나
    # 머리말을 붙이는 날이 있다. 그러면 여기서 파싱이 깨진다 — 그것도 적재 대상이다.
    final_text = wrapper.get("final_text")
    if not isinstance(final_text, str) or not final_text.strip():
        return _failed(run_id, wrapper, "final_text 가 없거나 비어 있다")

    try:
        analysis = json.loads(final_text)
    except json.JSONDecodeError as e:
        return _failed(run_id, wrapper, f"final_text JSON 파싱 실패: {e}")
    if not isinstance(analysis, dict):
        return _failed(run_id, wrapper, f"보고서가 객체가 아니다: {type(analysis).__name__}")

    # 여기부터는 JSON 으로 열리기는 한 회차다. 다만 그대로 믿으면 안 되는 것들이 있다.
    # 넷은 원인이 다르지만 "이 산출물을 서비스에 내보내면 안 된다" 는 뜻은 같아서
    # 한 상태로 묶는다. 무엇이 걸렸는지는 parse_error 가 줄 단위로 말한다.
    problems: list[str] = []

    # 러너가 본 파싱 상태. clean 이 아니면 코드펜스를 벗겨내는 등 손을 댔다는 뜻이라
    # 우리 쪽에서 열렸더라도 원문 그대로가 아닐 수 있다.
    json_status = wrapper.get("json_status")
    if json_status is not None and json_status != "clean":
        problems.append(f"json_status={json_status}")

    # 점검 스크립트가 찾은 스키마 위반(필수 칸 누락, 값 목록 밖의 값 등).
    # 목록을 문자열로 붙여 둔다 — 구조화가 필요해지면 parse_error 를 JSONB 로 바꾼다.
    schema_problems = wrapper.get("schema_problems")
    if isinstance(schema_problems, list) and schema_problems:
        problems.append(f"schema_problems={schema_problems}")

    # 생성이 도중에 죽은 회차. 본문이 잘려 있을 수 있다.
    if wrapper.get("is_error"):
        problems.append("is_error=true (실행 실패)")

    # 프롬프트가 되묻기를 금지한다 — 자동 실행이라 답할 사람이 없다. 되물었다는 건
    # 정보가 부족한 상황에서 진행하지 않고 멈췄다는 뜻이라 본문을 믿을 수 없다.
    if wrapper.get("asked_question"):
        problems.append("asked_question=true (되묻기 금지 위반)")

    return ParsedAnalysis(
        run_id=run_id,
        analysis=analysis,
        # 파싱 성공이면 raw_json 은 보고서 쪽이다. 래퍼의 나머지는 운영 지표라 안 남긴다.
        raw_json=analysis,
        parse_status="schema_violation" if problems else "ok",
        parse_error="\n".join(problems) if problems else None,
    )


# --- 정규화 ---------------------------------------------------------------
#
# 아래 코어서들이 하나같이 "아니면 NULL" 로 빠지는 건 게으름이 아니라 정책이다.
# LLM 이 낸 값은 타입이 어긋날 수 있는데(size_fit 에 숫자가 오는 식), 그 행에서
# 예외를 던지면 정작 원인 분석에 제일 필요한 행만 DB 에 못 들어간다. 그래서
# 이상한 값은 칼럼에서 비우고 raw_json 에 맡긴다. 모델 쪽에 ENUM·CHECK 를 걸지
# 않은 것도 같은 이유다.


def _as_str(value: Any) -> str | None:
    """문자열만 받는다. LLM 이 다른 타입을 내면 NULL 로 두고 raw_json 에 맡긴다."""
    return value if isinstance(value, str) else None


def _as_bool(value: Any) -> bool | None:
    """참/거짓만 받는다. "true" 같은 문자열은 받지 않는다 — 조용히 참으로 바뀌면
    direction_match 나 unconfirmed 가 뒤집혀서 화면 문구의 뜻이 달라진다."""
    return value if isinstance(value, bool) else None


def _as_date(value: Any) -> date | None:
    """보고서가 설명하는 대상일. 프롬프트 입력의 target_date 가 그대로 돌아온 값이다."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _as_of_datetime(target_date: date | None, raw: Any) -> datetime | None:
    """날짜 "YYYY-MM-DD" 와 시각 "HH:MM" 을 합쳐 KST aware datetime 으로 만든다.

    as_of 는 **기준 시각**이다. 이 시각까지 들어온 메시지만 보고 쓴 보고서라는 뜻이라,
    같은 날 같은 종목이라도 11:00 판과 15:30 판은 내용이 다르다. 15:30 이면 장 마감
    기준이고 그 전이면 확정값이 아니다. 자연키에 이 값이 들어가는 이유이기도 하다.

    날짜가 없으면 합칠 수 없어 NULL 이다. 원본 "15:30" 은 raw_json 에 남아 있으므로
    여기서 놓쳐도 되살릴 수 있다.
    """
    if target_date is None or not isinstance(raw, str):
        return None
    try:
        hhmm = time.fromisoformat(raw.strip())
    except ValueError:
        return None
    return datetime.combine(target_date, hhmm, tzinfo=KST)


def _as_decimal(value: Any) -> Decimal | None:
    """등락률. float 를 str 로 한 번 거쳐 Decimal 로 만든다.

    Decimal(3.37) 은 3.3700000000000001... 이 되지만 Decimal("3.37") 은 3.37 이다.
    루트 CLAUDE.md 가 가공하지 않은 값을 요구하므로 적재가 값을 흔들면 안 된다.

    이 값은 화면 표시용이기만 한 게 아니다. 판정(verdict)과 각 사건의 크기 판단이
    여기서 갈린다 — ±1% 이내면 무조건 no_clear_cause 이고, 시장 등락률을 뺀
    초과분이 factors 가 설명해야 할 몫이다. 0.01 이 흔들리면 그 판단과 어긋난다.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _parse_kst_datetime(value: Any) -> datetime | None:
    """출처 메시지가 텔레그램에 올라온 시각. 오프셋이 없으면 KST 로 본다.

    검수 때 "그 시각에 정말 이 메시지가 있었나" 를 되짚는 데 쓴다. 기준 시각 이후의
    메시지는 애초에 입력에 들어가지 않으므로, 여기 as_of 보다 늦은 값이 보이면
    모델이 시각을 지어낸 것이다.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def normalize_background(raw: Any) -> dict[str, list[dict[str, Any]]] | None:
    """background 항목의 문자열/객체 혼용을 흡수한다.

    background 는 「참고」 절이다. 그날 있었지만 주가를 설명하지는 않는 재료가 온다.
    원인(factors)·반대 재료(counter)·시장 등락에 이미 쓴 재료는 여기 다시 오지 않는다 —
    같은 내용이 두 번 나오면 독자가 새 정보로 착각하기 때문이다.

    항목은 두 형태로 온다.

        "인도네시아가 니켈 가격 계산 비율을 낮췄습니다."            ← 보통 항목
        {"text": "노사 총투표가 15~16일 진행됩니다.", "watch": true}  ← 앞으로 볼 것

    `watch` 는 "시점이 특정된 미래 사건" 이나 "되돌리기 어려운 변화" 에만 붙고,
    화면은 그 항목만 박스로 띄운다. 오늘 주가에 이미 반영된 것은 대상이 아니다.

    **둘 다 정상값이다.** 모델에게 일관성을 요구하는 대신(그러려면 프롬프트를 고쳐야
    하는데 검증 스크립트와 짝이라 못 건드린다) 적재가 `{text, watch}` 로 편다.
    화면이 매번 타입을 확인하지 않아도 되고, 원본 혼용은 raw_json 에 남는다.
    """
    if not isinstance(raw, dict):
        return None

    out: dict[str, list[dict[str, Any]]] = {}
    for slot in BACKGROUND_SLOTS:
        items = raw.get(slot)
        # 비는 칸은 빈 배열이다. 세 칸을 항상 만들어 둬야 화면이 칸 유무를 안 따진다.
        if not isinstance(items, list):
            out[slot] = []
            continue
        normalized: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, str):
                normalized.append({"text": item, "watch": False})
            elif isinstance(item, dict):
                # bool() 로 받으면 "false" 문자열이 참이 되어 박스가 뜬다. 진짜 true 만
                # 참이고 나머지(누락·문자열·숫자)는 전부 false 다 — 화면이 null 을 안 따지게
                # 여기서는 _as_bool 의 None 을 그대로 두지 않는다.
                normalized.append(
                    {"text": _as_str(item.get("text")), "watch": _as_bool(item.get("watch")) is True}
                )
            # 문자열도 객체도 아니면 버린다. 원본은 raw_json 에 있다.
        out[slot] = normalized
    return out


def normalize_terms(raw: Any) -> list[dict[str, Any]] | None:
    """용어 풀이. 본문에 쓴 **풀어 쓴 표현**과 원래 전문용어의 짝이다.

        본문   "메모리 그때그때 거래되는 시세가 한 달 새 올랐고"
        terms  {"plain": "그때그때 거래되는 시세", "term": "스팟가격"}

    화면은 본문에서 `plain` 과 **글자 그대로 일치하는** 부분을 찾아 색을 입히고,
    마우스를 올리면 `term` 을 띄운다. 그래서 한 글자만 달라도 표시되지 않는다.
    적재가 공백을 다듬거나 대소문자를 건드리면 안 되는 이유다 — 그대로 넣는다.
    """
    if not isinstance(raw, list):
        return None
    return [
        {"plain": _as_str(t.get("plain")), "term": _as_str(t.get("term"))}
        for t in raw
        if isinstance(t, dict)
    ]


def normalize_not_found(raw: Any) -> list[str] | None:
    """검수용 메모. 확인하려다 근거를 못 찾은 것, 본문을 못 읽은 링크, 애매했던 판단.

    **독자 화면에 나가지 않는다.** 그래도 담는 이유는 보고서가 틀렸을 때 모델이
    무엇을 알고 무엇을 몰랐는지 되짚을 자료가 이것뿐이어서다. 노출 제어는 backend
    응답 단계에서 한다.
    """
    if not isinstance(raw, list):
        return None
    return [n for n in raw if isinstance(n, str)]


def _log_limit_violations(run_id: str | None, analysis: dict[str, Any]) -> None:
    """상한 초과를 로그로만 남긴다. 상한 설정에 대한 유의미한 데이터는 실험을 통해
    확인할 수 없었기에, 추가적인 테스트를 통해 상한을 조정할 수 있도록 하기 위해서이다.

    적재가 말없이 자르면 두 가지를 잃는다. 하나는 잘린 내용 자체이고, 다른 하나는
    "이 프롬프트가 상한을 얼마나 자주 어기는가" 라는 관측치다. 뒤엣것이 없으면
    상한이 적절한지 판단할 근거가 영영 안 쌓인다. 위반 탐지 자체는 점검 스크립트
    담당이고 여기서는 그대로 넣은 뒤 로그에만 남긴다.
    """
    factors = analysis.get("factors")
    if isinstance(factors, list) and len(factors) > MAX_FACTORS:
        logger.warning("%s: factors %d개 (상한 %d)", run_id, len(factors), MAX_FACTORS)

    terms = analysis.get("terms")
    if isinstance(terms, list) and len(terms) > MAX_TERMS:
        logger.warning("%s: terms %d개 (상한 %d)", run_id, len(terms), MAX_TERMS)

    background = analysis.get("background")
    if isinstance(background, dict):
        total = 0
        for slot in BACKGROUND_SLOTS:
            items = background.get(slot)
            if not isinstance(items, list):
                continue
            total += len(items)
            if len(items) > MAX_BACKGROUND_PER_SLOT:
                logger.warning(
                    "%s: background.%s %d개 (칸당 상한 %d)",
                    run_id,
                    slot,
                    len(items),
                    MAX_BACKGROUND_PER_SLOT,
                )
        if total > MAX_BACKGROUND_TOTAL:
            logger.warning(
                "%s: background 전체 %d개 (상한 %d)", run_id, total, MAX_BACKGROUND_TOTAL
            )


def build_analysis(
    parsed: ParsedAnalysis,
    *,
    verify_status: str = "not_verified",
    verify_error: str | None = None,
    generated_at: datetime | None = None,
    prompt_version: str | None = None,
    source: str = "telegram",
) -> StockMoveAnalysis:
    """ParsedAnalysis → 아직 DB 에 넣지 않은 ORM 객체.

    `verify_status` 는 **인자다.** 이 함수가 근거 검증을 수행하지 않는다 —
    판정과 적재를 분리해야 한쪽을 고쳐도 다른 쪽이 안 흔들린다.

    `source` 는 출처의 **종류**다. 지금 입력이 텔레그램 수집뿐이라 기본값이 telegram
    이지만, 뉴스·리포트가 붙으면 부르는 쪽이 갈아 끼운다.
    """
    r = parsed.analysis
    _log_limit_violations(parsed.run_id, r)

    target_date = _as_date(r.get("date"))
    summary = r.get("summary") if isinstance(r.get("summary"), dict) else {}

    analysis = StockMoveAnalysis(
        run_id=parsed.run_id,
        ticker=_as_str(r.get("ticker")),
        name=_as_str(r.get("name")),
        target_date=target_date,
        as_of=_as_of_datetime(target_date, r.get("as_of")),
        change_pct=_as_decimal(r.get("change_pct")),
        verdict=_as_str(r.get("verdict")),
        # summary 네 칸. 화면 맨 위에 칸마다 따로 나간다.
        #   move        기준 시각·종목 등락률·시장 등락률·시장 대비 초과분
        #   main_cause  원인 요약. factors 를 줄글로 묶은 것이라 중복이 아니다
        #   counter     방향이 어긋나는 재료
        #   unexplained 설명되지 않는 폭과, 이 보고서에만 해당하는 한계
        summary_move=_as_str(summary.get("move")),
        summary_main_cause=_as_str(summary.get("main_cause")),
        # counter 는 null 이 정상값이다. 등락 방향과 어긋나는 재료가 실제로 있을 때만
        # 채워지고, no_clear_cause 인 날은 "어긋난다" 는 개념 자체가 없어 항상 null 이다.
        # 빈 문자열로 바꾸지 않는다 — 화면이 "없음" 과 "못 채움" 을 구분해야 한다.
        summary_counter=_as_str(summary.get("counter")),
        summary_unexplained=_as_str(summary.get("unexplained")),
        terms=normalize_terms(r.get("terms")),
        background=normalize_background(r.get("background")),
        not_found=normalize_not_found(r.get("not_found")),
        raw_json=parsed.raw_json,
        parse_status=parsed.parse_status,
        parse_error=parsed.parse_error,
        verify_status=verify_status,
        verify_error=verify_error,
        prompt_version=prompt_version,
        generated_at=generated_at,
    )

    # factors 는 「이유」 절이다. no_clear_cause 인 날은 빈 배열이므로 이 루프가
    # 한 번도 안 돈다 — 그것이 정상이지 적재 실패가 아니다.
    factors = r.get("factors")
    if isinstance(factors, list):
        for i, f in enumerate(factors):
            if not isinstance(f, dict):
                continue
            analysis.factors.append(_build_factor(i, f, source=source))
    return analysis


def _build_factor(index: int, f: dict[str, Any], *, source: str) -> StockMoveAnalysisFactor:
    """원인 하나와 그 출처들을 편다.

    칸의 뜻은 이렇다. 앞의 셋은 "이 사건이 정말 오늘 이 등락의 원인인가" 를
    모델이 스스로 채점한 결과다.

        claim / detail   화면에 나가는 원인 한 문장과 부연
        stance           사건 **자체**가 주가를 올릴 성질(bullish)인지 내릴 성질
                         (bearish)인지. 그날 등락 방향과 무관하게 판단한다
        direction_match  stance 가 실제 등락 방향과 맞는가. **factors 에는 true 만
                         들어온다** — false 인 사건은 summary.counter 로 간다
        size_fit         이 사건 **하나만으로** 시장 대비 초과분이 설명되는가.
                         sufficient / partial / insufficient. 판정을 가르는 값이라
                         sufficient 가 하나라도 있으면 explained 다
        unconfirmed      "~설", 커뮤니티 전언처럼 출처가 스스로 확인되지 않았다고
                         밝힌 정보에 기댄 원인인가
    """
    factor = StockMoveAnalysisFactor(
        order_index=index,  # 배열 순서가 곧 중요도 순이다
        claim=_as_str(f.get("claim")),
        detail=_as_str(f.get("detail")),
        stance=_as_str(f.get("stance")),
        direction_match=_as_bool(f.get("direction_match")),
        size_fit=_as_str(f.get("size_fit")),
        unconfirmed=_as_bool(f.get("unconfirmed")),
    )

    # 출처 없는 주장은 프롬프트가 금지하므로 최소 1개가 정상이다. 0개면 그 자체가
    # 점검 대상인데, 여기서 막지 않고 그대로 넣어 나중에 세어 볼 수 있게 둔다.
    sources = f.get("sources")
    if isinstance(sources, list):
        for j, s in enumerate(sources):
            if not isinstance(s, dict):
                continue
            factor.sources.append(
                StockMoveAnalysisFactorSource(
                    order_index=j,
                    source=source,
                    channel=_as_str(s.get("channel")),
                    # 입력 메시지에 있던 URL 그대로여야 한다. 모델이 지어낸 주소인지
                    # 검증기가 원본 메시지 목록과 대조해 가린다.
                    url=_as_str(s.get("url")),
                    datetime_kst=_parse_kst_datetime(s.get("datetime_kst")),
                    # 원문에서 글자 그대로 뜬 40자 이내 발췌. **검증의 핵심이다** —
                    # 검증기가 이 문자열을 원본 메시지에서 찾아보고, 한 글자라도
                    # 다르면 환각으로 본다. 그래서 적재가 다듬으면 안 된다.
                    quote=_as_str(s.get("quote")),
                    # 이 메시지가 종목을 직접 다루는지(direct), 업황·경쟁사만
                    # 다루는지(indirect). indirect 만으로 세운 원인은 size_fit 이
                    # partial 을 넘을 수 없다.
                    match=_as_str(s.get("match")),
                    # "코스피 마감 시황" 류. 결과를 적은 것이지 원인이 아니라서,
                    # 이게 근거로 쓰이면 "내려서 내렸다" 는 순환 논리가 된다.
                    is_market_recap=_as_bool(s.get("is_market_recap")),
                )
            )
    return factor


# --- 적재 -----------------------------------------------------------------


async def insert_analysis(
    session: AsyncSession,
    parsed: ParsedAnalysis,
    *,
    verify_status: str = "not_verified",
    verify_error: str | None = None,
    generated_at: datetime | None = None,
    prompt_version: str | None = None,
    source: str = "telegram",
) -> StockMoveAnalysis:
    """보고서 한 회차를 넣는다. **INSERT only — 기존 행을 찾지도, 고치지도 않는다.**

    같은 (ticker, target_date, as_of) 가 이미 있어도 새 행으로 쌓는다. 프롬프트가
    "이전 회차를 언급하지 않는다" 고 규정해 각 회차가 독립 문서라서다. 덮어쓰면
    "그때 무엇을 내보냈나" 를 되짚을 수 없다.

    대신 멱등하지 않다 — 같은 파일을 두 번 넣으면 행이 두 개 생긴다. 재적재가
    필요하면 부르는 쪽이 기존 행을 정리하고 넣어야 한다.
    """
    analysis = build_analysis(
        parsed,
        verify_status=verify_status,
        verify_error=verify_error,
        generated_at=generated_at,
        prompt_version=prompt_version,
        source=source,
    )
    session.add(analysis)
    # flush 까지만 한다. id 가 필요한 호출자를 위해서이고, 커밋 경계는 아래 설명 참고.
    await session.flush()
    return analysis


async def insert_analysis_files(
    session: AsyncSession,
    paths: list[Path],
    *,
    verdicts: dict[str, tuple[str, str | None]] | None = None,
    generated_at: datetime | None = None,
    prompt_version: str | None = None,
) -> list[StockMoveAnalysis]:
    """parsed/*.json 여러 개를 한 트랜잭션으로 넣는다. 배치의 진입점이다.

    `verdicts` 는 run_id → (verify_status, verify_error) 다. 근거 검증 결과를
    **받아서** 채우는 자리이며 없으면 전부 not_verified 로 들어간다. 미검증 행은
    backend 조회(verify_status = passed)에 걸리지 않으므로 화면으로 새지 않는다.
    검증기 연결은 후속 PR 이다.

    커밋은 부르는 쪽이 한다 — 실행 하나를 통째로 한 단위로 볼지 파일마다 끊을지는
    배치가 정할 일이지 리포지토리가 정할 일이 아니다.
    """
    verdicts = verdicts or {}
    inserted: list[StockMoveAnalysis] = []
    for path in paths:
        parsed = parse_analysis_file(path)
        status, error = verdicts.get(parsed.run_id or "", ("not_verified", None))
        if parsed.parse_status != "ok":
            # 버리지 않는다. 원인 분석 자료가 사라진다. 로그는 나중에 어떤 파일이
            # 왜 깨졌는지 runs/ 를 다시 뒤지지 않고 찾기 위한 것이다.
            logger.warning("%s: %s — %s", path.name, parsed.parse_status, parsed.parse_error)
        inserted.append(
            await insert_analysis(
                session,
                parsed,
                verify_status=status,
                verify_error=error,
                generated_at=generated_at,
                prompt_version=prompt_version,
            )
        )
    return inserted


__all__ = [
    "KST",
    "ParsedAnalysis",
    "build_analysis",
    "insert_analysis",
    "insert_analysis_files",
    "normalize_background",
    "normalize_not_found",
    "normalize_terms",
    "parse_analysis_file",
    "parse_wrapper",
]
