"""⑤ 근거 검증 · 점검. 보고서와 **그 보고서를 만든 입력**을 함께 받는 순수 함수들이다.

LLM 을 부르지 않는다. 모델에게 "네 인용이 맞느냐" 를 물으면 같은 환각이 한 번 더
돌아올 뿐이라, 글자 대조와 표에 적힌 규칙만으로 판정한다.

입력이 반드시 같이 필요하다. 보고서 출력에는 `market` 이 없어서 보고서만으로는
층마다 설명할 방향이 어느 쪽인지, quote 가 원문에 있는지, url 이 입력에 있던 주소인지 확인할 수 없다.

## 문제 표기

문제 하나는 `"<코드>: <상세>"` 문자열이다. 코드는 규칙마다 하나라 빈도를 셀 수 있고,
상세는 사람이 어느 칸이 걸렸는지 찾아가는 용도다. 래퍼 JSON 과 DB 의 verify_error
(Text) 에 그대로 들어가야 해서 객체가 아니라 문자열로 둔다. 코드는 `code_of()` 로 뗀다.

## 값 목록은 프롬프트에서 옮겼다

아래 상수는 `prompts/stock_analysis_system.md` 의 「출력 형식」 절과 4부 칸별 표에
적힌 값만 옮긴 것이다. 프롬프트를 고치면 여기도 같이 고친다. 추측으로 늘리지 않는다 —
검증기가 프롬프트보다 너그러우면 위반이 통과하고, 엄격하면 멀쩡한 보고서가 떨어진다.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

# --- 프롬프트 「출력 형식」 에서 옮긴 값 목록 ------------------------------------

VERDICTS = ("explained", "partially_explained", "no_clear_cause")
STANCES = ("bullish", "bearish", "neutral")
# link.strength 의 값. 이전 형식 factor 의 size_fit 과 같은 값 체계다.
SIZE_FITS = ("sufficient", "partial", "insufficient")
MATCHES = ("direct", "indirect")
BACKGROUND_SLOTS = ("bullish", "bearish", "neutral")
# link 의 층. move 는 오늘 등락의 원인, relative 는 다른 대형주와 달랐던 이유다(2부 3단계).
# factor 는 사건 하나이고, 그 사건이 어느 층에 답하는지는 factor.links 에 층마다 하나씩 단다.
LAYERS = ("move", "relative")
# 층마다 판정이 하나씩 있다. verdict 는 등락 층, relative_verdict 는 상대 층.
VERDICT_KEYS = {"move": "verdict", "relative": "relative_verdict"}

# 최상위 필수 칸. 출력 형식 예시에 있는 키 전부다.
REQUIRED_TOP = (
    "ticker", "name", "date", "as_of", "change_pct", "verdict", "relative_verdict",
    "summary", "factors", "terms", "background", "not_found",
)
# summary 다섯 칸. relative 와 counter 만 null 이 정상값이다(4부 summary 표의 「비움」 열).
SUMMARY_KEYS = ("move", "main_cause", "relative", "counter", "unexplained")
SUMMARY_NULLABLE = ("relative", "counter")
# events — 검수용 칸(4부 「events」). 화면에 나가지 않아 REQUIRED_TOP 에 넣지 않고, 판정과
# 따로 check_events() 가 본다. 모델은 factors·background 에 실제로 적은 사건만 적는다.
# dropped 는 러너만 쓴다 — quote 를 한 번 고쳐 쓰게 해도 원문에 없어 칸에서 뺀 사건이다(repair.repair_quotes).
EVENT_PLACEMENTS = ("factors", "background", "dropped")
QUOTE_VERIFY_FAIL = "quote_verify_fail"
EVENT_REASONS = (QUOTE_VERIFY_FAIL,)
# reason 을 쓰는 곳. dropped 만 쓰고, 나머지 placed 는 reason 칸을 뺀다.
EVENT_REASON_BY_PLACEMENT = {"dropped": EVENT_REASONS}

# 모델에 보내는 입력의 세 칸(프롬프트 1부 「세 칸의 용도」). split_messages() 가 kind·after_prev_close 로 가른다.
#   messages        근거가 되는 메시지(news·news_digest·disclosure·other·theme_recap, kind 없음 포함)
#   market_context  그날 시장 시황(market_recap)과 전날 장 설명(after_prev_close)
#   flow            장중 매매 순위 목록(flow_rank)
MARKET_CONTEXT_KINDS = ("market_recap",)
FLOW_KINDS = ("flow_rank",)

# --- 규칙 상수 ----------------------------------------------------------------

# 입력 market.move_case 의 값. 러너가 move_case() 로 계산해 입력에 넣고 집계에 쓰는
# 이름표다. 규칙은 이 이름표가 아니라 layer_pct() 로 본다 — 등락 층의 ±1% 규칙은
# move_case 와 무관하게 change_pct 로 걸어야 해서다.
# 시장 몫을 알 수 없는 날(null)은 문자열이 아니라 None 이다.
MOVE_CASES = ("flat", "opposite", "normal")
# 2부 7단계 ±1% 규칙의 경계. 층마다 |layer_pct| <= 1.00 이면 그 층 판정은
# no_clear_cause 다(경계 포함).
FLAT_EXCESS_PCT = Decimal("1.00")
# 출력 change_pct 는 입력 값을 옮겨 적은 것이라 같아야 하지만, 모델이 자릿수를
# 반올림하는 경우가 있어 0.01 까지는 같은 값으로 본다. float 로 빼면 1.09 - 1.08 이
# 0.010000000000000009 가 되어 경계에서 떨어지므로 Decimal 로 계산한다.
CHANGE_PCT_TOLERANCE = Decimal("0.01")
# 2부 6단계 표. 간접·미확인 근거는 partial 을 넘을 수 없다(모든 link 의 strength).
CAPPED_SIZE_FIT = "sufficient"
# 4부 factors.sources "최소 1개, 최대 3개". background.sources 도 같은 규칙이다.
# 출처는 factor(사건)에 달리므로 links 가 몇 개든 factor 하나에 한 번 센다.
SOURCES_MAX = 3

# --- 문제 코드 ----------------------------------------------------------------

# 스키마
SCHEMA_MISSING = "SCHEMA_MISSING"  # 필수 칸 없음
SCHEMA_TYPE = "SCHEMA_TYPE"  # 타입이 다름 (bool 자리에 문자열 등)
SCHEMA_VALUE = "SCHEMA_VALUE"  # 값 목록 밖의 값, 비움 불가 칸이 빈 문자열
# events 항목의 reason 이 placed 와 맞지 않음. dropped 인데 reason 이 없거나, reason 을 쓰지
# 않는 placed 에 reason 이 있거나, background 에 over_cap 아닌 reason 이 붙었다.
EVENT_REASON_MISMATCH = "EVENT_REASON_MISMATCH"
# links 가 빈 배열. 층에 하나도 답하지 않는 사건은 factor 가 아니다(2부 7단계).
LINKS_EMPTY = "LINKS_EMPTY"
# 한 factor 의 links 에 같은 layer 가 두 번. 층마다 link 는 하나다.
LINK_LAYER_DUPLICATE = "LINK_LAYER_DUPLICATE"
# 규칙
FLAT_MOVE_VERDICT = "FLAT_MOVE_VERDICT"  # |change_pct| ±1% 이내인데 verdict 가 no_clear_cause 아님
FLAT_MOVE_FACTORS = "FLAT_MOVE_FACTORS"  # |change_pct| ±1% 이내인데 layer: move link 를 가진 factor 가 있음
# 상대 층. |excess_pct| ±1% 이내이거나 excess_pct 가 null(상대 층을 판단하지 않는 날)인데
# relative_verdict 가 no_clear_cause 가 아니거나 layer: relative link 를 가진 factor 가 있음.
FLAT_RELATIVE_VERDICT = "FLAT_RELATIVE_VERDICT"
FLAT_RELATIVE_FACTORS = "FLAT_RELATIVE_FACTORS"
# 아래 세 코드는 link 마다 본다. 이름은 이전 형식(factor.size_fit) 때 것을 그대로 둬 빈도를 이어 센다.
SIZE_FIT_OVER_CAP = "SIZE_FIT_OVER_CAP"  # indirect 만 근거인데 link strength 가 sufficient
UNCONFIRMED_OVER_CAP = "UNCONFIRMED_OVER_CAP"  # unconfirmed 인데 link strength 가 sufficient
DIRECTION_MISMATCH = "DIRECTION_MISMATCH"  # link 에 direction_match: false
# link 의 direction_match 를 그 link 층 방향으로 계산한 값과 다르다. move 는 change_pct 부호,
# relative 는 excess_pct 부호다. 덜 내린 날의 악재를 relative 로 넣으면 여기서 걸린다.
DIRECTION_MATCH_WRONG = "DIRECTION_MATCH_WRONG"
# summary.counter 는 background 에 있는 재료만 요약한다. background 가 모두 비었는데
# counter 가 있으면 출처 없이 counter 에만 적은 재료가 있다는 뜻이다.
COUNTER_WITHOUT_BACKGROUND = "COUNTER_WITHOUT_BACKGROUND"
# 2부 5단계. 종목 등락 중 다른 대형주와 같은 몫(peer_median_pct)이 절반 이상인 날, 등락 층의
# sufficient factor 가 모두 종목 고유 재료다. 종목 고유 재료는 다른 대형주와 달랐던 부분까지만
# 설명할 수 있어 상한이 partial 이다.
MOVE_SUFFICIENT_STOCK_ONLY = "MOVE_SUFFICIENT_STOCK_ONLY"
VERDICT_SIZE_FIT = "VERDICT_SIZE_FIT"  # 판정표 조건과 move link 가 어긋남(verdict)
RELATIVE_VERDICT_SIZE_FIT = "RELATIVE_VERDICT_SIZE_FIT"  # 같은 표, relative link 와 relative_verdict
TICKER_MISMATCH = "TICKER_MISMATCH"
DATE_MISMATCH = "DATE_MISMATCH"
CHANGE_PCT_MISMATCH = "CHANGE_PCT_MISMATCH"
# 근거
FACTOR_WITHOUT_SOURCE = "FACTOR_WITHOUT_SOURCE"  # 4부 "sources — 최소 1개"
BACKGROUND_WITHOUT_SOURCE = "BACKGROUND_WITHOUT_SOURCE"  # background 항목도 최소 1개
SOURCES_OVER_MAX = "SOURCES_OVER_MAX"  # factor·background 항목의 출처가 SOURCES_MAX 를 넘음
QUOTE_NOT_IN_SOURCE = "QUOTE_NOT_IN_SOURCE"
URL_NOT_IN_INPUT = "URL_NOT_IN_INPUT"
# link_bodies 의 기사 주소를 출처로 쓴 것. 프롬프트가 "그 링크가 실려 있던 텔레그램
# 메시지 URL 을 쓴다" 고 정했으므로 실패지만, 지어낸 주소(URL_NOT_IN_INPUT)와는 성격이
# 달라 빈도를 따로 본다 — 이게 많으면 프롬프트 문구를 고칠 일이지 환각이 아니다.
URL_IS_LINK_BODY = "URL_IS_LINK_BODY"
# 보고서를 열 수 없음. 검증 자체를 못 했지만 not_verified 가 아니라 failed 로 둔다 —
# not_verified 는 "아직 검증기를 안 돌렸다" 는 뜻이라 섞이면 셀 수가 없다.
LLM_ERROR = "LLM_ERROR"  # 호출 실패
EMPTY_RESPONSE = "EMPTY_RESPONSE"  # 정상 응답인데 본문이 빔
# finish_reason=length. 본문이 비었든 잘린 본문이 있든 이 코드다 — 빈 응답과 원인이 달라
# (출력 상한) 고칠 곳도 다르다. 같은 설정으로 다시 보내면 같은 자리에서 또 잘리므로
# 자동 재시도하지 않는다.
OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"
# 스트림이 응답을 다 주기 전에 끊겼다(재시도까지 끊김). 받은 부분은 열어 보지 않는다.
STREAM_INTERRUPTED = "STREAM_INTERRUPTED"
JSON_INVALID = "JSON_INVALID"  # 벗겨내도 JSON 으로 안 열림
ASKED_QUESTION = "ASKED_QUESTION"  # 되묻기 금지 위반

# --- 경고 코드 (실패 아님) ----------------------------------------------------

# 서로 다른 두 factor 의 출처 url 집합이 같다. 한 사건을 factor 둘로 나눴을 수 있다
# (한 사건은 factor 하나, 층은 links). 다른 사건을 같은 메시지가 함께 전한 경우도 있어
# 실패로 두지 않는다. check_warnings() 가 보고 verify_status 에는 넣지 않는다.
DUPLICATE_SOURCES = "DUPLICATE_SOURCES"
# events 의 issue_ids 가 issue_trace 에 없는 id 를 가리킨다.
ISSUE_ID_UNKNOWN = "ISSUE_ID_UNKNOWN"
# messages 칸 메시지 url 이 issue_trace 에 없다. 1-1 에서 그 메시지를 건너뛴 것이다(메시지가 많을 때).
ISSUE_TRACE_MISSING_URL = "ISSUE_TRACE_MISSING_URL"
# 생성 뒤 처리(quote 고쳐 쓰기 실패로 factor 를 뺌)로 등락 층 근거가 빠졌는데 summary.main_cause 를
# 다시 쓰지 못했다. main_cause 가 뺀 근거를 아직 말하고 있을 수 있다(repair.rewrite_main_cause).
MAIN_CAUSE_STALE = "MAIN_CAUSE_STALE"
# 4부 개수 상한(background 전체 6·칸당 3, watch 전체 3·칸당 1, factors 4, terms 8)을 넘었다.
# check_schema 는 적재 관측을 끊지 않으려고 상한을 보지 않으므로 경고로만 남긴다.
COUNT_OVER_CAP = "COUNT_OVER_CAP"
# factor 출처가 모두 입력 kind 가 flow_rank·market_recap 인 메시지다. 결과(순위·시황)만으로 원인을 세웠다.
FACTOR_RESULT_SOURCES_ONLY = "FACTOR_RESULT_SOURCES_ONLY"
# factor 출처에 theme_recap 메시지가 있는데, 그 메시지에서 이 factor 로 묶인 이슈 중 relation 이 sector 인
# 것이 없다. 이 종목 업종이 아닌 테마 단락을 근거로 썼을 수 있다.
THEME_RECAP_NOT_SECTOR = "THEME_RECAP_NOT_SECTOR"
# factor 의 첫 출처 quote 에 event 의 대상어(매매 주체, 영문 고유명)가 없다. quote 가 event 를 뒷받침하는지
# 글자만으로는 알 수 없어 겹침만 본다. 이 종목명은 대상어로 보지 않는다.
QUOTE_MISSING_SUBJECT = "QUOTE_MISSING_SUBJECT"

# --- events ↔ 실제 칸 대조 (events_problems, 판정과 분리) ------------------------

# placed=background 의 {slot, index} 가 가리키는 background 항목이 없다.
EVENT_BACKGROUND_REF_MISSING = "EVENT_BACKGROUND_REF_MISSING"
# 두 사건이 같은 background 항목을 가리킨다. 항목 하나에 사건 하나다.
EVENT_BACKGROUND_REF_DUPLICATE = "EVENT_BACKGROUND_REF_DUPLICATE"
# 어느 사건도 가리키지 않는 background 항목.
EVENT_BACKGROUND_UNREFERENCED = "EVENT_BACKGROUND_UNREFERENCED"
# placed=factors 사건 수가 factors 수와 다르다.
EVENT_FACTOR_COUNT = "EVENT_FACTOR_COUNT"
# placed=factors 의 factor 순번이 factors 범위 밖이다.
EVENT_FACTOR_REF_MISSING = "EVENT_FACTOR_REF_MISSING"
# 두 사건이 같은 factor 를 가리킨다.
EVENT_FACTOR_DUPLICATE = "EVENT_FACTOR_DUPLICATE"
# 한 이슈 id 가 두 사건의 issue_ids 에 들어 있다.
ISSUE_ID_DUPLICATE = "ISSUE_ID_DUPLICATE"

# 4부 개수 상한. 프롬프트 background·watch·factors·terms 절에서 옮겼다.
CAPS = {"factors": 4, "terms": 8, "background": 6, "background_slot": 3, "watch": 3, "watch_slot": 1}
# 입력 kind 가 이 값이면 결과(순위·시장 시황)를 적은 메시지다. factor 의 원인 출처가 될 수 없다(6단계).
RESULT_KINDS = ("flow_rank", "market_recap")
THEME_RECAP_KIND = "theme_recap"
SECTOR_RELATION = "sector"
# 매매 주체. event 에 있으면 첫 출처 quote 에도 있어야 한다. "기관" 은 그 아래 주체가 quote 에 있어도 된다.
INVESTOR_SUBJECTS = ("외국인", "기관", "개인", "연기금", "투신", "금융투자", "사모", "보험", "기타법인")
INSTITUTION_MEMBERS = ("기관", "연기금", "투신", "금융투자", "사모", "보험")
# 영문 고유명. 대문자로 시작하는 두 글자 이상 영문·숫자 덩어리(CATL, YMTC, HBM4, Meta).
_LATIN_NAME = re.compile(r"[A-Z][A-Za-z0-9]+")
# 영문 직함. 대상(누구)이 아니라 그 사람의 자리라 대상어로 보지 않는다.
TITLE_WORDS = ("CEO", "CFO", "CTO", "COO")


def code_of(problem: str) -> str:
    """`"CODE: 상세"` 에서 코드만."""
    return problem.split(":", 1)[0].strip()


# --- 계열 ---------------------------------------------------------------------

# 한 실수로 함께 나오는 코드를 묶는 계열. 여기 없는 코드는 코드 이름이 곧 계열이다.
# 문제 목록(verify_problems)은 코드 그대로 남기고, 러너의 사유별 집계만 계열로 센다 —
# 집계는 "몇 회차가 이 실수를 했나" 를 보는 숫자라 한 실수가 여러 칸에 들어가면 안 된다.
FLAT_MOVE = "FLAT_MOVE"
FLAT_RELATIVE = "FLAT_RELATIVE"
CODE_FAMILIES = {
    FLAT_MOVE_VERDICT: FLAT_MOVE,
    FLAT_MOVE_FACTORS: FLAT_MOVE,
    FLAT_RELATIVE_VERDICT: FLAT_RELATIVE,
    FLAT_RELATIVE_FACTORS: FLAT_RELATIVE,
}
# 층마다 (±1% 코드, 그 층의 판정표 코드).
_FLAT_AND_TABLE_CODES = (
    ({FLAT_MOVE_VERDICT, FLAT_MOVE_FACTORS}, VERDICT_SIZE_FIT),
    ({FLAT_RELATIVE_VERDICT, FLAT_RELATIVE_FACTORS}, RELATIVE_VERDICT_SIZE_FIT),
)


def families_of(problems: list[str]) -> set[str]:
    """보고서 하나의 문제 목록 → 집계에 넣을 계열 집합.

    판정표 위반이 같은 층의 ±1% 규칙 위반에 딸려 나온 것이면 뺀다. 층마다 따로 본다.
    ±1% 날 그 층의 FLAT 코드가 없다는 건 그 층 판정이 no_clear_cause 이고 그 층 factor 가
    없다는 뜻이고 그러면 판정표는 항상 맞는다. 즉 그날 그 층의 판정표 위반은 언제나
    FLAT 실수의 결과다.
    """
    codes = {code_of(p) for p in problems}
    for flat_codes, table_code in _FLAT_AND_TABLE_CODES:
        if codes & flat_codes:
            codes.discard(table_code)
    return {CODE_FAMILIES.get(code, code) for code in codes}


def _p(code: str, detail: str) -> str:
    return f"{code}: {detail}"


def _is_number(value: Any) -> bool:
    # bool 은 int 의 하위 타입이라 따로 막는다. change_pct 에 true 가 오면 1 로 읽힌다.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _decimal(value: Any) -> Decimal | None:
    """float 를 str 로 한 번 거친다. Decimal(1.08) 은 1.0800000000000000710... 이다."""
    if not _is_number(value):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


# --- 이전 형식 정규화 ---------------------------------------------------------

# 이전 형식에서 link 로 옮겨 가는 층별 칸. (옛 이름, 새 이름).
_LEGACY_LINK_FIELDS = (("size_fit", "strength"), ("direction_match", "direction_match"))


def _is_legacy_factor(f: Any) -> bool:
    """이전 형식 factor 인가. 층이 links 가 아니라 layer 문자열로 와 있다."""
    return isinstance(f, dict) and "links" not in f and isinstance(f.get("layer"), str)


def _normalize_factor(f: dict[str, Any]) -> dict[str, Any]:
    """layer·size_fit·direction_match 를 link 하나로 옮기고 claim 은 event 로 옮긴다.

    note 는 채우지 않는다. 옛 detail 에는 출처의 사실과 모델의 판단이 섞여 있어 어느 층의
    답인지 기계적으로 가를 수 없다. 비워 두고 converted: true 로 변환된 link 임을 남긴다.
    """
    out = {k: v for k, v in f.items() if k not in ("claim", "layer", "size_fit", "direction_match")}
    if "event" not in out and "claim" in f:
        out["event"] = f["claim"]
    link: dict[str, Any] = {"layer": f["layer"], "note": None, "converted": True}
    for old, new in _LEGACY_LINK_FIELDS:
        if old in f:
            link[new] = f[old]
    out["links"] = [link]
    return out


def normalize_report(report: Any) -> Any:
    """이전 형식 factor 를 links 형식으로 편 사본. 새 형식이거나 factor 가 없으면 그대로다.

    검증 함수마다 처음에 부른다. 같은 보고서를 두 번 불러도 결과가 같고, 원본은 고치지 않는다.
    """
    if not isinstance(report, dict):
        return report
    factors = report.get("factors")
    if not isinstance(factors, list) or not any(_is_legacy_factor(f) for f in factors):
        return report
    return {**report, "factors": [_normalize_factor(f) if _is_legacy_factor(f) else f
                                  for f in factors]}


# --- 스키마 -------------------------------------------------------------------


def _check_str(obj: dict, key: str, path: str, out: list[str], *, nullable: bool = False,
               non_empty: bool = False) -> None:
    if key not in obj:
        out.append(_p(SCHEMA_MISSING, f"{path}{key}"))
        return
    value = obj[key]
    if value is None and nullable:
        return
    if not isinstance(value, str):
        out.append(_p(SCHEMA_TYPE, f"{path}{key} 는 문자열이어야 한다: {value!r}"))
    elif non_empty and not value.strip():
        out.append(_p(SCHEMA_VALUE, f"{path}{key} 는 비울 수 없다"))


def _check_bool(obj: dict, key: str, path: str, out: list[str]) -> None:
    if key not in obj:
        out.append(_p(SCHEMA_MISSING, f"{path}{key}"))
    elif not isinstance(obj[key], bool):
        # "true" 문자열을 받아 주면 적재에서 NULL 로 빠진다(_as_bool). 여기서 먼저 잡는다.
        out.append(_p(SCHEMA_TYPE, f"{path}{key} 는 true/false 여야 한다: {obj[key]!r}"))


def _check_enum(obj: dict, key: str, allowed: tuple[str, ...], path: str, out: list[str]) -> None:
    if key not in obj:
        out.append(_p(SCHEMA_MISSING, f"{path}{key}"))
    elif obj[key] not in allowed:
        out.append(_p(SCHEMA_VALUE, f"{path}{key}={obj[key]!r} (허용: {'|'.join(allowed)})"))


def _check_list(obj: dict, key: str, path: str, out: list[str]) -> list | None:
    if key not in obj:
        out.append(_p(SCHEMA_MISSING, f"{path}{key}"))
        return None
    if not isinstance(obj[key], list):
        out.append(_p(SCHEMA_TYPE, f"{path}{key} 는 배열이어야 한다"))
        return None
    return obj[key]


def _check_sources_schema(obj: dict, path: str, out: list[str]) -> None:
    """factor 와 background 항목이 같이 쓰는 sources 형식."""
    sources = _check_list(obj, "sources", path, out)
    for j, s in enumerate(sources or []):
        spath = f"{path}sources[{j}]."
        if not isinstance(s, dict):
            out.append(_p(SCHEMA_TYPE, f"{spath[:-1]} 는 객체여야 한다"))
            continue
        for key in ("channel", "url", "datetime_kst", "quote"):
            _check_str(s, key, spath, out)
        _check_enum(s, "match", MATCHES, spath, out)
        _check_bool(s, "is_market_recap", spath, out)


def _check_links_schema(f: dict, path: str, out: list[str]) -> None:
    """factor.links. 최소 1개, 층마다 최대 1개.

    note 는 비울 수 없다. 이전 형식에서 변환한 link(converted: true)만 null 을 받는다.
    """
    links = _check_list(f, "links", path, out)
    if links is None:
        return
    if not links:
        out.append(_p(LINKS_EMPTY, f"{path}links 가 비었다"))
        return
    seen: set[str] = set()
    for k, link in enumerate(links):
        lpath = f"{path}links[{k}]."
        if not isinstance(link, dict):
            out.append(_p(SCHEMA_TYPE, f"{lpath[:-1]} 는 객체여야 한다"))
            continue
        _check_enum(link, "layer", LAYERS, lpath, out)
        if "converted" in link:
            _check_bool(link, "converted", lpath, out)
        converted = link.get("converted") is True
        _check_str(link, "note", lpath, out, nullable=converted, non_empty=not converted)
        _check_bool(link, "direction_match", lpath, out)
        _check_enum(link, "strength", SIZE_FITS, lpath, out)
        layer = link.get("layer")
        if layer in seen:
            out.append(_p(LINK_LAYER_DUPLICATE, f"{path}links 에 layer={layer} 가 두 번"))
        elif layer in LAYERS:
            seen.add(layer)


def check_schema(report: dict[str, Any]) -> list[str]:
    """필수 칸과 값 목록. 개수 상한(factors 4개 등)은 보지 않는다 — 적재 모듈이
    로그로 관측하기로 한 값이고, 여기서 떨어뜨리면 그 관측이 끊긴다."""
    report = normalize_report(report)
    out: list[str] = []
    for key in REQUIRED_TOP:
        if key not in report:
            out.append(_p(SCHEMA_MISSING, key))

    for key in ("ticker", "name", "date", "as_of"):
        if key in report and not isinstance(report[key], str):
            out.append(_p(SCHEMA_TYPE, f"{key} 는 문자열이어야 한다: {report[key]!r}"))
    if "change_pct" in report and not _is_number(report["change_pct"]):
        out.append(_p(SCHEMA_TYPE, f"change_pct 는 숫자여야 한다: {report['change_pct']!r}"))
    for key in VERDICT_KEYS.values():
        if key in report and report[key] not in VERDICTS:
            out.append(_p(SCHEMA_VALUE, f"{key}={report[key]!r} (허용: {'|'.join(VERDICTS)})"))

    summary = report.get("summary")
    if "summary" in report and not isinstance(summary, dict):
        out.append(_p(SCHEMA_TYPE, "summary 는 객체여야 한다"))
    elif isinstance(summary, dict):
        for key in SUMMARY_KEYS:
            nullable = key in SUMMARY_NULLABLE
            _check_str(summary, key, "summary.", out, nullable=nullable, non_empty=not nullable)

    factors = _check_list(report, "factors", "", out) if "factors" in report else None
    for i, f in enumerate(factors or []):
        path = f"factors[{i}]."
        if not isinstance(f, dict):
            out.append(_p(SCHEMA_TYPE, f"factors[{i}] 는 객체여야 한다"))
            continue
        # 사건·출처 칸. 층마다 달라지는 칸(layer·note·direction_match·strength)은 links 에 있다.
        _check_str(f, "event", path, out, non_empty=True)
        _check_str(f, "detail", path, out)
        _check_enum(f, "stance", STANCES, path, out)
        _check_bool(f, "unconfirmed", path, out)
        _check_sources_schema(f, path, out)
        _check_links_schema(f, path, out)

    terms = _check_list(report, "terms", "", out) if "terms" in report else None
    for i, t in enumerate(terms or []):
        if not isinstance(t, dict):
            out.append(_p(SCHEMA_TYPE, f"terms[{i}] 는 객체여야 한다"))
            continue
        _check_str(t, "plain", f"terms[{i}].", out)
        _check_str(t, "term", f"terms[{i}].", out)

    background = report.get("background")
    if "background" in report and not isinstance(background, dict):
        out.append(_p(SCHEMA_TYPE, "background 는 객체여야 한다"))
    elif isinstance(background, dict):
        # "비는 칸은 빈 배열" 이라 세 칸이 모두 있어야 한다.
        for slot in BACKGROUND_SLOTS:
            items = _check_list(background, slot, "background.", out)
            for i, item in enumerate(items or []):
                ipath = f"background.{slot}[{i}]"
                # 출처를 달아야 해서 문자열 항목은 받지 않는다.
                if not isinstance(item, dict):
                    out.append(_p(SCHEMA_TYPE, f"{ipath} 는 객체여야 한다(text·sources)"))
                    continue
                _check_str(item, "text", f"{ipath}.", out, non_empty=True)
                _check_sources_schema(item, f"{ipath}.", out)
                # watch 는 표시할 때만 붙인다. 붙였으면 true/false 여야 한다.
                if "watch" in item:
                    _check_bool(item, "watch", f"{ipath}.", out)

    not_found = _check_list(report, "not_found", "", out) if "not_found" in report else None
    for i, n in enumerate(not_found or []):
        if not isinstance(n, str):
            out.append(_p(SCHEMA_TYPE, f"not_found[{i}] 는 문자열이어야 한다"))
    return out


# --- events (검수용, 판정과 분리) ----------------------------------------------


def check_events(report: dict[str, Any] | None) -> tuple[str, list[str]]:
    """(passed | failed | missing, 문제 목록). verify() 와 따로 돈다.

    events 는 화면에 나가지 않는 진단 칸이라 이 결과는 verify_status 에 넣지 않는다. 형식이
    틀렸다고 보고서를 떨어뜨리면 멀쩡한 본문까지 화면에서 사라진다. 래퍼에 events_status·
    events_problems 로 따로 남겨 프롬프트를 고칠 때 본다. 보고서를 열지 못했거나 칸이 없으면 missing.
    """
    if not isinstance(report, dict) or "events" not in report:
        return "missing", []
    out: list[str] = []
    events = _check_list(report, "events", "", out)
    for i, e in enumerate(events or []):
        _check_event(e, f"events[{i}]", out)
    if events is not None:
        out += _check_event_places(report, events)
    return ("failed" if out else "passed"), out


def _check_event_places(report: dict[str, Any], events: list[Any]) -> list[str]:
    """events 가 가리키는 자리가 실제 칸과 맞는가. 형식이 맞는 항목만 본다(형식은 _check_event).

    background 항목과 placed=background 사건은 하나씩 짝이 맞아야 하고, placed=factors 사건 수는 factors
    수와 같고 한 factor 를 한 사건만 가리켜야 한다. 이슈 id 는 한 사건에만 든다.
    """
    out: list[str] = []
    items = {(slot, i) for slot in BACKGROUND_SLOTS
             for i, _ in enumerate(report["background"][slot]
                                   if isinstance(report.get("background"), dict)
                                   and isinstance(report["background"].get(slot), list) else [])}
    n_factors = len(report["factors"]) if isinstance(report.get("factors"), list) else 0
    seen_bg: dict[tuple[str, int], int] = {}
    seen_factor: dict[int, int] = {}
    seen_issue: dict[str, int] = {}
    placed_factors = 0
    for k, e in enumerate(events):
        if not isinstance(e, dict):
            continue
        if e.get("placed") == "background" and (ref := _background_ref(e)) is not None:
            if ref not in items:
                out.append(_p(EVENT_BACKGROUND_REF_MISSING, f"events[{k}] background.{ref[0]}[{ref[1]}] 가 없다"))
            elif ref in seen_bg:
                out.append(_p(EVENT_BACKGROUND_REF_DUPLICATE,
                              f"events[{seen_bg[ref]}] 와 events[{k}] 가 background.{ref[0]}[{ref[1]}] 를 가리킨다"))
            else:
                seen_bg[ref] = k
        if e.get("placed") == "factors":
            placed_factors += 1
            f = e.get("factor")
            if _is_index(f) and f >= n_factors:
                out.append(_p(EVENT_FACTOR_REF_MISSING, f"events[{k}].factor={f} (factors {n_factors}개)"))
            elif _is_index(f) and f in seen_factor:
                out.append(_p(EVENT_FACTOR_DUPLICATE, f"events[{seen_factor[f]}] 와 events[{k}] 가 factors[{f}] 를 가리킨다"))
            elif _is_index(f):
                seen_factor[f] = k
        ids = e.get("issue_ids") if isinstance(e.get("issue_ids"), list) else []
        for x in dict.fromkeys(i for i in ids if isinstance(i, str)):
            if x in seen_issue:
                out.append(_p(ISSUE_ID_DUPLICATE, f"{x!r} 가 events[{seen_issue[x]}] 와 events[{k}] 에 있다"))
            else:
                seen_issue[x] = k
    for slot, i in sorted(items - set(seen_bg)):
        out.append(_p(EVENT_BACKGROUND_UNREFERENCED, f"background.{slot}[{i}] 를 가리키는 사건이 없다"))
    if placed_factors != n_factors:
        out.append(_p(EVENT_FACTOR_COUNT, f"placed=factors 사건 {placed_factors}개, factors {n_factors}개"))
    return out


def _is_index(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _background_ref(e: dict[str, Any]) -> tuple[str, int] | None:
    """events 항목의 background 칸 → (slot, index). 형식이 틀렸거나 없으면 None."""
    ref = e.get("background")
    if not isinstance(ref, dict) or ref.get("slot") not in BACKGROUND_SLOTS or not _is_index(ref.get("index")):
        return None
    return ref["slot"], ref["index"]


def _check_event(e: Any, path: str, out: list[str]) -> None:
    if not isinstance(e, dict):
        out.append(_p(SCHEMA_TYPE, f"{path} 는 객체여야 한다"))
        return
    _check_str(e, "event", f"{path}.", out, non_empty=True)
    # 입력에 dup_channels 가 없으면 null 이다. 칸 자체는 있어야 한다.
    if "dup_channels" not in e:
        out.append(_p(SCHEMA_MISSING, f"{path}.dup_channels"))
    elif e["dup_channels"] is not None and (
            isinstance(e["dup_channels"], bool) or not isinstance(e["dup_channels"], int)):
        out.append(_p(SCHEMA_TYPE, f"{path}.dup_channels 는 정수나 null 이어야 한다: {e['dup_channels']!r}"))
    # issue_ids 는 issue_trace 를 쓰는 프롬프트부터 생겼다. 없는 예전 보고서는 그대로 통과한다.
    if "issue_ids" in e and not (isinstance(e["issue_ids"], list)
                                 and all(isinstance(x, str) for x in e["issue_ids"])):
        out.append(_p(SCHEMA_TYPE, f"{path}.issue_ids 는 문자열 배열이어야 한다: {e['issue_ids']!r}"))
    _check_enum(e, "placed", EVENT_PLACEMENTS, f"{path}.", out)
    placed = e.get("placed")
    if "factor" in e and (placed != "factors" or not _is_index(e["factor"])):
        out.append(_p(SCHEMA_VALUE, f"{path}.factor 는 placed=factors 일 때 factors 순번(정수)만 쓴다: "
                                    f"{e['factor']!r}"))
    # placed=background 면 그 사건을 담은 항목 자리 {slot, index} 가 있어야 한다. 그 밖에는 칸을 뺀다.
    if placed == "background" and "background" not in e:
        out.append(_p(SCHEMA_MISSING, f"{path}.background (placed=background 의 항목 자리)"))
    elif "background" in e and (placed != "background" or _background_ref(e) is None):
        out.append(_p(SCHEMA_VALUE, f"{path}.background 는 placed=background 일 때 "
                                    f"{{slot: {'|'.join(BACKGROUND_SLOTS)}, index: 정수}} 만 쓴다: "
                                    f"{e['background']!r}"))
    if placed not in EVENT_PLACEMENTS:
        return  # placed 가 깨졌으면 reason 조건을 따질 기준이 없다.
    allowed = EVENT_REASON_BY_PLACEMENT.get(placed, ())
    if "reason" not in e:
        if placed == "dropped":
            out.append(_p(EVENT_REASON_MISMATCH, f"{path} dropped 인데 reason 이 없다"))
    elif not allowed:
        out.append(_p(EVENT_REASON_MISMATCH, f"{path} placed={placed} 는 reason 을 쓰지 않는다"))
    elif e["reason"] not in EVENT_REASONS:
        out.append(_p(SCHEMA_VALUE, f"{path}.reason={e['reason']!r} (허용: {'|'.join(EVENT_REASONS)})"))
    elif e["reason"] not in allowed:
        out.append(_p(EVENT_REASON_MISMATCH,
                      f"{path} placed={placed} 에 reason={e['reason']!r} (허용: {'|'.join(allowed)})"))


# --- 규칙 ---------------------------------------------------------------------


def _factors(report: dict[str, Any]) -> list[dict[str, Any]]:
    factors = report.get("factors")
    return [f for f in factors if isinstance(f, dict)] if isinstance(factors, list) else []


def _sources(factor: dict[str, Any]) -> list[dict[str, Any]]:
    sources = factor.get("sources")
    return [s for s in sources if isinstance(s, dict)] if isinstance(sources, list) else []


def _links(factor: dict[str, Any]) -> list[dict[str, Any]]:
    links = factor.get("links")
    return [x for x in links if isinstance(x, dict)] if isinstance(links, list) else []


def _has_layer(factor: dict[str, Any], layer: str) -> bool:
    return any(x.get("layer") == layer for x in _links(factor))


def _background_items(report: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(경로, 항목) 목록. 객체가 아닌 항목은 check_schema 가 잡으므로 뺀다."""
    background = report.get("background")
    if not isinstance(background, dict):
        return []
    out = []
    for slot in BACKGROUND_SLOTS:
        items = background.get(slot)
        for i, item in enumerate(items if isinstance(items, list) else []):
            if isinstance(item, dict):
                out.append((f"background.{slot}[{i}]", item))
    return out


