"""③ 보고서 생성과 ④ 실행 기록 래핑.

입력 JSON 하나 → `complete()` 한 번 → 래퍼 dict 하나. 래퍼는 적재 모듈의
`parse_wrapper()` 가 읽는 형식이다(필드 뜻은 그 모듈 docstring 참고).

입력은 파일이 아니라 **dict 로 받는다.** 지금은 CLI 가 파일을 열어 넘기지만, ② 필터·
태깅이 붙으면 DB 에서 만든 dict 를 그대로 넘길 수 있게 하려는 것이다.

## final_text 에 무엇을 넣나

`parse_wrapper()` 는 final_text 를 그대로 `json.loads` 한다. 그래서 코드펜스를 벗겨야
열린 응답(stripped)은 **벗겨낸 JSON 텍스트**를 넣고, 모델이 낸 원문은 raw_text 에 따로
남긴다. 원문을 final_text 에 넣으면 벗기면 멀쩡한 보고서가 전부 parse_failed 가 된다.
그래도 json_status=stripped 가 남으므로 적재는 schema_violation 으로 표시해 화면에 내지 않는다.

## JSON 이 안 열리면 한 번 다시 부른다

정상 응답(finish_reason=stop)인데 JSON 으로 열리지 않으면(json_status=invalid) 같은 입력으로 한 번 더
부른다. 따옴표 하나가 빠지는 식의 깨짐은 다시 부르면 대개 열린다. 래퍼 json_retry 에 다시 불렀는지와
첫 시도의 상태·원문을 남기고, 첫 시도 비용은 cost 에 더한다. 잘림(OUTPUT_TRUNCATED)·빈 응답·호출 실패는
다시 부르지 않는다 — 같은 설정이면 같은 자리에서 또 잘리고, 호출 실패는 스트림 재시도가 따로 있다.

## 판단하지 않는 층에 원인을 달면 한 번 다시 부른다

입력 market.judge_layers 가 false 인 층(±1% 이내)에 link 나 판정을 단 보고서는 같은 입력으로 한 번 더
부른다(judge_retry). JSON 재시도와 같은 방식이고, link 를 떼는 결정적 보정은 하지 않는다.

## 직접 언급이 0건이면 LLM 을 부르지 않는다

`mention: "mentioned"` 메시지와 `kind: "theme_recap"` 메시지가 하나도 없으면(시장 시황만 있어도) 정형 보고서를
낸다(canned_report, needs_llm). 테마 동향은 업종 단락이 sector 근거가 될 수 있어 있으면 LLM 을 부른다. 원인 칸은 비우고 "수집된 소식 없음" 을 적는다. 래퍼 skipped_llm 으로 가른다.

## 실패를 예외로 올리지 않는다

LLM 호출 실패·출력 잘림·빈 응답은 is_error=true 래퍼로 돌려준다. 여러 입력을 도는 중에 한 건이
죽었다고 뒤의 건까지 멈추면 안 되고, 실패한 회차도 "왜 실패했나" 를 남겨야 한다.
"""

import hashlib
import json
import logging
import re
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.llm.client import (
    PROMPT_DIR,
    LLMError,
    LLMTimeout,
    StreamInterrupted,
    complete,
    cost_currency,
    cost_detail,
    input_tokens,
)
from app.repositories.stock_move_analysis import KST
from app.services.stock_analysis.market_compare import display_as_of
from app.services.stock_analysis.stock_meta import sector, universe_weight
from app.services.stock_analysis.verify import (
    EMPTY_RESPONSE,
    LINKED_GROUP_SUFFIX,
    LLM_ERROR,
    OUTPUT_TRUNCATED,
    STREAM_INTERRUPTED,
    THEME_RECAP_KIND,
    _decimal,
    check_market_flags,
    check_schema,
    common_move,
    judge_layers,
    main_cause_sentences,
    market_led,
    mention_of,
    message_ids,
    move_case,
    move_comparison,
    move_strength_cap,
    normalize_payload,
    split_messages,
)

logger = logging.getLogger(__name__)

PROMPT_NAME = "stock_analysis_system"

# 프롬프트 1부 입력 형식에서 러너가 반드시 있어야 하는 칸. market 은 null 이 허용이라
# 빠져 있다. change_pct 는 ±1% 규칙과 초과분 판단의 기준이라 없으면 검증을 못 한다.
REQUIRED_INPUT = ("stock", "code", "target_date", "cutoff", "change_pct", "messages")
# 래퍼 skipped_llm 값. 근거 칸(messages)에 직접 언급·테마 동향 메시지가 0건이라 LLM 을 부르지 않고 정형 보고서(canned_report)를 냈다.
NO_DIRECT_MESSAGES = "NO_DIRECT_MESSAGES"

_FENCE = re.compile(r"```[A-Za-z]*[ \t]*\n(.*?)```", re.DOTALL)
# Windows 파일명에 못 쓰는 글자와 공백. run_id 는 파일명이 된다.
_UNSAFE = re.compile(r'[<>:"/\\|?*\s]+')
_HHMM = re.compile(r"(\d{1,2}):(\d{2})")
# check_input 의 target_date 형식. cutoff 도 이 꼴로 시작해야 한다(날짜만 있거나 시각만 있는 값을 막는다).
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 스트림이 중간에 끊기거나 시간 제한에 걸렸을 때 다시 보내는 횟수(둘을 합쳐 센다). 대개 일시적인 연결·
# 서버 지연이라 한 번은 다시 보내 볼 만하지만, 같은 입력이 거듭 그러면 입력이나 프록시 쪽 문제라 더 보내도 돈만 쓴다.
STREAM_RETRIES = 1


