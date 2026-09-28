"""⑤ 근거 검증 · 점검. 보고서와 **그 보고서를 만든 입력**을 함께 받는 순수 함수들이다.

LLM 을 부르지 않는다. 모델에게 "네 인용이 맞느냐" 를 물으면 같은 환각이 한 번 더
돌아올 뿐이라, 글자 대조와 표에 적힌 규칙만으로 판정한다.

입력이 반드시 같이 필요하다. 보고서 출력에는 `market` 이 없어서 보고서만으로는
±1% 구간인지, quote 가 원문에 있는지, url 이 입력에 있던 주소인지 확인할 수 없다.

## 문제 표기

문제 하나는 `"<코드>: <상세>"` 문자열이다. 코드는 규칙마다 하나라 빈도를 셀 수 있고,
상세는 사람이 어느 칸이 걸렸는지 찾아가는 용도다. 래퍼 JSON 과 DB 의 verify_error
(Text) 에 그대로 들어가야 해서 객체가 아니라 문자열로 둔다. 코드는 `code_of()` 로 뗀다.

## 값 목록은 프롬프트에서 옮겼다

아래 상수는 `prompts/stock_analysis_system.md` 의 「출력 형식」 절과 4부 칸별 표에
적힌 값만 옮긴 것이다. 프롬프트를 고치면 여기도 같이 고친다. 추측으로 늘리지 않는다 —
검증기가 프롬프트보다 너그러우면 위반이 통과하고, 엄격하면 멀쩡한 보고서가 떨어진다.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

# --- 프롬프트 「출력 형식」 에서 옮긴 값 목록 ------------------------------------

VERDICTS = ("explained", "partially_explained", "no_clear_cause")
STANCES = ("bullish", "bearish", "neutral")
SIZE_FITS = ("sufficient", "partial", "insufficient")
MATCHES = ("direct", "indirect")
BACKGROUND_SLOTS = ("bullish", "bearish", "neutral")

# 최상위 필수 칸. 출력 형식 예시에 있는 키 전부다.
REQUIRED_TOP = (
    "ticker", "name", "date", "as_of", "change_pct", "verdict",
    "summary", "factors", "terms", "background", "not_found",
)
# summary 네 칸. counter 만 null 이 정상값이다(4부 summary 표의 「비움」 열).
SUMMARY_KEYS = ("move", "main_cause", "counter", "unexplained")
SUMMARY_NULLABLE = ("counter",)

# --- 규칙 상수 ----------------------------------------------------------------

# 2부 7단계 "등락률이 ±1% 이내면 no_clear_cause". 경계를 포함한다(|x| <= 1.00).
FLAT_MOVE_PCT = Decimal("1.00")
# 출력 change_pct 는 입력 값을 옮겨 적은 것이라 같아야 하지만, 모델이 자릿수를
# 반올림하는 경우가 있어 0.01 까지는 같은 값으로 본다. float 로 빼면 1.09 - 1.08 이
# 0.010000000000000009 가 되어 경계에서 떨어지므로 Decimal 로 계산한다.
CHANGE_PCT_TOLERANCE = Decimal("0.01")
# 2부 6단계 표. 간접·미확인 근거는 partial 을 넘을 수 없다.
CAPPED_SIZE_FIT = "sufficient"

# --- 문제 코드 ----------------------------------------------------------------

# 스키마
SCHEMA_MISSING = "SCHEMA_MISSING"  # 필수 칸 없음
SCHEMA_TYPE = "SCHEMA_TYPE"  # 타입이 다름 (bool 자리에 문자열 등)
SCHEMA_VALUE = "SCHEMA_VALUE"  # 값 목록 밖의 값, 비움 불가 칸이 빈 문자열
# 규칙
FLAT_MOVE_VERDICT = "FLAT_MOVE_VERDICT"  # ±1% 이내인데 verdict 가 no_clear_cause 아님
FLAT_MOVE_FACTORS = "FLAT_MOVE_FACTORS"  # ±1% 이내인데 factors 가 비어 있지 않음
SIZE_FIT_OVER_CAP = "SIZE_FIT_OVER_CAP"  # indirect 만 근거인데 sufficient
UNCONFIRMED_OVER_CAP = "UNCONFIRMED_OVER_CAP"  # unconfirmed 인데 sufficient
DIRECTION_MISMATCH = "DIRECTION_MISMATCH"  # factors 에 direction_match: false
VERDICT_SIZE_FIT = "VERDICT_SIZE_FIT"  # 판정표 조건과 factors 가 어긋남
TICKER_MISMATCH = "TICKER_MISMATCH"
DATE_MISMATCH = "DATE_MISMATCH"
CHANGE_PCT_MISMATCH = "CHANGE_PCT_MISMATCH"
# 근거
FACTOR_WITHOUT_SOURCE = "FACTOR_WITHOUT_SOURCE"  # 4부 "sources — 최소 1개"
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
JSON_INVALID = "JSON_INVALID"  # 벗겨내도 JSON 으로 안 열림
ASKED_QUESTION = "ASKED_QUESTION"  # 되묻기 금지 위반


def code_of(problem: str) -> str:
    """`"CODE: 상세"` 에서 코드만."""
    return problem.split(":", 1)[0].strip()


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


def check_schema(report: dict[str, Any]) -> list[str]:
    """필수 칸과 값 목록. 개수 상한(factors 4개 등)은 보지 않는다 — 적재 모듈이
    로그로 관측하기로 한 값이고, 여기서 떨어뜨리면 그 관측이 끊긴다."""
    out: list[str] = []
    for key in REQUIRED_TOP:
        if key not in report:
            out.append(_p(SCHEMA_MISSING, key))

    for key in ("ticker", "name", "date", "as_of"):
        if key in report and not isinstance(report[key], str):
            out.append(_p(SCHEMA_TYPE, f"{key} 는 문자열이어야 한다: {report[key]!r}"))
    if "change_pct" in report and not _is_number(report["change_pct"]):
        out.append(_p(SCHEMA_TYPE, f"change_pct 는 숫자여야 한다: {report['change_pct']!r}"))
    if "verdict" in report and report["verdict"] not in VERDICTS:
        out.append(_p(SCHEMA_VALUE, f"verdict={report['verdict']!r} (허용: {'|'.join(VERDICTS)})"))

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
        _check_str(f, "claim", path, out, non_empty=True)
        _check_str(f, "detail", path, out)
        _check_enum(f, "stance", STANCES, path, out)
        _check_bool(f, "direction_match", path, out)
        _check_enum(f, "size_fit", SIZE_FITS, path, out)
        _check_bool(f, "unconfirmed", path, out)
        sources = _check_list(f, "sources", path, out)
        for j, s in enumerate(sources or []):
            spath = f"{path}sources[{j}]."
            if not isinstance(s, dict):
                out.append(_p(SCHEMA_TYPE, f"{spath[:-1]} 는 객체여야 한다"))
                continue
            for key in ("channel", "url", "datetime_kst", "quote"):
                _check_str(s, key, spath, out)
            _check_enum(s, "match", MATCHES, spath, out)
            _check_bool(s, "is_market_recap", spath, out)

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
                if isinstance(item, str):
                    continue
                if not isinstance(item, dict):
                    out.append(_p(SCHEMA_TYPE, f"{ipath} 는 문자열이나 객체여야 한다"))
                    continue
                _check_str(item, "text", f"{ipath}.", out)
                _check_bool(item, "watch", f"{ipath}.", out)

    not_found = _check_list(report, "not_found", "", out) if "not_found" in report else None
    for i, n in enumerate(not_found or []):
        if not isinstance(n, str):
            out.append(_p(SCHEMA_TYPE, f"not_found[{i}] 는 문자열이어야 한다"))
    return out


# --- 규칙 ---------------------------------------------------------------------


def _factors(report: dict[str, Any]) -> list[dict[str, Any]]:
    factors = report.get("factors")
    return [f for f in factors if isinstance(f, dict)] if isinstance(factors, list) else []


def _sources(factor: dict[str, Any]) -> list[dict[str, Any]]:
    sources = factor.get("sources")
    return [s for s in sources if isinstance(s, dict)] if isinstance(sources, list) else []


def is_flat_move(change_pct: Any) -> bool:
    """±1% 이내인가. 경계를 포함한다 — 1.00% 는 이 구간이다."""
    value = _decimal(change_pct)
    return value is not None and abs(value) <= FLAT_MOVE_PCT


def check_rules(report: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """프롬프트 판단 절차의 규칙 중 필드만 보고 기계적으로 가릴 수 있는 것.

    ±1% 판정은 보고서가 아니라 **입력의** change_pct 로 한다. 보고서 값은 모델이 옮겨
    적은 것이라, 그걸 기준으로 삼으면 옮기다 틀린 보고서가 규칙을 피해 간다.
    """
    out: list[str] = []
    factors = _factors(report)
    raw_factors = report.get("factors")

    if is_flat_move(payload.get("change_pct")):
        if report.get("verdict") != "no_clear_cause":
            out.append(_p(FLAT_MOVE_VERDICT,
                          f"입력 등락률 {payload['change_pct']}% 인데 verdict={report.get('verdict')!r}"))
        if isinstance(raw_factors, list) and raw_factors:
            out.append(_p(FLAT_MOVE_FACTORS,
                          f"입력 등락률 {payload['change_pct']}% 인데 factors {len(raw_factors)}개"))

    for i, f in enumerate(factors):
        sources = _sources(f)
        size_fit = f.get("size_fit")
        # "match: indirect 메시지만 있음" 이 상한 조건이다. 출처가 하나도 없으면
        # 간접인지 알 수 없으므로 여기서는 보지 않고 FACTOR_WITHOUT_SOURCE 가 잡는다.
        if sources and all(s.get("match") == "indirect" for s in sources) \
                and size_fit == CAPPED_SIZE_FIT:
            out.append(_p(SIZE_FIT_OVER_CAP, f"factors[{i}] 간접 근거만 있는데 size_fit=sufficient"))
        if f.get("unconfirmed") is True and size_fit == CAPPED_SIZE_FIT:
            out.append(_p(UNCONFIRMED_OVER_CAP, f"factors[{i}] 미확인 정보인데 size_fit=sufficient"))
        if f.get("direction_match") is False:
            out.append(_p(DIRECTION_MISMATCH, f"factors[{i}] direction_match=false 는 counter 로 간다"))

    out.extend(_check_verdict_table(report.get("verdict"), raw_factors, factors))
    out.extend(_check_matches_input(report, payload))
    return out


def _check_verdict_table(verdict: Any, raw_factors: Any, factors: list[dict[str, Any]]) -> list[str]:
    """2부 7단계 판정표의 세 줄만 옮긴다. 표에 없는 조합은 보지 않는다.

        explained            size_fit: sufficient 인 factor 가 최소 1개
        partially_explained  factor 가 있으나 전부 partial 이나 insufficient
        no_clear_cause       factor 가 없음. factors 는 빈 배열

    판정 재료가 스키마를 어겼으면 **건너뛴다** — verdict 가 목록 밖, factors 가 배열이
    아님, factor 가 객체가 아님, size_fit 이 없거나 목록 밖. 그 상태에서 일관성을 따지면
    같은 원인이 SCHEMA_* 와 VERDICT_SIZE_FIT 로 두 번 세어져 사유별 빈도가 부풀고,
    "size_fit 이 medium 이라 sufficient 가 없다" 처럼 뜻 없는 사유가 붙는다.
    스키마 실패는 check_schema 가 잡으므로 보고서는 어차피 failed 다.
    """
    if verdict not in VERDICTS or not isinstance(raw_factors, list):
        return []
    if len(factors) != len(raw_factors) or any(f.get("size_fit") not in SIZE_FITS for f in factors):
        return []
    fits = [f["size_fit"] for f in factors]
    if verdict == "explained" and "sufficient" not in fits:
        return [_p(VERDICT_SIZE_FIT, "explained 인데 size_fit=sufficient 인 factor 가 없다")]
    if verdict == "partially_explained":
        if not raw_factors:
            return [_p(VERDICT_SIZE_FIT, "partially_explained 인데 factors 가 비어 있다")]
        if any(fit not in ("partial", "insufficient") for fit in fits):
            return [_p(VERDICT_SIZE_FIT,
                       "partially_explained 인데 partial·insufficient 가 아닌 factor 가 있다")]
    if verdict == "no_clear_cause" and raw_factors:
        return [_p(VERDICT_SIZE_FIT, "no_clear_cause 인데 factors 가 비어 있지 않다")]
    return []


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


def _messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages = payload.get("messages")
    return [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else []


def _link_bodies(message: dict[str, Any]) -> list[dict[str, Any]]:
    bodies = message.get("link_bodies")
    return [b for b in bodies if isinstance(b, dict)] if isinstance(bodies, list) else []


def _haystack(messages: list[dict[str, Any]]) -> list[str]:
    """quote 를 찾을 원문. 메시지 text 와 그 메시지에 딸린 기사 excerpt 다."""
    texts = []
    for m in messages:
        if isinstance(m.get("text"), str):
            texts.append(normalize_ws(m["text"]))
        for b in _link_bodies(m):
            if isinstance(b.get("excerpt"), str):
                texts.append(normalize_ws(b["excerpt"]))
    return texts


def check_grounding(report: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """factor 출처마다 url 이 입력 메시지 주소인지, quote 가 그 메시지 원문에 있는지.

    quote 는 **그 url 의 메시지 안에서만** 찾는다. 입력 전체에서 찾으면 다른 메시지의
    문장을 이 출처에 붙여도 통과한다. 찾을 범위는 이렇게 정한다.

        url 이 메시지 url        → 그 메시지(text + 딸린 excerpt)
        url 이 link_bodies 주소  → 그 링크가 딸린 메시지. url 자체는 URL_IS_LINK_BODY 로 실패
        어디에도 없음             → 입력 전체. url 은 URL_NOT_IN_INPUT 으로 실패
    """
    out: list[str] = []
    messages = _messages(payload)
    for i, f in enumerate(_factors(report)):
        sources = _sources(f)
        if not sources:
            out.append(_p(FACTOR_WITHOUT_SOURCE, f"factors[{i}]"))
            continue
        for j, s in enumerate(sources):
            path = f"factors[{i}].sources[{j}]"
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
            # 빈 quote 는 어떤 문자열에도 들어 있으므로 따로 떨어뜨린다.
            needle = normalize_ws(quote) if isinstance(quote, str) else ""
            if not needle or not any(needle in text for text in _haystack(scope)):
                out.append(_p(QUOTE_NOT_IN_SOURCE, f"{path} {quote!r}"))
    return out


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
    "MATCHES",
    "SIZE_FITS",
    "STANCES",
    "VERDICTS",
    "check_grounding",
    "check_rules",
    "check_schema",
    "code_of",
    "is_flat_move",
    "normalize_ws",
    "verify",
    "verify_wrapper",
]