def _background_is_empty(report: dict[str, Any]) -> bool:
    background = report.get("background")
    if not isinstance(background, dict):
        return True
    return not any(isinstance(background.get(slot), list) and background[slot]
                   for slot in BACKGROUND_SLOTS)


def layer_pct(payload: dict[str, Any], layer: str) -> Decimal | None:
    """층의 값. 부호가 그 층의 방향이고(2부 3단계), 절댓값이 ±1% 규칙의 기준이다(7단계).

        move      종목 change_pct
        relative  market.excess_pct. market 이나 excess_pct 가 null 이면 None
                  — 상대 층을 판단하지 않는 날이다

    move 가 None 이면(입력 change_pct 가 숫자가 아님) 그 층의 ±1% 규칙과 방향 검사를 보지 않는다.
    """
    if layer == "move":
        return _decimal(payload.get("change_pct"))
    market = payload.get("market")
    return _decimal(market.get("excess_pct")) if isinstance(market, dict) else None


def expected_direction_match(stance: Any, pct: Decimal) -> bool:
    """4부 factors 의 direction_match 계산. 층의 값이 양수면 bullish, 음수면 bearish 만
    true. neutral 과 0 은 언제나 false 다."""
    return (stance == "bullish" and pct > 0) or (stance == "bearish" and pct < 0)