def prompt_sha256() -> str:
    """시스템 프롬프트 **파일 바이트**의 해시. 어떤 판으로 만든 보고서인지 가리는 키다.

    load_prompt() 의 반환값이 아니라 파일을 해시하는 이유: load_prompt 는 앞뒤 공백을
    걷어내므로, 파일을 열어 sha256sum 한 값과 맞춰 볼 수 있어야 추적이 된다.
    """
    return hashlib.sha256((PROMPT_DIR / f"{PROMPT_NAME}.md").read_bytes()).hexdigest()


def check_input(payload: Any) -> list[str]:
    """호출 전에 입력을 본다. 돈을 쓰고 나서 입력이 깨져 있었다는 걸 알면 헛돈다.

    target_date 는 YYYY-MM-DD, cutoff 는 시간대가 붙은 ISO 8601 시각이어야 한다. target_date 는 run_id 를 거쳐
    파일 이름이 되므로 형식이 틀린 값(예: "/", "..")이 경로에 들어가기 전에 막는다.
    """
    if not isinstance(payload, dict):
        return [f"입력이 객체가 아니다: {type(payload).__name__}"]
    problems = [f"{key} 가 없다" for key in REQUIRED_INPUT if key not in payload]
    change = payload.get("change_pct")
    if "change_pct" in payload and (isinstance(change, bool) or not isinstance(change, (int, float))):
        problems.append(f"change_pct 는 숫자여야 한다: {change!r}")
    if "target_date" in payload and not _is_date(payload["target_date"]):
        problems.append(f"target_date 는 YYYY-MM-DD 여야 한다: {payload['target_date']!r}")
    if "cutoff" in payload and not _is_aware_datetime(payload["cutoff"]):
        problems.append(f"cutoff 는 시간대가 붙은 ISO 8601 시각이어야 한다(예: 2026-10-21T15:30:00+09:00): "
                        f"{payload['cutoff']!r}")
    if "messages" in payload and not isinstance(payload["messages"], list):
        problems.append("messages 는 배열이어야 한다")
    return problems


def _is_date(value: Any) -> bool:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_aware_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not _DATE.match(value):
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def model_input(payload: dict[str, Any]) -> dict[str, Any]:
    """모델에 보낼 입력. 원본은 바꾸지 않는다(프롬프트 1부).

    - 메시지를 messages·market_context·flow 세 칸으로 나눈다(verify.split_messages). messages 칸 메시지에는
      입력 순서대로 id(m1…mN)를 붙인다(verify.message_ids). issue_trace 는 이 id 로 m1부터 N개를 적는다.
    - market 에 러너가 계산한 judge_layers·common_move 를 넣는다. 입력에 같은 칸이 있어도 다시 계산해
      덮어쓴다 — 계산은 verify 의 함수 한 곳에서만 한다. move_case 는 보내지 않는다(래퍼 집계에만 남긴다).
      market 이 null 이면 넣을 자리가 없어 그대로 둔다.
    러너는 이 함수에 넘기는 입력을 inputs_used/ 사본으로 남긴다. 그 사본으로 언제든 다시 만들 수 있다.
    inputs/ 사본은 받은 바이트 그대로라 시장 맥락을 넣고 KRX 로 덮어쓰기 전 값이다.
    - 메시지의 옛 칸 match(direct|indirect)는 mention(mentioned|not_mentioned)으로 옮겨 보낸다(verify.normalize_payload).
    """
    payload = normalize_payload(payload)
    out = {k: v for k, v in payload.items() if k != "messages"}
    # 업종 라벨(러너 종목 표). 테마 동향의 업종 단락과 relation: sector 판단에 쓴다(프롬프트 1부).
    out["sector"] = sector(payload.get("code"))
    # main_cause 에서 모델이 쓸 문장 수. 러너 고정 문장(finalize)을 더해도 3문장 이하가 되게 한다(프롬프트 4부).
    out["main_cause_sentences"] = main_cause_sentences(payload)
    # 화면 기준 시각(HH:MM)과 move 첫머리 문구. cutoff 가 장 마감 뒤면 그날 장 마감 시각이다(market_compare.display_as_of).
    # 보고서 as_of 는 cutoff 그대로이고 display_as_of·display_is_close 와 함께 finalize 가 넣는다.
    shown = display_as_of(payload)
    out["display_as_of"] = shown[0].strftime("%H:%M") if shown else None
    out["as_of_phrase"] = as_of_phrase(payload)
    out.update(split_messages(payload))
    out["messages"] = [{"id": i, **m} for i, m in message_ids(payload)]
    market = payload.get("market")
    if isinstance(market, dict):
        out["market"] = {**{k: v for k, v in market.items() if k != "move_case"},
                         "judge_layers": judge_layers(payload), "common_move": common_move(payload),
                         "move_strength_cap": move_strength_cap(payload), "market_led": market_led(payload),
                         "move_comparison": move_comparison(payload),
                         "universe_weight": universe_weight(payload.get("code"))}
    return out


def direct_message_count(payload: dict[str, Any]) -> int:
    """`mention: "mentioned"` 메시지 수. 공통 시황처럼 not_mentioned 로만 들어온 메시지는 세지 않는다."""
    messages = payload.get("messages")
    return sum(isinstance(m, dict) and mention_of(m) == "mentioned"
               for m in (messages if isinstance(messages, list) else []))


