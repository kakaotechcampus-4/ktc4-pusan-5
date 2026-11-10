# 케이스 추가·수정 가이드

새 케이스를 만들거나 기존 케이스를 고칠 때의 절차를 정리함. 필드 정의는 `schema.md`, 라벨링 기준은 `../rubric.md`, 검증 도구는 `../validate_gold.md` 를 봄.

- 이 세트의 케이스 10건은 아래 절차로 만들었음. 조립에 쓴 임시 스크립트(DB 조회, KRX 계산, KIND 접수 시각 매칭)는 저장소에 없고, 이 문서의 코드 조각이 그 요지임. 그대로 복사하지 말고 경로와 날짜를 바꿔 씀.
- 모든 명령은 `ai/` 폴더에서 실행함. 앱 코드를 import 하는 스크립트는 `PYTHONPATH=. uv run python ...` 으로 돌림.
- 접속 정보와 API 키는 `ai/.env`(및 설정 코드)에서 읽음. 문서·스크립트·커밋에 값을 적지 않음.

## 0. 시작 전 점검

| 항목 | 확인 방법 |
|---|---|
| DB 가 떠 있음 | 수집기 DB(`basis-db` 컨테이너)에 접속되는지 확인. 메시지 테이블은 `telegram_messages`, 채널은 `channel`, 공시는 `dart_disclosures` |
| KRX 키가 동작함 | `ai/.env` 의 KRX 키. 안 맞으면 시장 값(3단계)을 못 구함 |
| 브랜치 | `feature/` 로 시작하는 브랜치. `main` 에서 작업하지 않음 |
| 고정 값 | `cutoff` 는 대상일 18:45 KST, 입력 창은 직전 거래일 15:30 초과 ~ `cutoff` 이하 |

## 1. 대상일·종목 정하기

1. **확정일만** 씀. 당일은 KRX 가 `no_data` 를 줌.
2. 종목이 충분히 언급됐는지 먼저 셈. 메시지가 너무 적으면 gold 를 쓸 재료가 없음.
3. 노리는 함정을 정함(`schema.md` 3-9 번호표). 한 케이스가 함정 여러 개를 겸해도 됨.
4. **결과를 알고 고르는 편향**에 주의함. 눈에 띄는 날만 고르면 "원인이 있는 날"만 모임. 원인 없는 날(예: c07)과 호재인데 하락한 날(예: c05)도 일부러 넣음.
5. 같은 종목·날짜가 이미 있는지 `cases/` 에서 확인함.

종목별 언급 수는 별칭 포함으로 셈(다음 단계의 별칭 목록으로 `text` 를 검색).

## 2. 별칭 정하기

메시지 검색의 기준이므로 빠뜨리면 케이스가 빈약해짐.

- 한글 종목명 + **영문명·약칭**을 모두 넣음(예: 삼성전기 → `삼성전기`, `Samsung Electro-Mechanics`, `Samsung Electro`, `SEMCO`).
- 종목명이 다른 종목명에 포함되는 경우(예: `HD현대` 가 `HD현대중공업`·`HD현대일렉트릭` 에도 걸림)는 걸러낼 규칙을 정함. 이 경우 유사 종목 혼동 함정(9번)으로 일부러 둔 것이 아니면 계열사 단독 메시지는 `notes.md` 에 어떻게 처리했는지 적음.
- 별칭을 나중에 추가하면 이미 만든 케이스의 메시지가 늘어남. 추가 후에는 해당 케이스의 gold 사건을 다시 점검함.

## 3. 입력 만들기

### 3-1. 메시지 추출

`telegram_messages` 에서 입력 창 안의 메시지를 가져와 본문에 별칭이 있는 것만 남김. 삭제 표시(`purged_at`)가 있는 것은 뺌.

```python
K = dt.timezone(dt.timedelta(hours=9))
lo = dt.datetime(2026, 10, 21, 15, 30, tzinfo=K)   # 직전 거래일 15:30
hi = dt.datetime(2026, 10, 22, 18, 45, tzinfo=K)   # cutoff
sql = """select t.text, t.posted_at, t.url
         from telegram_messages t join channel ch on ch.id = t.channel_id
         where t.purged_at is null and t.posted_at > :lo and t.posted_at <= :hi
         order by t.posted_at"""
# 본문 필터: re.search("LG디스플레이|LG Display", text, re.I)
```

- 시각은 `posted_at`(편집된 글은 최초 본문 기준)을 KST 로 변환해 `datetime_kst` 에 씀.
- 시황·테마 메시지처럼 종목명이 없는 것은 넣지 않음(`mention: mentioned` 만). 코스피 시황 메시지를 넣을지는 케이스별로 판단하고 `notes.md` 에 이유를 적음.

### 3-2. `case.json` 쓰기

필드는 `schema.md` §1. 주의할 점
- `change_pct` 는 KRX 종목 등락률(%)을 소수 둘째 자리로 넣음. 3단계에서 구한 값과 같아야 함.
- `market` 은 항상 `null`.
- `messages` 는 `datetime_kst` 오름차순.