def move_case(payload: dict[str, Any]) -> str | None:
    """입력 market.move_case 이름표. flat | opposite | normal, 시장 몫을 모르면 None.

    러너가 입력에 넣고 경우별로 세는 데 쓴다. 검증 규칙은 이 값을 보지 않는다
    (layer_pct 참고). opposite 는 종목 등락률과 excess_pct 의 부호가 반대인 날이라는 표시일
    뿐이고 판정에 상한을 두지 않는다.

        None      market 이나 market.excess_pct 가 null
        flat      |excess_pct| <= 1.00 (경계 포함)
        opposite  |excess_pct| >  1.00 이고 change_pct 와 excess_pct 의 부호가 반대
        normal    그 밖

    0 처리. 부호는 `change_pct × excess_pct < 0` 일 때만 반대로 본다. 0 은 부호가 없다.
    - excess_pct 가 0 이면 |0| <= 1 이라 항상 flat 이다. 부호까지 가지 않는다.
    - change_pct 가 0 이면 반대로 볼 부호가 없어 normal 이다.
    """
    market = payload.get("market")
    if not isinstance(market, dict):
        return None
    excess = _decimal(market.get("excess_pct"))
    if excess is None:
        return None
    if abs(excess) <= FLAT_EXCESS_PCT:
        return "flat"
    change = _decimal(payload.get("change_pct"))
    if change is not None and change * excess < 0:
        return "opposite"
    return "normal"