def needs_llm(payload: dict[str, Any]) -> bool:
    """LLM 을 부를 입력인가. 근거 칸(messages)에 mentioned 메시지나 theme_recap 메시지가 있으면 부른다.

    테마 동향은 이 종목 업종 단락이면 sector 근거가 될 수 있어(프롬프트 1부) 직접 언급이 없어도 부른다.
    market_context(시장 시황·전날 장 설명)와 flow(매매 순위)는 근거가 될 수 없어 세지 않는다.
    둘 다 없으면 정형 보고서를 낸다.
    """
    messages = split_messages(payload)["messages"]
    return any(mention_of(m) == "mentioned" or m.get("kind") == THEME_RECAP_KIND for m in messages)


def _has_batchim(word: str) -> bool:
    """마지막 글자가 받침 있는 한글인가. 받침 없음·영문·숫자는 False."""
    last = word[-1:] if word else ""
    return "가" <= last <= "힣" and bool((ord(last) - 0xAC00) % 28)


def _topic_josa(word: str) -> str:
    """은/는. 마지막 글자가 받침 있는 한글이면 은, 그 밖(받침 없음·영문·숫자)은 는."""
    return "은" if _has_batchim(word) else "는"


def _with_josa(word: str) -> str:
    """과/와."""
    return "과" if _has_batchim(word) else "와"


def _object_josa(word: str) -> str:
    """을/를."""
    return "을" if _has_batchim(word) else "를"


def _pct(value: Decimal) -> str:
    return f"{abs(value):.2f}%"


def _verb(value: Decimal, base: str = "") -> str:
    """오른/내린 방향의 말. base 가 '' 면 '올랐'·'내렸', '날' 이면 '오른'·'내린'."""
    up, down = ("오른", "내린") if base else ("올랐", "내렸")
    return up if value > 0 else down


def as_of_phrase(payload: dict[str, Any]) -> str:
    """기준 시각 문구. 장 마감 이후면 '오후 3시 30분 장 마감 기준'(마감이 늦춰진 날은 '오후 4시 30분 장 마감 기준'),
    장중이면 '오전 11시 기준' 처럼. 시각은 market_compare.display_as_of 가 정한다."""
    shown = display_as_of(payload)
    if shown is None:
        return "기준 시각"
    at, close = shown
    hour, minute = at.hour, at.minute
    when = f"{'오전' if hour < 12 else '오후'} {hour if hour <= 12 else hour - 12}시" + (f" {minute}분" if minute else "")
    return f"{when} 장 마감 기준" if close else f"{when} 기준"


def _canned_move(payload: dict[str, Any]) -> str:
    """정형 보고서의 summary.move. 프롬프트 4부 move 와 같은 내용(기준 시각, 종목·코스피 등락률, 대형주
    움직임과 비교)을 숫자로만 채운다. 입력에 없는 칸은 그 문장을 뺀다."""
    stock = str(payload.get("stock") or payload.get("code") or "이 종목")
    change = _decimal(payload.get("change_pct"))
    head = f"{as_of_phrase(payload)} {stock}{_topic_josa(stock)}"
    sentences = [f"{head} 등락이 없었습니다." if not change else f"{head} {_pct(change)} {_verb(change)}습니다."]
    market = payload.get("market") if isinstance(payload.get("market"), dict) else {}
    index, index_pct = market.get("index") or "코스피", _decimal(market.get("change_pct"))
    peer = _decimal(market.get("peer_median_pct"))
    # "같은 시각 코스피는 0.30% 올랐고, 대형주 19개 중 14개가 내렸으며 중간값은 1.57% 하락이었습니다."
    index_stem = None  # "코스피는 0.30% 올랐" — 뒤에 "고," 나 "습니다." 를 붙인다
    if index_pct is not None:
        index_stem = f"{index}{_topic_josa(index)} " + (f"{_pct(index_pct)} {_verb(index_pct)}" if index_pct
                                                        else "보합이었")
    peers = None
    if peer is not None and isinstance(market.get("peer_total"), int):
        up, down = market.get("peer_up") or 0, market.get("peer_down") or 0
        many = f"{down}개가 내렸으며" if down >= up else f"{up}개가 올랐으며"
        trend = "보합" if not peer else ("상승" if peer > 0 else "하락")
        peers = f"대형주 {market['peer_total']}개 중 {many} 중간값은 {_pct(peer)} {trend}이었습니다."
    if index_stem and peers:
        sentences.append(f"같은 시각 {index_stem}고, {peers}")
    elif index_stem:
        sentences.append(f"같은 시각 {index_stem}습니다.")
    elif peers:
        sentences.append(f"같은 시각 {peers}")
    if change and peer is not None and market.get("excess_pct") is not None:
        if not judge_layers(payload)["relative"]:
            relation = "대형주 전반과 비슷하게 움직였습니다"
        elif change * peer < 0:
            relation = "대형주 전반과 반대로 움직였습니다"
        else:
            relation = f"대형주 전반보다 {'더' if abs(change) > abs(peer) else '덜'} {_verb(change)}습니다"
        sentences.append(f"{stock}{_topic_josa(stock)} {relation}.")
    sentences += _canned_kospi(payload, stock)
    return " ".join(sentences)


def _compare_ok(payload: dict[str, Any]) -> dict[str, Any] | None:
    """입력 market_compare 가 비교 문장을 쓸 수 있는 상태(ok)면 그 칸. 아니면 None(프롬프트 3단계 「비교 수치」)."""
    compare = payload.get("market_compare")
    return compare if isinstance(compare, dict) and compare.get("status") == "ok" else None