### 3-3. `provenance.json` 쓰기

필드는 `schema.md` §2. 기존 케이스의 `assembly` 를 복사해 `window`(직전 거래일 날짜), `aliases` 를 바꿔 씀. `messages` 에는 메시지마다 `time_source: telegram_messages.posted_at`, `verified_by_human: false` 를 넣음.

### 3-4. 공시 접수 시각 확인

DART 공시 목록 API 는 **날짜(`rcept_dt`)만** 주고 시각을 안 줌. 접수 시각이 필요한 이유는 공시가 장중에 나왔는지 마감 후인지에 따라 인과 상한이 달라지기 때문임.

1. 대상 기간의 공시를 `dart_disclosures`(종목코드, `rcept_dt` 범위)에서 뽑아 `disclosures_pending_time_check` 에 넣음(`rcept_time_kst: null`, `in_case_json: false`).
2. KIND(`kind.krx.co.kr`)의 공시 상세 검색 목록을 날짜별로 받아 접수번호(`acptNo`)와 `YYYY-MM-DD HH:MM` 을 모음. 요청 사이에 0.3초 이상 간격을 두고, 더 이상 새 행이 없으면 멈춤.
3. DART `rcept_no` 와 KIND `acptNo` 를 맞춤. 두 값이 같거나, 9번째 자리만 `8` ↔ `0` 으로 다르면 같은 공시임. 맞는 행이 없으면 회사명과 제목 앞부분이 같은 행을 후보로 확인함.
4. 맞으면 `rcept_time_kst` 에 ISO 시각을, `time_source` 에 매칭 근거(예: `KIND 접수번호 8→0 대응, 회사·제목 일치`)를 적음.
5. **확인하지 못하면 `null` 로 둠.** 그 공시는 `case.json` 에도 gold 사건의 근거에도 넣지 않음(이번 세트에서는 5건이 `null`).

### 3-5. 누수 함정(선택)

함정 1(사후 누수)이 필요하면 `cutoff` 이후 메시지를 골라 `case.json` 에 넣고, `provenance.json` 의 `injected_after_cutoff` 에 `url`, `datetime_kst`, `why` 를 적음. 이 메시지는 `provenance.json` 의 `messages` 에는 넣지 않음. gold 의 근거로 쓰면 검증 스크립트가 오류로 처리함.

## 4. gold 뼈대와 시장 칸

### 4-1. 시장 칸은 사람이 쓰지 않음

`market_expectation` 은 파이프라인 코드가 같은 입력으로 계산한 값을 옮김. 직접 계산하지 않고 아래 코드로 구해서 `schema.md` §3-2 의 필드에 옮김.

```python
from app.services.stock_analysis.market_compare import MarketCompare
from app.services.stock_analysis.verify import (
    judge_layers, common_move, market_led, move_comparison, move_strength_cap)

async with httpx.AsyncClient(timeout=90) as client:
    payload, fields = await MarketCompare(client).apply(case_json_dict)
    m = payload["market"]          # peer_median_pct, excess_pct 등
    # judge_layers(payload), common_move(payload), market_led(payload),
    # move_comparison(payload), move_strength_cap(payload)
    # 코스피 값: MarketCompare 가 채우는 market_compare.kospi
```

옮기는 대응

| gold 칸 | 코드 값 |
|---|---|
| `stock_change_pct` | `payload["change_pct"]`(KRX 종목 등락률로 덮어쓴 값) |
| `peer_median_pct` | `market["peer_median_pct"]` |
| `excess_vs_peers_pp` | `market["excess_pct"]` |
| `judge_layers`, `common_move`, `market_led`, `move_strength_cap` | 같은 이름의 `verify` 함수 |
| `relative_direction` | `move_comparison(payload)`(`더`/`덜`/`반대로`/`비슷하게`) |
| `kospi_change_pct`, `excess_vs_basis_pp`, `kospi_basis`, `kospi_relation` | `market_compare.kospi` 의 같은 이름 칸 |

- `fields.get("market_compare_error")` 가 있거나 `market` 이 `null` 이면 KRX 응답을 못 받은 것임. 키와 날짜를 확인하고 다시 돌림. 값 없이 gold 를 쓰지 않음.
- 이 값은 **라이브 KRX 와 현재 `stock_meta` 유니버스**로 계산됨. 유니버스나 KRX 데이터가 바뀌면 값이 달라질 수 있으므로 평가 실행 전에 다시 계산해 gold 와 비교함.

### 4-2. 뼈대 만들기

기존 케이스의 `gold.json` 을 복사해 `case_id`, `trap_ids`, `market_expectation`, `time_expectation` 을 바꾸고 `status` 를 `skeleton` 으로 둠. 사건·판정·금지 주장 등은 비움. `time_expectation.cutoff` 는 `case.json` 과 같게, `display_as_of` 는 대상일 15:30 으로 맞춤.

## 5. gold 쓰기

`../rubric.md` §8 의 순서를 따름. 요약하면 다음과 같음.