def _layer_is_quiet(payload: dict[str, Any], layer: str) -> tuple[bool, Decimal | None]:
    """(그 층에 원인을 대면 안 되는 날인가, 층의 값). 2부 7단계 ±1% 규칙.

    move 는 |change_pct| <= 1. relative 는 |excess_pct| <= 1 이거나 excess_pct 가 null
    (상대 층을 판단하지 않는다). move 값이 없으면 규칙을 걸 수 없어 False 다.
    """
    pct = layer_pct(payload, layer)
    if pct is None:
        return layer == "relative", None
    return abs(pct) <= FLAT_EXCESS_PCT, pct


def judge_layers(payload: dict[str, Any]) -> dict[str, bool]:
    """입력 market.judge_layers. 층마다 이 입력에서 원인을 판단하는가(±1% 규칙의 반대).

    러너가 입력에 넣어 모델이 규칙을 다시 계산하지 않게 한다. 검증(check_judge_layers)도 같은
    _layer_is_quiet 를 보므로 입력에 넣은 값과 검증 기준이 어긋나지 않는다.
    """
    return {layer: not _layer_is_quiet(payload, layer)[0] for layer in LAYERS}


def _peer_share_half(payload: dict[str, Any]) -> bool | None:
    """종목 등락 중 다른 대형주와 같은 몫이 절반 이상인가. change_pct 와 peer_median_pct 의 부호가 같고
    |peer| >= |change| × 0.5 (경계 포함). 2부 5단계 「종목 고유 재료는 sufficient 불가」 의 조건이다.
    peer_median_pct 나 change_pct 가 숫자가 아니면 알 수 없어 None.
    """
    change = layer_pct(payload, "move")
    market = payload.get("market")
    peer = _decimal(market.get("peer_median_pct")) if isinstance(market, dict) else None
    if change is None or peer is None:
        return None
    return change * peer > 0 and 2 * abs(peer) >= abs(change)