def _kospi_base(kospi: dict[str, Any], stock: str) -> tuple[str, Decimal | None]:
    """(기준 시장 이름, 그 등락률). kospi_basis 가 kospi_ex_self 면 "<종목명>을 뺀 코스피" 다."""
    if kospi.get("kospi_basis") == "kospi_ex_self":
        return f"{stock}{_object_josa(stock)} 뺀 코스피", _decimal(kospi.get("kospi_ex_self_change_rate_pct"))
    return "코스피", _decimal(kospi.get("kospi_change_rate_pct"))


def _moved(value: Decimal | None) -> str:
    """'올랐'·'내렸'·'움직였'(보합·모름). 뒤에 '습니다'·'고'·'지만' 을 붙인다."""
    return "움직였" if not value else _verb(value)


def _canned_kospi(payload: dict[str, Any], stock: str) -> list[str]:
    """summary.move 의 코스피 판정 문장(프롬프트 4부 move, 3단계 kospi_relation 표). 판정이 없으면 []."""
    compare = _compare_ok(payload)
    kospi = compare.get("kospi") if compare else None
    relation = kospi.get("kospi_relation") if isinstance(kospi, dict) else None
    if relation is None:
        return []
    base, base_pct = _kospi_base(kospi, stock)
    change = _decimal(kospi.get("stock_change_rate_pct"))
    topic = f"{stock}{_topic_josa(stock)}"
    if kospi.get("kospi_basis") == "kospi_ex_self":
        # 비중·기여도와 자기 제외 코스피 판정을 한 문장으로 쓴다. 두 문장이면 move 가 5문장까지 되어 4부 상한(최대 4문장)을
        # 넘는다. "삼성전자는 코스피 비중이 28.80%여서 코스피 등락 가운데 0.51%포인트를 끌어올렸고, 삼성전자를 뺀 코스피는
        # 0.20% 올라 삼성전자는 시장 흐름과 비슷하게 움직였습니다."
        weight, share = _decimal(kospi.get("kospi_weight_pct")), _decimal(kospi.get("kospi_contribution_pp"))
        clauses = []
        if weight is not None and share:
            clauses.append(f"{topic} 코스피 비중이 {_pct(weight)}여서 코스피 등락 가운데 {abs(share)}%포인트를 "
                           f"{'끌어올렸' if share > 0 else '끌어내렸'}")
        if base_pct is not None:  # 자기 제외 코스피 등락률은 앞 문장에 없다
            clauses.append(_ex_self_clause(relation, base, base_pct, topic, change))
        return [f"{'고, '.join(clauses)}습니다."] if clauses else []
    # 기준이 코스피면 두 등락률은 앞 문장에 있다. 방향과 판정만 쓴다
    if relation == "follows":
        return [f"{topic} {base}{_with_josa(base)} 비슷하게 움직였습니다."]
    if relation == "opposite" or (change and base_pct and change * base_pct < 0):
        link = "고" if relation == "opposite" else "지만"
        return [f"{base}{_topic_josa(base)} {_moved(base_pct)}{link} {topic} {_moved(change)}습니다."]
    return [f"{topic} {base}{_with_josa(base)} 다르게 움직였습니다."]


def _went(value: Decimal) -> str:
    """'올라'·'내려'. 뒤에 이어지는 말을 붙인다."""
    return "올라" if value > 0 else "내려"


def _ex_self_clause(relation: str, base: str, base_pct: Decimal, topic: str, change: Decimal | None) -> str:
    """자기 제외 코스피 판정 구절. 끝이 '움직였'·'올랐' 처럼 열려 있어 '습니다' 를 붙인다(3단계 kospi_relation 표).

    follows   "삼성전자를 뺀 코스피는 0.20% 올라 삼성전자는 시장 흐름과 비슷하게 움직였"
    opposite  "삼성전자를 뺀 코스피는 0.20% 내렸고 삼성전자는 올랐" — 판정하는 말을 쓰지 않는다
    diverges  "… 0.20% 올라 삼성전자는 시장 흐름과 다르게 움직였", 방향이 반대면
              "… 0.20% 내렸지만 삼성전자는 올라 시장 흐름과 다르게 움직였"
    """
    head = f"{base}{_topic_josa(base)}"
    if relation == "opposite":
        moved = f"{_pct(base_pct)} {_verb(base_pct)}" if base_pct else "보합이었"
        return f"{head} {moved}고 {topic} {_moved(change)}"
    if change and base_pct and change * base_pct < 0:
        return f"{head} {_pct(base_pct)} {_verb(base_pct)}지만 {topic} {_went(change)} 시장 흐름과 다르게 움직였"
    went = f"{_pct(base_pct)} {_went(base_pct)}" if base_pct else "보합이라"
    return f"{head} {went} {topic} 시장 흐름과 {'비슷하게' if relation == 'follows' else '다르게'} 움직였"


def _group_who(peer: dict[str, Any]) -> str:
    """"같은 은행지주 그룹의 신한지주·하나금융지주", 연동 그룹은 "SK하이닉스 지분으로 이어진 SK스퀘어·SK"."""
    group = str(peer.get("group"))
    names = "·".join(str(m.get("name")) for m in peer.get("members_used") or [] if isinstance(m, dict))
    if group.endswith(LINKED_GROUP_SUFFIX):
        return f"{group.removesuffix(LINKED_GROUP_SUFFIX)} 지분으로 이어진 {names}"
    return f"같은 {group} 그룹의 {names}"