1. `case.json` **만** 읽음. 모델 보고서와 `event_candidates.md` 같은 사전 분류 메모는 근거로 삼지 않음(메모는 후보일 뿐 입력에서 확인함).
2. 사건 목록(`events`)을 쓰고 사건마다 중요도·층·방향·최대 강도·근거 URL·`key_facts` 를 정함.
3. 층별 `expected_verdict`, `confidence_level` 을 정하고 서로 맞는지 확인함.
4. `forbidden_claims`(2~3개, 입력으로 반증되는 것), `unknowns`, `beginner_terms` 를 씀.
5. 망설인 곳은 `notes.md` 에 적음.
6. 마지막에 `status` 를 `skeleton` 이외의 값(`labeled`)으로 바꿈.

흔한 실수
- 공시 URL 을 `supporting_sources` 에 넣음 → `case.json` 에 없는 URL 이라 오류. 같은 사실을 담은 메시지 URL 로 바꿈.
- `key_facts` 가 일부 source 에만 있음 → 없는 source 는 `supporting_sources` 에서 뺌.
- 방향이 반대인 재료에 `likely_cause` 를 줌 → `coincident`.
- 판단하지 않는 층(절댓값 1 이하)에 사건을 담 → 그 층 사건을 빼고 `no_clear_cause`.
- 장 마감(15:30) 이후 공개된 재료에 높은 상한을 줌 → `coincident`.

## 6. 검증·잠금

1. `python3 evals/validate_gold.py <케이스 앞부분> --strict` 로 오류 0건, 경고 0건을 만듦.
2. 체크리스트(시각·출처·시장·판정·금지 주장)와 블라인드 재라벨링으로 검증하고 `verification` 을 채움.
3. 세트가 이미 잠금 상태이면 변경이 감지됨. 아래 7장을 봄.

## 7. 기존 케이스를 고칠 때

| 바꾸는 것 | 영향 | 해야 할 일 |
|---|---|---|
| `gold.json` 의 판정·사건·금지 주장 등 | 해시 변경 | `validate_gold.py` 로 검증 → 세트 버전을 올리고 `lock_set.py --write` → baseline 다시 돌림 |
| `gold.json` 의 `verification`, `status` | 해시 변경 없음 | 검증 기록만 채움 |
| `case.json` 메시지 추가·삭제(별칭 추가 포함) | 해시 변경, **gold 사건이 달라질 수 있음** | 사건·근거·판정을 다시 점검, `provenance.json` 의 `messages`·`aliases` 갱신, 위와 같이 버전 올림 |
| `provenance.json` 의 접수 시각 | 해시 변경 | 시각이 장 마감 전후를 바꾸면 해당 사건 상한을 다시 정함 |
| 시장 칸(KRX·유니버스 변경) | 해시 변경 | 4-1 코드로 다시 계산해 옮기고 `rubric` §2-1 규칙(`judge_layers`, `common_move`, `move_strength_cap`)에 따라 판정·사건이 바뀌는지 확인 |
| `rubric.md`·enum 값 | 모든 케이스에 영향 | `schema.md`, `validate_gold.py` 상수와 함께 고치고 10건 전부 다시 검증 |

변경을 확인하는 명령
```
python3 evals/validate_gold.py            # 규칙 위반 확인
python3 evals/lock_set.py --check         # 잠금 이후 바뀐 케이스·파일 확인
```

## 8. 체크리스트(케이스 1건 추가할 때)

- [ ] 대상일이 확정일이고 같은 종목·날짜 케이스가 없음
- [ ] 별칭(한글·영문·약칭)으로 메시지를 뽑았고 시황·유사 종목을 걸러냄
- [ ] `case.json`: `change_pct` 가 KRX 값, `market` 이 `null`, 메시지가 시각순
- [ ] `provenance.json`: 모든 메시지에 `time_source`, 공시 접수 시각 확인 또는 `null`, 섞은 메시지는 `injected_after_cutoff`
- [ ] 시장 칸을 `verify` 코드로 계산해 옮김(직접 계산하지 않음)
- [ ] gold 를 `case.json` 만 보고 씀, 망설인 곳은 `notes.md`
- [ ] `validate_gold.py` 오류 0건, 경고 0건
- [ ] 체크리스트·블라인드 재라벨링 후 `verification` 기록
- [ ] 세트 버전을 올리고 `lock_set.py --write`

## 9. 커밋

- 브랜치가 `feature/` 또는 `refactor/` 로 시작하는지 확인함.
- 커밋 메시지는 최근 커밋처럼 한국어 한 줄(예: `feat(ai): eval 케이스 c11 추가`). 본문과 attribution 줄은 쓰지 않음.
- 케이스 폴더(`ai/evals/cases/`)와 문서만 커밋함. 사전 분류 메모(`event_candidates.md`), 임시 계획 문서(`eval_plan*.md`), 입력 원본 폴더(`eval_input/`) 는 커밋하지 않음.
- 텔레그램 원문과 KRX 값이 들어 있으므로 외부로 push 하기 전에 팀의 데이터 사용 범위를 확인함.