def common_move(payload: dict[str, Any]) -> bool | None:
    """입력 market.common_move. 대형주 전반이 이 종목과 같은 방향으로 함께 움직인 날인가.

    _peer_share_half(대형주 몫이 절반 이상) 이고 상대 층을 판단하지 않는 날(judge_layers.relative 가 false).
    차이가 큰 날(예: -0.47% 인데 대형주 -1.77%)은 같은 방향이어도 "함께 움직인 날" 이 아니다.
    true 면 summary.main_cause 첫 문장에 그 사실을 쓴다(프롬프트 4부). 알 수 없으면 None.
    """
    share = _peer_share_half(payload)
    if share is None:
        return None
    return share and not judge_layers(payload)["relative"]


# 층마다 ±1% 규칙의 (판정 코드, factor 코드).
_FLAT_CODES = {"move": (FLAT_MOVE_VERDICT, FLAT_MOVE_FACTORS),
               "relative": (FLAT_RELATIVE_VERDICT, FLAT_RELATIVE_FACTORS)}
_TABLE_CODES = {"move": VERDICT_SIZE_FIT, "relative": RELATIVE_VERDICT_SIZE_FIT}


def check_rules(report: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """프롬프트 판단 절차의 규칙 중 필드만 보고 기계적으로 가릴 수 있는 것.

    층의 값(layer_pct)은 보고서가 아니라 **입력으로** 정한다. 보고서 값은 모델이
    옮겨 적은 것이라, 그걸 기준으로 삼으면 옮기다 틀린 보고서가 규칙을 피해 간다.
    """
    report = normalize_report(report)
    factors = _factors(report)
    quiet = {layer: _layer_is_quiet(payload, layer) for layer in LAYERS}
    out = check_judge_layers(report, payload)

    for i, f in enumerate(factors):
        sources = _sources(f)
        # "match: indirect 메시지만 있음" 이 상한 조건이다. 출처가 하나도 없으면
        # 간접인지 알 수 없으므로 여기서는 보지 않고 FACTOR_WITHOUT_SOURCE 가 잡는다.
        indirect_only = bool(sources) and all(s.get("match") == "indirect" for s in sources)
        stance = f.get("stance")
        for k, link in enumerate(_links(f)):
            where = f"factors[{i}].links[{k}]"
            strength = link.get("strength")
            # 근거의 성질(출처·unconfirmed)은 factor 에 있고 상한은 모든 link 에 걸린다.
            if indirect_only and strength == CAPPED_SIZE_FIT:
                out.append(_p(SIZE_FIT_OVER_CAP, f"{where} 간접 근거만 있는데 strength=sufficient"))
            if f.get("unconfirmed") is True and strength == CAPPED_SIZE_FIT:
                out.append(_p(UNCONFIRMED_OVER_CAP, f"{where} 미확인 정보인데 strength=sufficient"))
            if link.get("direction_match") is False:
                out.append(_p(DIRECTION_MISMATCH, f"{where} direction_match=false 는 counter 로 간다"))
            # 적힌 값이 그 link 층의 방향으로 계산한 값과 다르면 실패. stance 는 사건 하나에
            # 하나라 factor 에서 읽는다. 스키마를 어긴 값은 check_schema 가 잡으므로 보지 않는다.
            # ±1% 날 그 층의 link 는 FLAT_*_FACTORS 로 떨어지므로 같은 실수를 두 번 세지 않게 건너뛴다.
            layer, match = link.get("layer"), link.get("direction_match")
            if layer not in LAYERS or stance not in STANCES or not isinstance(match, bool):
                continue
            is_quiet, pct = quiet[layer]
            if pct is not None and not is_quiet and match != expected_direction_match(stance, pct):
                out.append(_p(DIRECTION_MATCH_WRONG,
                              f"{where} layer={layer}, stance={stance}, 값 {pct} 인데 "
                              f"direction_match={match}"))

    out.extend(_check_market_share(factors, payload, quiet["move"][0]))

    # 4부 counter: background 에 있는 재료만 언급한다.
    summary = report.get("summary")
    counter = summary.get("counter") if isinstance(summary, dict) else None
    if isinstance(counter, str) and counter.strip() and _background_is_empty(report):
        out.append(_p(COUNTER_WITHOUT_BACKGROUND, "summary.counter 가 있는데 background 가 모두 비었다"))

    out.extend(_check_verdict_tables(report, report.get("factors"), factors))
    out.extend(_check_matches_input(report, payload))
    return out


def check_judge_layers(report: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """2부 7단계: 입력 judge_layers 가 false 인 층(±1% 이내, 상대 층은 excess_pct 가 null 인 날도)은
    그 층 판정이 no_clear_cause 이고 그 층 link 가 없다. FLAT_* 코드만 낸다.

    check_rules 의 일부이고, generate 가 이 위반만 보고 한 번 다시 부를지 정할 때 따로 부른다.
    """
    report = normalize_report(report)
    factors = _factors(report)
    out: list[str] = []
    for layer in LAYERS:
        is_quiet, pct = _layer_is_quiet(payload, layer)
        if not is_quiet:
            continue
        verdict_code, factors_code = _FLAT_CODES[layer]
        key = VERDICT_KEYS[layer]
        why = "excess_pct 가 null" if pct is None else f"±1% 이내({layer} 값 {pct})"
        if report.get(key) != "no_clear_cause":
            out.append(_p(verdict_code, f"{why} 인데 {key}={report.get(key)!r}"))
        # 층마다 센다. 두 층에 link 를 단 factor 는 두 층에 각각 하나로 들어간다.
        n = sum(_has_layer(f, layer) for f in factors)
        if n:
            out.append(_p(factors_code, f"{why} 인데 layer={layer} link 를 가진 factor {n}개"))
    return out


def is_stock_specific(factor: dict[str, Any]) -> bool:
    """종목 고유 재료인가. 출처가 모두 `match: "direct"` 이면 그렇다고 본다.

    프롬프트에 따로 칸이 없어 1부의 근거 구분(direct = 이 종목을 직접 다룬 메시지,
    indirect = 업황·경쟁사·전방산업)을 빌려 쓴다. 출처에 간접 메시지가 하나라도 있으면
    업종 재료로 본다. 한계: 이 종목 메시지가 시장 전체 사건을 전한 경우(direct 인데 시장 재료)
    는 종목 고유로 잘못 잡힌다. 출처가 없으면 판단하지 않는다(FACTOR_WITHOUT_SOURCE).
    """
    sources = _sources(factor)
    return bool(sources) and all(s.get("match") == "direct" for s in sources)


def _check_market_share(factors: list[dict[str, Any]], payload: dict[str, Any],
                        move_quiet: bool) -> list[str]:
    """2부 5단계. change_pct 와 peer_median_pct 의 부호가 같고 |peer| >= |change|/2 (경계 포함)
    인 날, layer: move link 가 sufficient 인 factor 가 있는데 모두 종목 고유 재료면 실패.

    ±1% 날은 move link 자체가 FLAT_MOVE_FACTORS 로 떨어지므로 보지 않는다.
    """
    if move_quiet or not _peer_share_half(payload):
        return []
    change = layer_pct(payload, "move")
    peer = _decimal(payload["market"].get("peer_median_pct"))
    sufficient = [i for i, f in enumerate(factors)
                  if any(x.get("layer") == "move" and x.get("strength") == CAPPED_SIZE_FIT
                         for x in _links(f))]
    if not sufficient or not all(is_stock_specific(factors[i]) for i in sufficient):
        return []
    where = ", ".join(f"factors[{i}]" for i in sufficient)
    return [_p(MOVE_SUFFICIENT_STOCK_ONLY,
               f"종목 {change} 중 대형주와 같은 몫 {peer} 가 절반 이상인데 등락 층 sufficient 가 "
               f"모두 종목 고유 재료({where}). 상한은 partial")]


def _check_verdict_tables(report: dict[str, Any], raw_factors: Any,
                          factors: list[dict[str, Any]]) -> list[str]:
    """2부 7단계 판정표의 세 줄을 층마다 적용한다. 표에 없는 조합은 보지 않는다.

        explained            그 층에 strength: sufficient 인 link 가 최소 1개
        partially_explained  그 층에 link 가 있으나 전부 partial 이나 insufficient
        no_clear_cause       그 층에 link 가 없음

    verdict 는 layer: move link 로, relative_verdict 는 layer: relative link 로 본다.
    factor 하나에 층마다 link 는 하나라 "그 층 link 수" 가 곧 "그 층 link 를 가진 factor 수" 다.

    판정 재료가 스키마를 어겼으면 **건너뛴다** — 판정이 목록 밖, factors 가 배열이
    아님, factor 가 객체가 아님, links 가 없거나 비었거나 객체 아닌 항목이 있음, link 의
    strength 나 layer 가 없거나 목록 밖, 한 factor 에 같은 layer 가 두 번. 그 상태에서
    일관성을 따지면 같은 원인이 SCHEMA_* 와 판정표 코드로 두 번 세어져 사유별 빈도가
    부풀고, "strength 가 medium 이라 sufficient 가 없다" 처럼 뜻 없는 사유가 붙는다.
    layer 가 하나라도 깨지면 link 를 층으로 가를 수 없어 두 층 모두 건너뛴다.
    스키마 실패는 check_schema 가 잡으므로 보고서는 어차피 failed 다.
    """
    if not isinstance(raw_factors, list) or len(factors) != len(raw_factors):
        return []
    for f in factors:
        links = f.get("links")
        if not isinstance(links, list) or not links or len(_links(f)) != len(links):
            return []
        if any(x.get("strength") not in SIZE_FITS or x.get("layer") not in LAYERS for x in links):
            return []
        if len({x["layer"] for x in links}) != len(links):
            return []
    out: list[str] = []
    for layer, key in VERDICT_KEYS.items():
        verdict = report.get(key)
        if verdict not in VERDICTS:
            continue
        fits = [x["strength"] for f in factors for x in f["links"] if x["layer"] == layer]
        code, where = _TABLE_CODES[layer], f"{key}={verdict} 인데 layer={layer}"
        if verdict == "explained" and "sufficient" not in fits:
            out.append(_p(code, f"{where} 에 size_fit=sufficient 인 factor 가 없다"))
        elif verdict == "partially_explained" and not fits:
            out.append(_p(code, f"{where} factor 가 없다"))
        elif verdict == "partially_explained" and "sufficient" in fits:
            out.append(_p(code, f"{where} 에 partial·insufficient 가 아닌 factor 가 있다"))
        elif verdict == "no_clear_cause" and fits:
            out.append(_p(code, f"{where} factor 가 있다"))
    return out


def _check_matches_input(report: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """보고서가 입력을 옮겨 적은 칸. 다르면 다른 종목·다른 날 보고서가 섞인 것이다."""
    out: list[str] = []
    if "ticker" in report and report.get("ticker") != payload.get("code"):
        out.append(_p(TICKER_MISMATCH, f"{report.get('ticker')!r} ≠ 입력 {payload.get('code')!r}"))
    if "date" in report and report.get("date") != payload.get("target_date"):
        out.append(_p(DATE_MISMATCH, f"{report.get('date')!r} ≠ 입력 {payload.get('target_date')!r}"))
    if "change_pct" in report:
        got, want = _decimal(report.get("change_pct")), _decimal(payload.get("change_pct"))
        if got is not None and want is not None and abs(got - want) > CHANGE_PCT_TOLERANCE:
            out.append(_p(CHANGE_PCT_MISMATCH, f"{got} ≠ 입력 {want}"))
    return out


# --- 근거 ---------------------------------------------------------------------


def normalize_ws(text: str) -> str:
    """공백만 정규화한다. 줄바꿈·탭·연속 공백을 공백 하나로. 그 외 글자는 그대로다 —
    프롬프트가 "한 글자만 달라도 검증에서 떨어진다" 고 약속했다."""
    return " ".join(text.split())


# 괄호 안이 영문·숫자뿐인 짧은 약어. "(AI)", "(FE)", "(HBM4)" 처럼 앞말을 줄여 병기한 것이다.
# 영문이 한 글자는 있어야 한다 — "(2)", "(2026)" 같은 번호·숫자는 약어가 아니라 내용이라 남긴다.
_ABBR_PAREN = re.compile(r"\((?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{1,10}\)")


def normalize_quote(text: str) -> str:
    """quote 대조용 정규화. 원문과 quote **양쪽에 똑같이** 적용한다.

    1. 괄호 안이 영문·숫자로 된 짧은 약어면 괄호째 뺀다("인공지능(AI) 산업" → "인공지능 산업").
    2. 공백을 정리한다(normalize_ws).

    이것 말고는 손대지 않는다. 유사도·부분 일치는 허용하지 않는다 — 단어를 바꾸거나 빼거나
    더한 quote 는 여전히 떨어진다.
    """
    return normalize_ws(_ABBR_PAREN.sub("", text))


# 원문의 "말(약어)". 말은 괄호 바로 앞(공백 하나까지)의 한글·영문·숫자 덩어리다.
_WORD_ABBR = re.compile(r"([가-힣A-Za-z0-9]+) ?\(((?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{1,10})\)")


def _source_units(text: str) -> list[tuple[str, ...]]:
    """원문을 대조 단위로 편다. 글자 하나는 (글자,), "말(약어)" 하나는 (말, 약어) 다.

    quote 쪽은 normalize_quote 로 괄호 약어를 지우므로, 원문의 "말(약어)" 는 quote 가 "말(약어)"·"말"·
    "약어" 어느 꼴로 써도 맞는다. 말 앞에 붙은 것 없이 홀로 있는 괄호 약어는 normalize_quote 처럼 지운다.
    """
    def plain(segment: str) -> list[tuple[str, ...]]:
        # 조각 경계의 공백을 지우면 앞뒤 낱말이 붙는다. 공백은 하나로 줄이기만 한다.
        return [(c,) for c in re.sub(r"\s+", " ", _ABBR_PAREN.sub("", segment))]

    text = normalize_ws(text)
    units: list[tuple[str, ...]] = []
    pos = 0
    for m in _WORD_ABBR.finditer(text):
        units += plain(text[pos:m.start()])
        units.append((m.group(1), m.group(2)))
        pos = m.end()
    units += plain(text[pos:])
    # 조각마다 정규화해서 생긴 경계의 겹친 공백·맨 앞뒤 공백을 다시 정리한다.
    out: list[tuple[str, ...]] = []
    for u in units:
        if u == (" ",) and (not out or out[-1] == (" ",)):
            continue
        out.append(u)
    while out and out[-1] == (" ",):
        out.pop()
    return out


def _units_contain(units: list[tuple[str, ...]], needle: str) -> bool:
    """needle 이 units 로 만들 수 있는 문자열의 연속 부분에 글자 그대로 있는가.

    상태는 (단위 순번, 고른 꼴, 그 꼴 안의 위치). 어느 단위의 어느 꼴, 어느 위치에서든 시작할 수 있고
    (quote 가 말 중간에서 시작해도 된다), 한 꼴을 다 읽으면 다음 단위의 아무 꼴 맨 앞으로 넘어간다.
    글자 비교는 정확 일치뿐이다.
    """
    if not needle:
        return False
    states = {(u, o, k) for u, opts in enumerate(units) for o, opt in enumerate(opts)
              for k in range(len(opt))}
    for idx, c in enumerate(needle):
        last = idx == len(needle) - 1
        nxt: set[tuple[int, int, int]] = set()
        for u, o, k in states:
            opt = units[u][o]
            if opt[k] != c:
                continue
            if last:
                return True
            if k + 1 < len(opt):
                nxt.add((u, o, k + 1))
            elif u + 1 < len(units):
                nxt.update((u + 1, o2, 0) for o2 in range(len(units[u + 1])))
        if not nxt:
            return False
        states = nxt
    return False


def quote_in_text(quote: str, text: str) -> bool:
    """quote 가 원문 text 에 있는가. 정규화(normalize_quote)와 "말(약어)" 세 꼴 말고는 정확 일치다."""
    needle = normalize_quote(quote)
    if not needle:
        return False
    if needle in normalize_quote(text):
        return True
    return bool(_WORD_ABBR.search(text)) and _units_contain(_source_units(text), needle)


def _messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages = payload.get("messages")
    return [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else []


def _link_bodies(message: dict[str, Any]) -> list[dict[str, Any]]:
    bodies = message.get("link_bodies")
    return [b for b in bodies if isinstance(b, dict)] if isinstance(bodies, list) else []


def _haystack(messages: list[dict[str, Any]]) -> list[str]:
    """quote 를 찾을 원문. 메시지 text 와 그 메시지에 딸린 기사 excerpt 다. 정규화는 quote_in_text 가 한다."""
    texts = []
    for m in messages:
        if isinstance(m.get("text"), str):
            texts.append(m["text"])
        for b in _link_bodies(m):
            if isinstance(b.get("excerpt"), str):
                texts.append(b["excerpt"])
    return texts


def _check_source(s: dict[str, Any], path: str, messages: list[dict[str, Any]],
                  out: list[str]) -> None:
    url = s.get("url")
    scope = [m for m in messages if m.get("url") == url] if isinstance(url, str) else []
    if not scope:
        owners = [m for m in messages if isinstance(url, str) and any(
            url in (b.get("url"), b.get("final_url")) for b in _link_bodies(m))]
        if owners:
            out.append(_p(URL_IS_LINK_BODY, f"{path} 기사 주소를 썼다: {url}"))
            scope = owners
        else:
            out.append(_p(URL_NOT_IN_INPUT, f"{path} {url!r}"))
            scope = messages
    quote = s.get("quote")
    # 빈 quote 는 quote_in_text 가 떨어뜨린다("(AI)" 만 쓴 quote 도 정규화하면 빈다).
    if not isinstance(quote, str) or not any(quote_in_text(quote, text) for text in _haystack(scope)):
        out.append(_p(QUOTE_NOT_IN_SOURCE, f"{path} {quote!r}"))


def check_grounding(report: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """factor 와 background 항목의 출처마다 url 이 입력 메시지 주소인지, quote 가 그
    메시지 원문에 있는지. 두 칸의 규칙은 같다.

    quote 는 **그 url 의 메시지 안에서만** 찾는다. 입력 전체에서 찾으면 다른 메시지의
    문장을 이 출처에 붙여도 통과한다. 찾을 범위는 이렇게 정한다.

        url 이 메시지 url        → 그 메시지(text + 딸린 excerpt)
        url 이 link_bodies 주소  → 그 링크가 딸린 메시지. url 자체는 URL_IS_LINK_BODY 로 실패
        어디에도 없음             → 입력 전체. url 은 URL_NOT_IN_INPUT 으로 실패
    """
    out: list[str] = []
    messages = _messages(payload)
    items = [(f"factors[{i}]", f, FACTOR_WITHOUT_SOURCE) for i, f in enumerate(_factors(report))]
    items += [(path, item, BACKGROUND_WITHOUT_SOURCE) for path, item in _background_items(report)]
    for path, item, missing_code in items:
        sources = _sources(item)
        if not sources:
            out.append(_p(missing_code, path))
            continue
        if len(sources) > SOURCES_MAX:
            out.append(_p(SOURCES_OVER_MAX, f"{path} {len(sources)}개 (최대 {SOURCES_MAX})"))
        for j, s in enumerate(sources):
            _check_source(s, f"{path}.sources[{j}]", messages, out)
    return out


# --- 경고 (판정과 분리) -------------------------------------------------------


def check_warnings(report: dict[str, Any] | None, payload: dict[str, Any] | None = None,
                   issue_trace: Any = None) -> list[str]:
    """실패는 아니지만 검수자가 볼 것. verify() 와 따로 돌고 verify_status 에 넣지 않는다.

    DUPLICATE_SOURCES           서로 다른 두 factor 의 출처 url 집합이 같다. 한 사건을 층마다
                                factor 로 나눈 이전 방식일 수 있다. 출처가 없는 factor 는 보지 않는다.
    COUNT_OVER_CAP              4부 개수 상한을 넘었다(CAPS).
    아래는 payload 가 있어야 본다. kind 는 모델이 적은 is_market_recap 이 아니라 입력 kind 로 정한다.
    FACTOR_RESULT_SOURCES_ONLY  출처가 모두 flow_rank·market_recap 메시지인 factor.
    THEME_RECAP_NOT_SECTOR      theme_recap 출처의 이슈 중 이 factor 로 묶인 sector 이슈가 없다.
                                issue_trace 가 있어야 본다(events → issue_ids → issue_trace relation).
    QUOTE_MISSING_SUBJECT       첫 출처 quote 에 event 의 매매 주체·영문 고유명이 없다.
    """
    if not isinstance(report, dict):
        return []
    report = normalize_report(report)
    factors = _factors(report)
    keys = [frozenset(s["url"] for s in _sources(f) if isinstance(s.get("url"), str)) for f in factors]
    out: list[str] = []
    for i, a in enumerate(keys):
        for j in range(i + 1, len(keys)):
            if a and a == keys[j]:
                out.append(_p(DUPLICATE_SOURCES,
                              f"factors[{i}] 와 factors[{j}] 의 출처가 같다. 한 사건이면 factor 하나에 links 로 단다"))
    out += _check_caps(report)
    if payload is None:
        return out
    kinds = {m.get("url"): m.get("kind") for m in _messages(payload)}
    for i, f in enumerate(factors):
        source_kinds = [kinds.get(s.get("url")) for s in _sources(f)]
        if source_kinds and all(k in RESULT_KINDS for k in source_kinds):
            out.append(_p(FACTOR_RESULT_SOURCES_ONLY,
                          f"factors[{i}] 출처가 모두 {'·'.join(RESULT_KINDS)} 메시지다({', '.join(source_kinds)})"))
    if isinstance(issue_trace, list):
        out += _check_theme_recap_sector(report, kinds, issue_trace,
                                         {i: m.get("url") for i, m in message_ids(payload)})
    out += _check_quote_subjects(factors, str(payload.get("stock") or ""))
    return out


def _check_caps(report: dict[str, Any]) -> list[str]:
    over: list[str] = []
    for key in ("factors", "terms"):
        n = len(report[key]) if isinstance(report.get(key), list) else 0
        if n > CAPS[key]:
            over.append(f"{key} {n}개(최대 {CAPS[key]})")
    background = report.get("background") if isinstance(report.get("background"), dict) else {}
    slots = {slot: [x for x in background.get(slot) or [] if isinstance(x, dict)]
             if isinstance(background.get(slot), list) else [] for slot in BACKGROUND_SLOTS}
    total = sum(len(v) for v in slots.values())
    if total > CAPS["background"]:
        over.append(f"background 전체 {total}개(최대 {CAPS['background']})")
    watches = {slot: sum(x.get("watch") is True for x in items) for slot, items in slots.items()}
    if sum(watches.values()) > CAPS["watch"]:
        over.append(f"watch 전체 {sum(watches.values())}개(최대 {CAPS['watch']})")
    for slot in BACKGROUND_SLOTS:
        if len(slots[slot]) > CAPS["background_slot"]:
            over.append(f"background.{slot} {len(slots[slot])}개(최대 {CAPS['background_slot']})")
        if watches[slot] > CAPS["watch_slot"]:
            over.append(f"background.{slot} watch {watches[slot]}개(최대 {CAPS['watch_slot']})")
    return [_p(COUNT_OVER_CAP, x) for x in over]


def _check_theme_recap_sector(report: dict[str, Any], kinds: dict[Any, Any],
                              issue_trace: list[Any], id_to_url: dict[str, Any]) -> list[str]:
    """theme_recap 출처를 쓴 factor 마다, 그 factor 를 가리키는 사건의 issue_ids 중 theme_recap 메시지에서 나온
    이슈가 sector 인지 본다. 하나라도 sector 면 통과. 그런 이슈가 없거나 sector 가 아니면 경고."""
    issue_url = {i.get("id"): _trace_entry_url(m, id_to_url) for m in issue_trace if isinstance(m, dict)
                 for i in (m.get("issues") if isinstance(m.get("issues"), list) else []) if isinstance(i, dict)}
    relation = {i.get("id"): i.get("relation") for i in _trace_issues(issue_trace)}
    events = report.get("events") if isinstance(report.get("events"), list) else []
    out: list[str] = []
    for i, f in enumerate(_factors(report)):
        theme_urls = {s.get("url") for s in _sources(f) if kinds.get(s.get("url")) == THEME_RECAP_KIND}
        if not theme_urls:
            continue
        ids = [x for e in events if isinstance(e, dict) and e.get("placed") == "factors" and e.get("factor") == i
               for x in (e.get("issue_ids") if isinstance(e.get("issue_ids"), list) else [])]
        theme_rel = [relation.get(x) for x in ids if issue_url.get(x) in theme_urls]
        if SECTOR_RELATION not in theme_rel:
            seen = ", ".join(str(r) for r in theme_rel) or "연결된 이슈 없음"
            out.append(_p(THEME_RECAP_NOT_SECTOR, f"factors[{i}] theme_recap 출처의 이슈 relation: {seen}"))
    return out


def event_subjects(event: str, stock: str) -> list[str]:
    """event 의 대상어 — 매매 주체와 영문 고유명. 이 종목명과 그 일부(예: SK하이닉스의 SK), 직함(CEO 등)은 뺀다."""
    text = event.replace(stock, " ") if stock else event
    subjects = [w for w in INVESTOR_SUBJECTS if w in text]
    names = [n for n in dict.fromkeys(_LATIN_NAME.findall(text))
             if n not in TITLE_WORDS and not (stock and n in stock)]
    return subjects + names


def _subject_in_quote(subject: str, quote: str) -> bool:
    if subject == "기관":
        return any(w in quote for w in INSTITUTION_MEMBERS)
    return subject.lower() in quote.lower()


def _check_quote_subjects(factors: list[dict[str, Any]], stock: str) -> list[str]:
    out: list[str] = []
    for i, f in enumerate(factors):
        sources = _sources(f)
        event, quote = f.get("event"), sources[0].get("quote") if sources else None
        if not isinstance(event, str) or not isinstance(quote, str):
            continue
        missing = [w for w in event_subjects(event, stock) if not _subject_in_quote(w, normalize_ws(quote))]
        if missing:
            out.append(_p(QUOTE_MISSING_SUBJECT, f"factors[{i}] 첫 출처 quote 에 {', '.join(missing)} 가 없다"))
    return out


def _trace_issues(issue_trace: list[Any]) -> list[dict[str, Any]]:
    return [i for m in issue_trace if isinstance(m, dict)
            for i in (m.get("issues") if isinstance(m.get("issues"), list) else [])
            if isinstance(i, dict)]


def _event_issue_ids(report: dict[str, Any]) -> list[tuple[int, Any]]:
    """(events 순번, issue_ids 의 id) 목록."""
    events = report.get("events") if isinstance(report.get("events"), list) else []
    return [(k, x) for k, e in enumerate(events)
            for x in (e.get("issue_ids") if isinstance(e, dict) and isinstance(e.get("issue_ids"), list)
                      else [])]


def split_messages(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """입력 메시지를 모델에 보낼 세 칸으로 나눈다. 입력 순서는 칸 안에서 그대로다.

    after_prev_close 메시지는 kind 와 상관없이 market_context(전날 장 설명, 참고만)다. kind 가 없는 메시지
    (v3 이전 입력)는 messages 다. 검증·출처 대조는 나누기 전 입력 전체로 한다 — 모델이 어느 칸의 url 을
    출처로 달았든 입력에 있던 주소인지는 그대로 확인해야 한다.
    """
    out: dict[str, list[dict[str, Any]]] = {"messages": [], "market_context": [], "flow": []}
    for m in _messages(payload):
        if m.get("after_prev_close") is True or m.get("kind") in MARKET_CONTEXT_KINDS:
            out["market_context"].append(m)
        elif m.get("kind") in FLOW_KINDS:
            out["flow"].append(m)
        else:
            out["messages"].append(m)
    return out


def message_ids(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """messages 칸 메시지마다 (id, 메시지). id 는 입력 순서대로 m1, m2 … 다. 모델 입력(generate.model_input)과
    issue_trace 검증이 같은 함수를 본다."""
    return [(f"m{k + 1}", m) for k, m in enumerate(split_messages(payload)["messages"])]


def _trace_entry_url(entry: dict[str, Any], id_to_url: dict[str, Any]) -> Any:
    """issue_trace 항목이 가리키는 메시지 url. id(m1…) 로 적는 게 지금 형식이고, url 로 적은 예전 형식도 받는다."""
    return id_to_url.get(entry.get("id"), entry.get("url"))


def _missing_message_urls(issue_trace: list[Any], payload: dict[str, Any]) -> tuple[list[str], int, int]:
    """(issue_trace 에 없는 messages 칸 메시지 "id url" — 입력 순서, issue_trace 에 오른 메시지 수, messages 칸 메시지 수).

    issue_trace 는 messages 칸만 m1부터 순서대로 나열한다(프롬프트 1-1). market_context·flow 는 세지 않는다.
    """
    ids = message_ids(payload)
    id_to_url = {i: m.get("url") for i, m in ids}
    traced = {_trace_entry_url(e, id_to_url) for e in issue_trace if isinstance(e, dict)}
    missing = [f"{i} {m.get('url')}" for i, m in ids if m.get("url") not in traced]
    return missing, sum(m.get("url") in traced for _, m in ids), len(ids)


def check_issue_trace(issue_trace: Any, report: dict[str, Any] | None,
                      payload: dict[str, Any] | None = None) -> list[str]:
    """issue_trace 가 messages 칸을 다 훑었는지, events 의 issue_ids 가 issue_trace 에 있는 id 인지.
    경고만 돌려준다.

    events 는 factors·background 에 실제로 적은 사건만 담으므로, 어느 사건에도 들지 않은 이슈는 정상이다
    (issue_trace 에만 남는다). 쓰인 이슈 수는 issue_trace_stats 의 issues_used 가 센다.
    payload 를 주면 issue_trace 에 오르지 않은 messages 칸 url 을 ISSUE_TRACE_MISSING_URL 로 남긴다.
    verify_status 에는 넣지 않는다 — 검수 칸이 어긋났다고 멀쩡한 본문을 떨어뜨리지 않는다.
    issue_trace 가 없거나(예전 프롬프트) 보고서를 열지 못했으면 볼 것이 없어 빈 목록이다.
    """
    if not isinstance(issue_trace, list) or not isinstance(report, dict):
        return []
    out: list[str] = []
    if payload is not None:
        missing, _, _ = _missing_message_urls(issue_trace, payload)
        out += [_p(ISSUE_TRACE_MISSING_URL, f"{x} 가 issue_trace 에 없다") for x in missing]
    known = {i.get("id") for i in _trace_issues(issue_trace)}
    for k, x in _event_issue_ids(report):
        if x not in known:
            out.append(_p(ISSUE_ID_UNKNOWN, f"events[{k}].issue_ids 의 {x!r} 가 issue_trace 에 없다"))
    return out


def issue_trace_stats(issue_trace: Any, report: dict[str, Any] | None,
                      payload: dict[str, Any]) -> dict[str, int] | None:
    """issue_trace 의 숫자. 래퍼 issue_trace_stats 칸이다. issue_trace 가 없으면 None.

        messages_traced  issue_trace 에 url 이 오른 messages 칸 메시지 수
        messages_total   messages 칸 메시지 수
        relations        관련 유형별 이슈 수. none 은 issues 에 적힌 것과 메시지마다의 none_count 를 더한다
        issues_used      issue_trace 이슈 중 events 의 issue_ids 에 든(factors·background 에 쓰인) 수
    """
    if not isinstance(issue_trace, list):
        return None
    _, traced, total = _missing_message_urls(issue_trace, payload)
    issues = _trace_issues(issue_trace)
    referenced = {x for _, x in _event_issue_ids(report)} if isinstance(report, dict) else set()
    relations: dict[str, int] = {}
    for i in issues:
        rel = str(i.get("relation"))
        relations[rel] = relations.get(rel, 0) + 1
    # none 이슈는 적지 않고 메시지마다 개수(none_count)만 남긴다(출력 형식). 예전 형식은 issues 에 있다.
    none_counts = sum(m["none_count"] for m in issue_trace
                      if isinstance(m, dict) and _is_index(m.get("none_count")))
    if none_counts:
        relations["none"] = relations.get("none", 0) + none_counts
    return {
        "messages_traced": traced,
        "messages_total": total,
        "relations": relations,
        "issues_used": sum(i.get("id") in referenced for i in issues),
    }


# --- 판정 ---------------------------------------------------------------------


def verify(report: dict[str, Any], payload: dict[str, Any]) -> tuple[str, list[str]]:
    """(passed | failed, 문제 목록). 스키마·규칙·근거 중 하나라도 걸리면 failed 다.

    스키마 위반도 실패에 넣는다. 칸이 빠진 보고서는 근거가 멀쩡해도 화면이 그릴 수 없다.
    """
    problems = check_schema(report) + check_rules(report, payload) + check_grounding(report, payload)
    return ("failed" if problems else "passed"), problems


def verify_wrapper(
    wrapper: dict[str, Any], report: dict[str, Any] | None, payload: dict[str, Any]
) -> tuple[str, list[str]]:
    """래퍼 단위 판정. 보고서를 열 수 없는 회차도 사유 코드를 달아 failed 로 돌려준다.

    `report` 는 부르는 쪽이 래퍼에서 편 것을 넘긴다(generate.report_of). 여기서 JSON 을
    다시 파싱하지 않아야 "무엇을 검증했나" 가 한 곳에서 정해진다.
    """
    if wrapper.get("is_error"):
        return "failed", [_p(wrapper.get("error_code") or LLM_ERROR, wrapper.get("error") or "")]
    if report is None:
        problems = [_p(JSON_INVALID, f"json_status={wrapper.get('json_status')}")]
        if wrapper.get("asked_question"):
            problems.append(_p(ASKED_QUESTION, "응답이 질문으로 끝난다"))
        return "failed", problems
    return verify(report, payload)


__all__ = [
    "BACKGROUND_SLOTS",
    "EVENT_PLACEMENTS",
    "EVENT_REASONS",
    "LAYERS",
    "MAIN_CAUSE_STALE",
    "MATCHES",
    "MOVE_CASES",
    "QUOTE_VERIFY_FAIL",
    "SIZE_FITS",
    "SOURCES_MAX",
    "STANCES",
    "VERDICTS",
    "VERDICT_KEYS",
    "check_events",
    "check_grounding",
    "check_issue_trace",
    "check_judge_layers",
    "check_rules",
    "check_schema",
    "check_warnings",
    "code_of",
    "common_move",
    "expected_direction_match",
    "families_of",
    "is_stock_specific",
    "issue_trace_stats",
    "judge_layers",
    "layer_pct",
    "message_ids",
    "move_case",
    "normalize_quote",
    "normalize_report",
    "normalize_ws",
    "quote_in_text",
    "split_messages",
    "verify",
    "verify_wrapper",
]