def _group_amount(peer: dict[str, Any], *, noun: bool) -> str:
    """그룹 등락률. 두 종목 이상이면 "대체로 X% 안팎"(통계 용어를 쓰지 않는다), 한 종목이면 그 종목 등락률.
    noun 이면 "대체로 3.01% 안팎 오른"(뒤에 종목이 온다), 아니면 "대체로 3.01% 안팎 올랐"."""
    rate = _decimal(peer.get("median_change_rate_pct"))
    many = len(peer.get("members_used") or []) >= 2
    if not rate:
        return ("대체로 " if many else "") + ("보합인" if noun else "보합이었")
    return ("대체로 " if many else "") + f"{_pct(rate)}" + (" 안팎" if many else "") + f" {_verb(rate, '날' if noun else '')}"


def _canned_relative(payload: dict[str, Any]) -> str | None:
    """summary.relative 의 코스피·그룹 비교 문장(프롬프트 4부 relative 첫 문장 표). 그룹마다 한 문장이다.

    코스피는 수치 없이 말로만, 첫 번째 follows 그룹 문장에만 넣는다. 그룹 비교를 쓸 수 없으면(market_compare 가 ok 가
    아니거나 그룹 판정이 모두 null) None 이다. 그룹이 없는 종목의 코스피 비교는 summary.move 에 있다(_canned_kospi).
    """
    compare = _compare_ok(payload)
    if compare is None:
        return None
    stock = str(payload.get("stock") or payload.get("code") or "이 종목")
    topic = f"{stock}{_topic_josa(stock)}"
    kospi = compare.get("kospi") if isinstance(compare.get("kospi"), dict) else {}
    kospi_relation = kospi.get("kospi_relation")
    base, base_pct = _kospi_base(kospi, stock)
    change = _decimal(kospi.get("stock_change_rate_pct"))
    sentences = []
    for peer in compare.get("peers") or []:
        relation = peer.get("relation") if isinstance(peer, dict) else None
        if relation is None:
            continue
        who = _group_who(peer)
        noun = f"{_group_amount(peer, noun=True)} {who}"  # "대체로 3.01% 안팎 오른 같은 은행지주 그룹의 …"
        with_group = f"{noun}{_with_josa(who)}"
        if relation == "follows":
            if kospi_relation == "follows":
                sentence = f"{topic} {base}, 그리고 {with_group} 비슷하게 움직여 시장 전체 흐름을 따라갔습니다."
            elif kospi_relation == "opposite":
                sentence = f"{base}{_topic_josa(base)} {_moved(base_pct)}고 {topic} {with_group} 함께 {_moved(change)}습니다."
            elif kospi_relation == "diverges" and change and base_pct and change * base_pct < 0:
                sentence = f"{base}{_topic_josa(base)} {_moved(base_pct)}지만 {topic} {with_group} 함께 {_moved(change)}습니다."
            elif kospi_relation == "diverges":
                sentence = f"{topic} {base}{_with_josa(base)}는 다르게 {with_group} 함께 움직였습니다."
            else:
                sentence = f"{topic} {with_group} 함께 {_moved(change)}습니다."
            kospi_relation = None  # 코스피는 한 번만 쓴다
        elif relation == "diverges":
            sentence = f"{topic} {with_group} 크게 달랐습니다."
        elif relation == "opposite":
            moved = f"{_pct(change)} {_verb(change)}" if change else "보합이었"
            sentence = f"{who}{_topic_josa(who)} {_group_amount(peer, noun=False)}고, {topic} {moved}습니다."
        else:  # inconclusive — 판정하는 말 없이 비교 종목 등락률만
            sentence = f"{who}{_topic_josa(who)} {_group_amount(peer, noun=False)}습니다."
        sentences.append(sentence)
    return " ".join(sentences) or None


def canned_report(payload: dict[str, Any]) -> dict[str, Any]:
    """직접 언급·테마 동향 메시지가 0건인 날의 정형 보고서. LLM 을 부르지 않는다(needs_llm).

    두 판정은 no_clear_cause, 근거·참고 재료는 비운다. 소식이 없는 날일수록 코스피·그룹 흐름 설명이 필요해서, 입력
    market_compare 의 판정으로 코스피 판정 문장(summary.move 끝)과 그룹 비교 문장(summary.relative)을 템플릿으로 쓴다. 화면은 이 보고서를 "수집된 소식 없음" 으로 보여 줄 수
    있게 래퍼 skipped_llm 칸으로 가른다. 프롬프트 4부와 같게 common_move 날은 main_cause 첫 문장에 그 사실을 쓴다.
    """
    change = _decimal(payload.get("change_pct"))
    shown = display_as_of(payload)
    main_cause = "제공된 메시지에서 확인된 원인은 없습니다."
    if common_move(payload) and change:
        main_cause = f"대형주 전반이 함께 {_verb(change, '날')} 날이었습니다. " + main_cause
    return {
        "ticker": payload.get("code"), "name": payload.get("stock"), "date": payload.get("target_date"),
        # as_of 는 메시지를 자른 시각(cutoff) 그대로, display_* 는 화면 기준 시각이다(finalize.fix_as_of 와 같다)
        "as_of": payload.get("cutoff"),
        "display_as_of": shown[0].isoformat() if shown else None,
        "display_is_close": shown[1] if shown else None,
        "change_pct": payload.get("change_pct"),
        "verdict": "no_clear_cause", "relative_verdict": "no_clear_cause",
        "summary": {"move": _canned_move(payload), "main_cause": main_cause, "relative": _canned_relative(payload),
                    "counter": None, "unexplained": "이 종목을 직접 다룬 소식이 수집되지 않았습니다."},
        "factors": [], "terms": [], "background": {"bullish": [], "bearish": [], "neutral": []},
        "not_found": [("직접 언급(mention: mentioned)·테마 동향(kind: theme_recap) 메시지가 0건이라 LLM 을 부르지 않고 "
                       "정형 보고서를 냈다")],
        "events": [],
    }


def _canned_wrapper(payload: dict[str, Any], *, prompt_hash: str, run_id: str) -> dict[str, Any]:
    report = canned_report(payload)
    wrapper = _base_wrapper(payload, prompt_hash=prompt_hash, run_id=run_id)
    final_text = json.dumps(report, ensure_ascii=False)
    wrapper.update(final_text=final_text, json_status="clean", schema_problems=check_schema(report),
                   skipped_llm=NO_DIRECT_MESSAGES, json_retry={"retried": False},
                   judge_retry={"retried": False})
    return wrapper


def _cutoff_hhmm(cutoff: Any) -> str:
    if isinstance(cutoff, str):
        try:
            return datetime.fromisoformat(cutoff.strip()).strftime("%H%M")
        except ValueError:
            pass
        m = _HHMM.search(cutoff)
        if m:
            return f"{int(m.group(1)):02d}{m.group(2)}"
    return "cutoff"


def make_run_id(payload: dict[str, Any], repeat: int = 1) -> str:
    """`<종목>-<날짜>-<기준시각 HHMM>__r<반복>`.

    기존 산출물의 `<종목>-<날짜>-<조건>__<반복>` 꼴을 따랐다. 조건 자리에 기준 시각을
    넣은 건 같은 날 같은 종목이 시각별로 여러 판 나오기 때문이다. 같은 판을 다시 돌리면
    반복 번호로 가른다(부르는 쪽이 정한다).
    """
    stock = _UNSAFE.sub("_", str(payload.get("stock") or payload.get("code") or "unknown"))
    return f"{stock}-{payload.get('target_date')}-{_cutoff_hhmm(payload.get('cutoff'))}__r{repeat}"


def extract_json(text: str) -> tuple[str, dict[str, Any] | None, str]:
    """(json_status, 보고서, final_text 에 넣을 텍스트).

        clean     응답 그대로 JSON 객체
        stripped  코드펜스나 머리말·꼬리말을 벗겨야 열린다
        invalid   그래도 안 열린다. 보고서는 None, 텍스트는 원문 그대로
    """
    body = text.strip()
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            return "clean", parsed, body
    except json.JSONDecodeError:
        pass

    candidates = [m.group(1).strip() for m in _FENCE.finditer(body)]
    start, end = body.find("{"), body.rfind("}")
    if start != -1 and end > start:
        candidates.append(body[start:end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return "stripped", parsed, candidate
    return "invalid", None, body


def looks_like_question(text: str) -> bool:
    """되물었나. 프롬프트가 금지하지만 정보가 부족하면 모델이 질문으로 끝내는 날이 있다."""
    return text.rstrip().endswith(("?", "？"))


def report_of(wrapper: dict[str, Any]) -> dict[str, Any] | None:
    """래퍼에서 보고서를 다시 편다. 열린 회차(clean·stripped)만."""
    if wrapper.get("is_error") or wrapper.get("json_status") not in ("clean", "stripped"):
        return None
    report = json.loads(wrapper["final_text"])
    return report if isinstance(report, dict) else None


def _merge_retry_costs(wrapper: dict[str, Any], first: dict[str, Any]) -> None:
    """다시 부른 래퍼에 첫 시도의 비용·시간·스트림 끊김을 더한다."""
    wrapper["cost"] += first["cost"]
    wrapper["duration_ms"] += first["duration_ms"]
    wrapper["stream_interruptions"] = first["stream_interruptions"] + wrapper["stream_interruptions"]
    wrapper["timeouts"] = first.get("timeouts", []) + wrapper["timeouts"]


async def generate(
    payload: dict[str, Any], *, system: str, prompt_hash: str, run_id: str
) -> dict[str, Any]:
    """입력 하나로 보고서를 만들어 래퍼로 감싼다. 예외를 던지지 않는다.

    JSON 이 안 열린 회차는 한 번 다시 부른다(모듈 docstring). 래퍼 json_retry 칸:
    {"retried": false} 또는 {"retried": true, "first": {json_status, asked_question, raw_text, usage,
    cost, duration_ms}}.

    보고서가 열렸는데 입력 market 의 러너 계산 값을 어겼으면(verify.check_market_flags — judge_layers 가 false 인
    층에 link·판정, move_strength_cap 이 partial 인 날 등락 층 종목 고유 재료가 sufficient) 같은 입력으로 한 번 더 부른다. 피드백 문구는 넣지 않는다. link 를 떼는 결정적 보정은 하지 않는다 —
    summary 문장이 떼어 낸 원인을 그대로 말하게 된다. 래퍼 judge_retry 칸: {"retried": false} 또는
    {"retried": true, "first": {problems, final_text, json_retry, usage, cost, duration_ms}}.
    다시 불러도 위반이면 그대로 둔다(검증에서 failed).
    """
    if not needs_llm(payload):
        logger.info("%s: 직접 언급·테마 동향 메시지가 없어 LLM 을 부르지 않고 정형 보고서를 낸다", run_id)
        return _canned_wrapper(payload, prompt_hash=prompt_hash, run_id=run_id)
    wrapper = await _generate_with_json_retry(payload, system=system, prompt_hash=prompt_hash,
                                              run_id=run_id)
    report = report_of(wrapper)
    problems = check_market_flags(report, payload) if report is not None else []
    if not problems:
        wrapper["judge_retry"] = {"retried": False}
        return wrapper
    logger.warning("%s: 판단하지 않는 층에 원인을 달아 한 번 다시 부른다: %s", run_id, "; ".join(problems))
    first = wrapper
    wrapper = await _generate_with_json_retry(payload, system=system, prompt_hash=prompt_hash,
                                              run_id=run_id)
    wrapper["judge_retry"] = {"retried": True, "first": {
        "problems": problems,
        **{key: first[key] for key in ("final_text", "json_retry", "usage", "cost", "duration_ms")}}}
    _merge_retry_costs(wrapper, first)
    return wrapper


async def _generate_with_json_retry(
    payload: dict[str, Any], *, system: str, prompt_hash: str, run_id: str
) -> dict[str, Any]:
    """_generate_once 한 번, JSON 이 안 열렸으면 한 번 더. json_retry 칸을 채운다."""
    wrapper = await _generate_once(payload, system=system, prompt_hash=prompt_hash, run_id=run_id)
    if wrapper["is_error"] or wrapper["json_status"] != "invalid":
        wrapper["json_retry"] = {"retried": False}
        return wrapper
    logger.warning("%s: JSON 이 열리지 않아 한 번 다시 부른다", run_id)
    first = wrapper
    wrapper = await _generate_once(payload, system=system, prompt_hash=prompt_hash, run_id=run_id)
    wrapper["json_retry"] = {"retried": True, "first": {
        key: first[key] for key in ("json_status", "asked_question", "raw_text", "usage", "cost",
                                    "duration_ms")}}
    _merge_retry_costs(wrapper, first)
    return wrapper


def _base_wrapper(payload: dict[str, Any], *, prompt_hash: str, run_id: str) -> dict[str, Any]:
    """LLM 을 부르기 전의 래퍼. 결과 칸은 비어 있고 요청 설정·입력 계산 칸만 채운다."""
    stream = settings.stock_analysis_streams()
    max_tokens = settings.summary_max_tokens
    return {
        "run_id": run_id,
        "final_text": "",
        "json_status": None,
        "schema_problems": [],
        "is_error": False,
        "asked_question": False,
        # 실패 종류. 검증 사유 코드로 그대로 쓴다(verify.verify_wrapper).
        "error_code": None,
        "error": None,
        # clean 이 아닐 때만 채운다. clean 이면 final_text 와 같아서 두 번 담을 이유가 없다.
        "raw_text": None,
        # 운영 지표. 적재 모듈은 이 아래를 읽지 않는다(보고서 표에 넣지 않기로 했다).
        "provider": settings.llm_provider,
        "model": settings.summary_model,
        # 요청 설정. 잘림·끊김을 볼 때 어떤 설정으로 보냈는지가 먼저 필요하다.
        "stream": stream,
        "max_completion_tokens": max_tokens,
        "reasoning_effort": settings.summary_reasoning_effort,
        # 스트림이 끊긴 시도마다 {"partial_chars", "error"}. 받은 부분의 본문은 남기지 않는다.
        # 끊긴 시도는 usage 를 못 받아 비용이 cost 에 들어가지 않는다.
        "stream_interruptions": [],
        # 시간 제한에 걸린 시도마다 {"error", "seconds"}. 받은 부분이 없고 usage 도 없어 비용에 들어가지 않는다.
        "timeouts": [],
        "usage": {},
        # 입력 토큰 내역(client.input_tokens). usage.prompt_tokens 는 캐시 쓰기 할증이 섞여
        # 첫 호출이 부풀어 보이므로 실제 입력 수는 여기 total 을 본다.
        "input_tokens": None,
        # 통화는 프로바이더마다 다르다(OpenRouter 달러, Elice 원화). 숫자만 두면 합산할 때 섞인다.
        "cost": 0.0,
        "cost_currency": cost_currency(),
        # provider(응답이 준 비용) | token_rates(단가로 계산) | unavailable(usage 누락).
        # token_rates 면 쓴 단가가 cost_rates 에.
        "cost_basis": None,
        "cost_rates": None,
        # finish_reason=length 일 때만 채운다. 잘린 자리를 보고 상한·추론 강도를 정한다.
        "truncation": None,
        "duration_ms": 0,
        "prompt_name": PROMPT_NAME,
        "prompt_sha256": prompt_hash,
        # 래퍼에 생성 시각이 없어 실행 디렉터리 이름에 기대던 것을 여기 직접 남긴다.
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        # 케이스별 집계용. flat | opposite | normal, 시장 몫을 모르면 null. 적재 모듈은 읽지
        # 않는다 — DB 칼럼은 백엔드에서 필요해질 때 만든다.
        "move_case": move_case(payload),
        # 모델에 보낸 market 계산 칸. market 이 null 이면 보내지 않았으므로 null.
        "judge_layers": judge_layers(payload) if isinstance(payload.get("market"), dict) else None,
        "common_move": common_move(payload) if isinstance(payload.get("market"), dict) else None,
        "move_strength_cap": move_strength_cap(payload) if isinstance(payload.get("market"), dict) else None,
        "market_led": market_led(payload) if isinstance(payload.get("market"), dict) else None,
        "move_comparison": move_comparison(payload) if isinstance(payload.get("market"), dict) else None,
        "main_cause_sentences": main_cause_sentences(payload),
        "sector": sector(payload.get("code")),
        "universe_weight": universe_weight(payload.get("code")),
    }


async def _generate_once(
    payload: dict[str, Any], *, system: str, prompt_hash: str, run_id: str
) -> dict[str, Any]:
    """complete() 한 번(스트림 끊김 재시도 포함)으로 래퍼 하나를 만든다.

    모델·타임아웃은 `complete()` 가 settings 에서 읽는다. 래퍼의 model 도 같은 settings 값을
    적는다 — complete 를 model 인자 없이 부르므로 둘이 같다. 스트리밍 여부와 출력 상한은
    여기서 명시해 넘기고, 추론 강도와 함께 래퍼에 남긴다.
    """
    started = time.monotonic()
    wrapper = _base_wrapper(payload, prompt_hash=prompt_hash, run_id=run_id)
    stream, max_tokens = wrapper["stream"], wrapper["max_completion_tokens"]
    user = json.dumps(model_input(payload), ensure_ascii=False, indent=2)
    for attempt in range(STREAM_RETRIES + 1):
        try:
            text, usage = await complete(system, user, max_tokens=max_tokens, stream=stream)
            break
        except StreamInterrupted as exc:
            logger.warning("%s: %s (시도 %d)", run_id, exc, attempt + 1)
            wrapper["stream_interruptions"].append(
                {"partial_chars": exc.partial_chars, "error": str(exc)})
            if attempt < STREAM_RETRIES:
                continue
            # 부분 응답은 열어 보지도 저장하지도 않는다. 길이만 stream_interruptions 에 있다.
            wrapper.update(is_error=True, error_code=STREAM_INTERRUPTED, error=str(exc))
        except LLMTimeout as exc:
            logger.warning("%s: %s (시도 %d)", run_id, exc, attempt + 1)
            wrapper["timeouts"].append({"error": str(exc),
                                        "seconds": round(time.monotonic() - started, 1)})
            if attempt < STREAM_RETRIES:
                continue
            wrapper.update(is_error=True, error_code=LLM_ERROR, error=str(exc))
        except LLMError as exc:
            logger.warning("%s: %s", run_id, exc)
            wrapper.update(is_error=True, error_code=LLM_ERROR, error=str(exc))
        wrapper["duration_ms"] = round((time.monotonic() - started) * 1000)
        return wrapper

    wrapper["usage"] = usage
    wrapper["cost"], wrapper["cost_basis"] = cost_detail(usage)
    if wrapper["cost_basis"] == "token_rates":
        wrapper["cost_rates"] = settings.token_rates()
    if wrapper["cost_basis"] != "unavailable":
        wrapper["input_tokens"] = input_tokens(usage)
    else:
        logger.warning("%s: usage 가 오지 않아 토큰·비용을 알 수 없다", run_id)
    wrapper["duration_ms"] = round((time.monotonic() - started) * 1000)

    if usage.get("finish_reason") == "length":
        # 출력 상한에 걸렸다. 본문이 비었으면 추론에 예산을 다 쓴 것이고, 있으면 쓰다 잘린 것이다.
        # 잘린 JSON 은 열려도 믿을 수 없어 열어 보지 않는다. 재시도도 하지 않는다 — 같은
        # 설정이면 같은 자리에서 또 잘린다(verify.OUTPUT_TRUNCATED).
        details = usage.get("completion_tokens_details")
        reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
        wrapper["truncation"] = {
            "body_empty": not text,
            "body_chars": len(text),
            "reasoning_tokens": reasoning,
            "completion_tokens": usage.get("completion_tokens"),
        }
        wrapper.update(
            is_error=True, json_status="invalid", error_code=OUTPUT_TRUNCATED,
            raw_text=text or None,
            error=(f"출력 상한에서 잘림 (본문 {'없음' if not text else f'{len(text)}자'}, "
                   f"reasoning_tokens={reasoning}, completion_tokens={usage.get('completion_tokens')})"),
        )
        return wrapper

    if not text:
        # 추론 모델이 예산을 사고에 다 쓰면 빈 본문이 정상 응답으로 온다. 비용은 나갔으니
        # usage·cost 는 남기고 실행 실패로 표시한다.
        wrapper.update(
            is_error=True, json_status="invalid", error_code=EMPTY_RESPONSE,
            error=f"빈 응답 (finish_reason={usage.get('finish_reason')})",
        )
        return wrapper

    status, report, final_text = extract_json(text)
    # 1단계 이슈 목록(issue_trace)은 실행 기록에만 남긴다. 보고서 스키마에 넣지 않는다.
    if report is not None and "issue_trace" in report:
        wrapper["issue_trace"] = report.pop("issue_trace")
        final_text = json.dumps(report, ensure_ascii=False)
    wrapper["json_status"] = status
    wrapper["final_text"] = final_text
    if status != "clean":
        wrapper["raw_text"] = text
    if report is None:
        wrapper["asked_question"] = looks_like_question(text)
    else:
        wrapper["schema_problems"] = check_schema(report)
    return wrapper


__all__ = [
    "NO_DIRECT_MESSAGES",
    "PROMPT_NAME",
    "as_of_phrase",
    "canned_report",
    "check_input",
    "direct_message_count",
    "extract_json",
    "generate",
    "looks_like_question",
    "make_run_id",
    "model_input",
    "needs_llm",
    "prompt_sha256",
    "report_of",
]
