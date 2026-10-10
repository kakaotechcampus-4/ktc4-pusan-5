# 데이터 수집 DB 스키마

- 기준 브랜치: `feature/data-collection` (`aace1f5` + 0024 작업분), 비교 대상: `develop`
- 작성일: 2026-10-08
- 범위: 이 브랜치에서 새로 만들거나 바꾼 표와, 그 표가 FK 로 잇는 표

설계 근거의 원본은 각 모델 파일의 주석(`ai/app/models/*.py`)이다. 이 문서는 그걸 한곳에
모아 본 것이라, 둘이 어긋나면 모델 주석이 맞다.

---

## 1. 한눈에 보기

### 1-1. 이번 브랜치에서 바뀐 것

| 구분 | 표 | 무엇이 | 리비전 |
| --- | --- | --- | --- |
| 넘겨받음 + 칼럼 추가 | `news` | backend 가 만든 표를 ai 가 관리. 중복 판정·본문 상태·삭제 기록 칼럼 7개 추가, `published_at` NULL 허용 | `0020` |
| 신규 | `telegram_messages` | 텔레그램 메시지 원문 | `0021` |
| 신규 | `telegram_message_links` | 메시지에서 발견한 링크·첨부 → 뉴스/PDF 연결 | `0021` |
| 넘겨받음 + 칼럼 추가 | `source_card` | backend 가 만든 표를 ai 가 관리. 원문 표를 가리키는 FK 3개 + 제약 추가 | `0022` |
| 칼럼 추가 | `analyst_reports` | 보관 정책 삭제 기록 칼럼 2개 추가, `body_status` 에 `purged` 값 추가 | `0023` |
| 칼럼 추가 | `source_card` | 공개 시각 `available_at` 추가. `event_date` 를 원문 카드에도 채움 | `0024` |
| 신규 | `source_card_stocks` | 자료 ↔ 종목 연결 (자료 하나가 여러 종목) | `0024` |
| 칼럼 추가 | `stock_move_analysis_factor_sources` | 보고서 출처를 공통 자료 ID 로 잇는 `source_card_id` | `0024` |
| 변경 없음(참조만) | `channel` | backend 소유. FK 대상으로만 쓰고, 처음 보는 채널 행을 등록만 한다 | — |
| 변경 없음 | `stock_move_analyses`, `_factors`, `_reviews` | 이전 리비전(`0019`) 그대로 | — |

backend 쪽 변경:

- `backend/app/models/news.py`, `repositories/news.py`, `collectors/news.py` 와 테스트 삭제 → ai 로 이관
- `backend/migrations/env.py` 에 `AI_MANAGED_TABLES = {"news", "source_card"}` 추가 → backend autogenerate 가 이 두 표를 비교하지 않는다
- `backend/app/models/source_card.py` 는 남김(`report_citation` 이 FK 로 가리켜서). 주석만 추가
- `NAVER_CLIENT_ID`·`NAVER_CLIENT_SECRET` 설정을 backend 에서 ai 로 이동

### 1-2. 표 소유권

같은 PostgreSQL 하나를 backend 와 ai 가 같이 쓰고, 마이그레이션 이력은 따로 둔다.

| | backend | ai |
| --- | --- | --- |
| 이력 표 | `alembic_version` | `alembic_version_ai` |
| 관리하는 표 | `channel`, `concepts`, `users`, `report`, `report_block`, `report_citation`, 주식 시세 표들 | `analyst_reports`, `news`, `source_card`, `source_card_stocks`, `telegram_messages`, `telegram_message_links`, `stock_move_analyses` 외 3개 |
| 설정 위치 | `backend/migrations/env.py` 의 `AI_MANAGED_TABLES` (비교 제외 목록) | `ai/alembic/env.py` 의 `MANAGED_TABLES` / `EXTERNAL_TABLES` |

`news`·`source_card` 는 **표 생성은 여전히 backend 첫 리비전(`99dbfe02fd98`)** 이 하고, 그 이후
구조 변경만 ai 가 한다. 한 표를 양쪽이 비교하면 서로 상대가 더한 칼럼을 지우라는
마이그레이션을 만들기 때문에 비교 주체를 한쪽으로 몰았다.

### 1-3. 관계도

```
                         ┌──────────────┐
                         │   channel    │  (backend 소유)
                         └──────┬───────┘
                 channel_id     │      channel_id
          ┌─────────────────────┼──────────────────────┐
          ▼                     │                      ▼
┌───────────────────┐           │            ┌──────────────────┐
│ telegram_messages │◄──────────┼────────────│   source_card    │  공통 자료 ID
└────────┬──────────┘ telegram_ │            │  (card_type 별   │
         │ message_id  message_id            │   FK 하나만 채움) │
         │ (CASCADE)            │            └──┬───────────┬───┘
         ▼                      │      news_id  │           │ analyst_report_id
┌────────────────────────┐      │               ▼           ▼
│ telegram_message_links │──────┼────────► ┌────────┐ ┌─────────────────┐
│  kind = url | attachment│ news_id         │  news  │ │ analyst_reports │
└────────────────────────┘──────┴────────► └────────┘ └─────────────────┘
                          analyst_report_id

source_card ◄── report_citation.source_card_id                (backend 의 브리핑 인용)
source_card ◄── stock_move_analysis_factor_sources.source_card_id   (ai 보고서의 출처)
source_card ◄── source_card_stocks.source_card_id             (자료 ↔ 종목, CASCADE)
```

- 원문은 종류별 표(`news` / `analyst_reports` / `telegram_messages`)에 한 번만 저장한다.
- `source_card` 는 원문을 복제하지 않고 FK 로 가리키는 **공통 자료 ID** 다. 브리핑이 인용할 때는 이 ID 를 쓴다.
- 어떤 메시지에서 어떤 주소로 기사·PDF 를 발견했는지는 `telegram_message_links` 에 남는다.
- 종목 브리핑은 `source_card_stocks`(종목)와 `source_card.available_at`(공개 시각)으로 "이 종목의 자료 중 기준 시각 이전 것" 을 찾는다.

---

## 2. 표별 칼럼

표기: **🆕** = 이번 브랜치에서 추가, **✏️** = 이번 브랜치에서 변경, 표시 없음 = 기존 그대로.
타입은 PostgreSQL 기준. `NN` = NOT NULL.

### 2-1. `news` — 뉴스 기사 원문 (`0020`)

한 행 = 기사 한 건(정규화한 주소 기준). 두 경로로 들어온다.

| source | 경로 | 발행 시각 | 본문 추출 |
| --- | --- | --- | --- |
| `naver` | 네이버 뉴스 검색 API | API 가 준다 | trafilatura, 3,000자에서 자름 |
| `telegram` | 텔레그램 메시지의 링크를 따라가 연 기사 | 모른다 → NULL | news_link(bs4), 전문 |

| 칼럼 | 타입 | NULL | 설명 | 변경 |
| --- | --- | --- | --- | --- |
| `id` | integer | NN | PK | |
| `url` | text | NN, UNIQUE | 처음 들어온 원문 주소. 네이버는 originallink, 텔레그램은 리다이렉트 끝 주소 | |
| `canonical_url` | text | NULL, UNIQUE | 중복 판정용 정규화 주소(`services/news/url.py`). 같은 기사가 두 경로로 와도 한 행 | 🆕 |
| `title` | text | NN | 못 읽었으면 빈 문자열. 다음 수집에서 채운다 | |
| `publisher` | varchar(100) | NN | 원 발행처. 지금은 원문 도메인 | |
| `source` | varchar(20) | NN | 처음 들어온 경로 `naver` \| `telegram` | |
| `published_at` | timestamptz | **NULL** | 발행 시각. 모르면 NULL. 수집 시각으로 대신 채우지 않는다 | ✏️ NOT NULL → NULL |
| `summary` | text | NN | 네이버가 준 요약. 본문 아님 | |
| `cleaned_text` | text | NULL | 정제한 본문 전체. 보관 정책으로 지우면 NULL | |
| `body_status` | varchar(16) | NN, CHECK | `ok` \| `failed` \| `purged` | 🆕 |
| `body_error` | text | NULL | 실패 사유(`http_404`, `extract_empty`, `no_body` …). 이관 전 실패 행은 `unrecorded` | 🆕 |
| `body_fetched_at` | timestamptz | NULL | 본문을 받으러 마지막으로 연 시각. 기준 시각 이후 본문을 거를 때 쓴다 | 🆕 |
| `body_extractor` | varchar(32) | NULL | `trafilatura` \| `news_link` | 🆕 |
| `purged_at` | timestamptz | NULL | 보관 정책으로 본문을 지운 시각 | 🆕 |
| `purge_reason` | text | NULL | 지운 사유(어느 정책인지) | 🆕 |
| `collected_at` | timestamptz | NN, 기본 `now()` | 행을 넣은 시각 | |

제약·인덱스

- `uq_news_canonical_url` UNIQUE(`canonical_url`) 🆕 — NULL 은 여러 개 허용(이관 전 행)
- `ck_news_body_status` CHECK(`body_status IN ('ok','failed','purged')`) 🆕
- `ix_news_published_at` (기존)

규칙

- **본문은 한 번 확보하면 덮어쓰지 않는다.** 브리핑이 인용한 문장과 원문이 어긋나거나 기준 시각 이후 수정이 섞이는 걸 막는다. `failed` 인 본문만 다음 수집에서 채운다.
- `purged` 행은 다시 수집해도 본문을 되살리지 않는다.

기존 행 이관(0020 실행 시 자동)

| 기존 상태 | `body_status` | `body_error` | `body_extractor` | `body_fetched_at` |
| --- | --- | --- | --- | --- |
| `cleaned_text` 있음 | `ok` | NULL | `trafilatura` | `collected_at` |
| NULL 또는 빈 문자열 | `failed` | `unrecorded` | NULL | `collected_at` |

`canonical_url` 은 리비전이 아니라 `python -m app.collectors.sources register` 가 채운다
(정규화 규칙이 앱 코드라서). 정규화 주소가 겹치는 기존 중복 행은 합치지 않고 비워 둔 채 목록만 보여준다.

### 2-2. `telegram_messages` — 텔레그램 메시지 원문 (`0021`, 🆕 신규)

한 행 = 채널의 메시지 한 건. 두 수집기가 같은 표에 넣는다.

| collected_via | 수집기 | 방식 |
| --- | --- | --- |
| `web` | `collectors/news_channels.py` | 로그인 없이 `t.me/s/` 공개 미리보기 |
| `telethon` | `collectors/telegram.py` | 로그인 계정으로 PDF 첨부 메시지 |

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `id` | bigint | NN | PK |
| `channel_id` | integer | NN | FK → `channel.id` |
| `msg_id` | bigint | NN | 채널 안 메시지 번호 |
| `url` | text | NN | `https://t.me/<채널>/<번호>`. 브리핑의 출처 주소 |
| `posted_at` | timestamptz | NULL | 게시 시각. 못 읽으면 NULL(수집 시각으로 채우지 않음) |
| `author` | varchar(200) | NULL | 채널 안 서명 |
| `text` | text | NULL | **처음 수집한 본문.** 빈 문자열 = 첨부만 있는 메시지, NULL = 보관 정책으로 지움 |
| `attachment_name` | text | NULL | 첨부 파일 이름 |
| `forwarded_from` | text | NULL | 다른 채널 글을 전달했으면 원래 채널 이름 |
| `forwarded_from_url` | text | NULL | 전달한 원글 주소 |
| `hidden_links` | jsonb | NN, 기본 `[]` | 보이는 글자와 실제 주소가 달라 쓰지 않은 링크 |
| `views` | varchar(32) | NULL | 마지막으로 본 조회수. `"1.2K"` 그대로 |
| `edited` | boolean | NN, 기본 false | 채널에 '수정됨' 표시가 있었는지 |
| `edit_detected_at` | timestamptz | NULL | 재수집 때 본문이 달라진 걸 처음 발견한 시각. 본문은 바꾸지 않는다 |
| `purged_at` | timestamptz | NULL | 보관 정책으로 본문을 지운 시각 |
| `purge_reason` | text | NULL | 지운 사유 |
| `collected_via` | varchar(16) | NN, CHECK | `web` \| `telethon` |
| `collected_at` | timestamptz | NN, 기본 `now()` | 처음 수집 시각 |
| `last_seen_at` | timestamptz | NN, 기본 `now()` | 마지막으로 다시 본 시각 |

제약·인덱스

- `uq_telegram_message_channel_msg` UNIQUE(`channel_id`, `msg_id`) — 메시지 번호는 채널 안에서만 유일
- `ck_telegram_message_collected_via` CHECK(`collected_via IN ('web','telethon')`)
- `ix_telegram_messages_posted_at` (`posted_at`)

규칙

- 본문(`text`)은 처음 저장한 값을 유지한다. 나중에 고쳐진 글은 `edit_detected_at` 만 남긴다.
- 운영자가 쓴 글과 남의 자료를 구분한다. 전달 글은 `forwarded_from*`, 외부 기사·PDF 는 `telegram_message_links` 로 별도 행에 잇는다.

### 2-3. `telegram_message_links` — 메시지 안의 링크·첨부 (`0021`, 🆕 신규)

한 행 = 메시지에서 발견한 링크 하나 또는 첨부 하나. 같은 기사가 여러 메시지에 올라와도
`news` 는 한 행이고 이 표에는 메시지 수만큼 생긴다.

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `id` | bigint | NN | PK |
| `message_id` | bigint | NN | FK → `telegram_messages.id` (ON DELETE CASCADE) |
| `kind` | varchar(16) | NN, CHECK | `url` \| `attachment` |
| `position` | integer | NN | 메시지 안 순서(1부터). 첨부는 1 |
| `discovered_url` | text | NULL | 메시지에 적힌 주소 그대로(대개 단축 URL). `url` 이면 필수, `attachment` 면 NULL |
| `final_url` | text | NULL | 리다이렉트를 따라 도착한 주소 |
| `status` | varchar(16) | NN | 아래 상태값 표 참고 |
| `error` | text | NULL | 실패 상세 |
| `http_status` | integer | NULL | 응답 코드 |
| `fetched_at` | timestamptz | NULL | 링크를 연 시각 |
| `news_id` | integer | NULL | FK → `news.id` |
| `analyst_report_id` | bigint | NULL | FK → `analyst_reports.id` |
| `created_at` | timestamptz | NN, 기본 `now()` | |

제약·인덱스

- `uq_telegram_message_link_position` UNIQUE(`message_id`, `kind`, `position`)
- `ck_telegram_message_link_kind` CHECK(`kind IN ('url','attachment')`)
- `ck_telegram_message_link_url` CHECK(`(kind = 'url') = (discovered_url IS NOT NULL)`)
- `ck_telegram_message_link_target` CHECK(`num_nonnulls(news_id, analyst_report_id) <= 1`) — 발견 하나는 기사 하나 또는 PDF 하나로만 이어진다
- `ix_telegram_message_links_news_id`, `ix_telegram_message_links_analyst_report_id`

`status` 값

| kind | 상황 | status |
| --- | --- | --- |
| `url` | 열었음 | `ok` · `no_body` · `pdf` · `not_html` · `too_large` · `http_error` · `blocked` · `error` |
| `url` | 안 열었음 | `stale`(게시 24시간 경과·게시 시각 모름) · `over_limit`(메시지당 상한) · `not_fetchable`(티커 문자열 등) · `not_opened`(`--no-links`) · `out_of_scope`(수집 범위 밖·수집량 상한) |
| `attachment` | | `saved`(이 메시지의 PDF 를 저장) · `duplicate`(같은 네이버 PDF 에 연결) · `excluded`(수집 대상 아님) · `not_saved`(저장 행도 같은 PDF 도 없음) |

### 2-4. `source_card` — 공통 자료 ID (`0022`)

backend 가 "모든 근거 카드가 들어오는 단일 테이블" 로 만든 표를, ai 가 **원문을 가리키는 공통 목록** 으로 쓰도록 확장했다.
기존 칼럼은 그대로 두고 FK 3개와 제약만 더했다.

| card_type | 가리키는 원문 | 채우는 FK |
| --- | --- | --- |
| `news` | `news` | `news_id` |
| `pdf` | `analyst_reports` | `analyst_report_id` |
| `message` | `telegram_messages` | `telegram_message_id` |
| 그 밖(시세·공시 등 backend 용) | — | 셋 다 NULL |

| 칼럼 | 타입 | NULL | 설명 | 변경 |
| --- | --- | --- | --- | --- |
| `id` | bigint | NN | PK. **공통 자료 ID** | |
| `card_type` | varchar(50) | NN | 자료 형태 | |
| `stock_code` | varchar(12) | NULL | backend 용 종목코드 칸. 종목을 하나만 담을 수 있어 원문 카드는 비우고 `source_card_stocks` 를 쓴다 | |
| `event_date` | date | NULL | 원문 카드는 `available_at` 의 날짜(KST). 시각을 모르는 네이버 리포트는 작성일 | ✏️ 원문 카드에도 채움 |
| `channel_id` | integer | NULL | FK → `channel.id`. 텔레그램 메시지·텔레그램 첨부 PDF 만 | |
| `source_name` | varchar(100) | NULL | 원 발행처. news=`publisher`, pdf=`broker`, message=`forwarded_from` 또는 채널명 | |
| `source_url` | varchar(500) | NULL | backend 직접 입력 카드용. 원문 카드는 비움 | |
| `raw_text` | text | NULL | 〃 | |
| `cleaned_text` | text | NULL | 〃 | |
| `tags` | jsonb | NN | DB 기본값 없음 → 넣을 때 `[]` | |
| `payload` | jsonb | NN | DB 기본값 없음 → 넣을 때 `{}` | |
| `confidence` | float | NULL | 신뢰도(미사용) | |
| `collected_at` | timestamptz | NULL | 원문 표의 `collected_at` 복사 | |
| `created_at` | timestamptz | NN | DB 기본값 없음 → 넣을 때 `now()` | |
| `news_id` | integer | NULL, UNIQUE | FK → `news.id` | 🆕 |
| `analyst_report_id` | bigint | NULL, UNIQUE | FK → `analyst_reports.id` | 🆕 |
| `telegram_message_id` | bigint | NULL, UNIQUE | FK → `telegram_messages.id` | 🆕 |
| `available_at` | timestamptz | NULL | 공개돼 있었다고 확인된 가장 이른 시각. 아래 표 참고 | 🆕 (0024) |

제약·인덱스

- `fk_source_card_news_id`, `fk_source_card_analyst_report_id`, `fk_source_card_telegram_message_id` 🆕
- `uq_source_card_news_id`, `uq_source_card_analyst_report_id`, `uq_source_card_telegram_message_id` 🆕 — 원문 한 행에 카드 하나. 등록을 여러 번 돌려도 늘지 않는다
- `ck_source_card_raw_source` 🆕
  ```sql
  (card_type = 'news')    = (news_id IS NOT NULL)
  AND (card_type = 'pdf')     = (analyst_report_id IS NOT NULL)
  AND (card_type = 'message') = (telegram_message_id IS NOT NULL)
  ```
- `ix_source_card_available_at` (`available_at`) 🆕 (0024)
- 기존: `idx_source_card_type`, `idx_source_card_stock_date`, `idx_source_card_tags_gin`, `idx_source_card_payload_gin`

`available_at` 계산 (등록할 때마다 원문에서 다시 계산한다)

| card_type | 값 |
| --- | --- |
| `news` | `news.published_at` 과, 이 기사를 건 텔레그램 메시지들의 `posted_at` 중 가장 이른 것 |
| `pdf` | 이 PDF 를 올린 텔레그램 메시지의 `posted_at`. 네이버 리포트는 작성일만 있어 NULL |
| `message` | `telegram_messages.posted_at` |

모르면 NULL 이고 수집 시각으로 대신 채우지 않는다. 더 이른 메시지를 나중에 수집하면 값이 앞당겨진다.
본문을 언제 받았는지(기준 시각 이후 수정이 섞였는지)는 원문 표의 `body_fetched_at` 이 따로 말한다.

카드는 수집기가 묶음마다 만들고(`register_missing_sources`), 빠진 것은
`python -m app.collectors.sources register` 로 한 번에 복구한다. 원문은 카드의 FK 를 따라가
읽는다(`repositories/source_card.py` 의 `get_sources`).

자료 형태·발행처·수집 경로는 서로 다른 값이다. 예를 들어 증권사 PDF 를 텔레그램에서 받았다면
`card_type = pdf`, `source_name = 증권사`, 경로는 `analyst_reports.source = telegram` 이다.

### 2-4-1. `source_card_stocks` — 자료 ↔ 종목 (`0024`, 🆕 신규)

한 행 = (공통 자료 ID, 종목코드). 기사 하나가 여러 종목을 다룰 수 있어 따로 표를 뒀다.

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `id` | bigint | NN | PK |
| `source_card_id` | bigint | NN | FK → `source_card.id` (ON DELETE CASCADE) |
| `stock_code` | varchar(6) | NN | 종목코드. backend `stock` 표를 FK 로 가리키지 않는다(마스터에 없는 종목이어도 저장이 막히지 않게) |
| `tagged_by` | varchar(32) | NN | 누가 이 연결을 정했나. 지금은 `report_item_code`(종목분석 리포트의 `item_code`)만 |
| `created_at` | timestamptz | NN, 기본 `now()` | |

제약·인덱스: `uq_source_card_stock` UNIQUE(`source_card_id`, `stock_code`), `ix_source_card_stocks_stock_code`

**아직 채워지지 않는 것:** 뉴스·메시지가 어느 종목 이야기인지 판단하는 코드(필터·태깅 단계)는 실험 레포에 있고
이 브랜치에 없다. 그게 들어오면 그 방식의 `tagged_by` 값으로 행을 더한다.

조회: `repositories/source_card.py` 의 `stock_card_ids(session, "005930", until=기준시각, since=...)` 가
공통 ID 를 오래된 순서로 준다. 공개 시각을 모르는 자료는 기준 시각의 **전날까지** 날짜인 것만 넣는다.

### 2-5. `analyst_reports` — 증권사 리포트 (`0023`)

한 행 = 리포트 한 편. 표 구조는 기존(`0001`·`0018`) 그대로이고 이번엔 삭제 기록만 더했다.

| 칼럼 | 타입 | NULL | 설명 | 변경 |
| --- | --- | --- | --- | --- |
| `id` | bigint | NN | PK | |
| `source` | varchar(16) | NN | `naver` \| `telegram` | |
| `source_id` | varchar(64) | NN | 네이버 researchId, 텔레그램 메시지 번호 | |
| `source_category` | varchar(32) | NN | 출처가 준 원본 구분. 네이버 API 카테고리 / 텔레그램 채널명 | |
| `category` | varchar(16) | NN | 우리 분류 `company` \| `industry` \| `economy` \| `market` | |
| `item_code` | varchar(6) | NULL | 종목코드(종목분석만) | |
| `item_name` | varchar(64) | NULL | 종목명 | |
| `broker` | varchar(64) | NULL | 발행기관. 모르면 NULL(채널명으로 채우지 않음) | |
| `title` | text | NN | 제목 | |
| `write_date` | date | NN | 작성일 | |
| `read_count` | integer | NULL | 조회수 | |
| `opinion` | varchar(16) | NULL | 투자의견 | |
| `goal_price` | bigint | NULL | 목표주가 | |
| `price_at_write` | bigint | NULL | 작성 시점 주가 | |
| `upside_pct` | numeric(8,2) | NULL | 상승여력 | |
| `sector_opinion` | varchar(16) | NULL | 산업분석 의견 | |
| `top_picks` | jsonb | NULL | 산업분석 추천 종목 | |
| `summary_html` / `summary_text` / `summary_chars` | text / text / int | NULL | 네이버 요약 | |
| `end_url` / `attach_url` | text | NULL | 원문 페이지·PDF 주소 | |
| `pdf_sha256` / `pdf_bytes` / `pdf_pages` | varchar(64) / bigint / int | NULL | PDF 식별·크기 | |
| `body_text` / `body_chars` | text / int | NULL | PDF 에서 뽑은 본문 | |
| `body_status` | varchar(16) | NN | `pending` \| `ok` \| `empty` \| `unusable` \| `failed` \| `skipped` \| **`purged`** | ✏️ `purged` 값 추가 |
| `body_extractor` / `body_error` / `body_fetched_at` | | NULL | 본문 추출 정보 | |
| `purged_at` | timestamptz | NULL | 보관 정책으로 본문을 지운 시각 | 🆕 |
| `purge_reason` | text | NULL | 지운 사유 | 🆕 |
| `collected_at` / `updated_at` | timestamptz | NN, 기본 `now()` | | |

`body_status` 는 CHECK 제약이 없는 문자열이라 `purged` 추가에 DDL 변경이 필요 없었다.
자연키는 `uq_analyst_report_source_id` UNIQUE(`source`, `source_category`, `source_id`) 그대로.

### 2-6. `channel` — 텔레그램 채널 (backend 소유, 변경 없음)

ai 는 FK 대상과 신규 채널 행 등록에만 쓴다. 이미 있는 행의 등급·검수 정보는 건드리지 않는다.

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `id` | integer | NN | PK |
| `telegram_handle` | varchar(100) | NN, UNIQUE | `t.me/<handle>`. `analyst_reports.source_category` 의 채널명과 같은 값 |
| `name` | varchar(200) | NN | 채널 표시 이름 |
| `is_public` | boolean | NN | |
| `grade` | varchar(1) | NULL | A~D. 사람이 검수하기 전엔 NULL |
| `reviewed_by` / `reviewed_at` | varchar(50) / timestamptz | NULL | 검수 정보 |
| `category` | varchar(50) | NULL | |
| `created_at` | timestamptz | NN | DB 기본값 없음 → 넣을 때 값을 준다 |

### 2-7. `stock_move_analyses` 외 3개

출처 표에 `source_card_id` 하나를 더했고(0024) 나머지는 그대로다. 상세는 `app/models/stock_move_analysis.py`.

| 표 | 한 행 | 주요 칼럼 |
| --- | --- | --- |
| `stock_move_analyses` | LLM 이 만든 종목 변동 요인 보고서 한 회차(INSERT only) | `ticker`, `target_date`, `as_of`, `change_pct`, `verdict`, `summary_*` 4칸, `terms`/`background`/`not_found`(jsonb), `raw_json`, `source_file_sha256`(UNIQUE), `parse_status`, `verify_status`, `generated_at`, `loaded_at` |
| `stock_move_analysis_factors` | 보고서가 든 원인 하나 | `analysis_id`(FK CASCADE), `order_index`, `claim`, `detail`, `stance`, `direction_match`, `size_fit`, `unconfirmed` |
| `stock_move_analysis_factor_sources` | 원인 하나가 기댄 출처 하나 | `factor_id`(FK CASCADE), `order_index`, `source`, `channel`, `url`, `datetime_kst`, `quote`, `match`, `is_market_recap`, 🆕 `source_card_id`(FK → `source_card.id`, NULL 허용) |
| `stock_move_analysis_reviews` | 사람의 검수 판정(아직 미사용) | `analysis_id`(FK CASCADE), `decision`, `reviewer`, `note`, `created_at` |

`source_card_id` 는 적재할 때 출처 `url` 로 저장된 원문을 찾아 채운다(텔레그램 메시지는 `telegram_messages.url`
글자 그대로, 기사는 정규화 주소). 못 찾으면 NULL 이고 `url` 은 남는다. 원문을 나중에 수집했으면
`python -m app.collectors.sources register` 가 다시 찾아 채운다.

backend 의 `report`/`report_block`/`report_citation` 과 이 표들 중 어느 쪽을 화면에 쓸지는 아직 정하지 않았다.
어느 쪽이든 출처는 공통 자료 ID(`source_card.id`)로 가리킨다.

---

## 3. 공통 규칙

### 3-1. 본문 상태와 보관 정책 삭제

세 원문 표 모두 "본문만 지우고 행은 남긴다" 는 같은 방식이다. 행과 id 가 남아야 공통 자료 ID 와
`report_citation` 인용이 깨지지 않는다.

| 표 | 지우는 칼럼 | 삭제 표시 | 남기는 것 |
| --- | --- | --- | --- |
| `news` | `cleaned_text` → NULL | `body_status = 'purged'`, `purged_at`, `purge_reason` | 제목·주소·발행처·시각·요약 |
| `analyst_reports` | `body_text` → NULL | `body_status = 'purged'`, `purged_at`, `purge_reason` | 식별키·PDF 해시·요약 |
| `telegram_messages` | `text` → NULL | `purged_at`, `purge_reason` | 주소·게시 시각·발견 경로 |

- 실행은 자동이 아니라 사람이 명령으로 한다: `python -m app.collectors.sources purge` (`repositories/retention.py`)
- 보관 기간·대상은 **아직 정하지 않았다.** 지금은 실행 수단만 있다.
- 지운 행은 다시 수집해도 본문을 되살리지 않는다.
- `news.summary`, `analyst_reports.summary_text` 같은 사본은 지우지 않는다. 범위는 분류·생성 담당과 맞춘 뒤 정한다.

### 3-2. 시각 칼럼

모든 시각은 `timestamptz`. 모르는 시각은 NULL 로 두고 **다른 시각으로 대신 채우지 않는다**
(`news.published_at`, `telegram_messages.posted_at`). 기준 시각 이후 정보가 브리핑에 섞이는 걸 막기 위해서다.

### 3-3. 동시 수집

같은 출처의 수집기가 동시에 돌면 수집량 상한을 넘을 수 있어서, 출처별 PostgreSQL advisory lock
(`pg_advisory_xact_lock(hashtextextended('collection:<출처>', 0))`)으로 직렬화한다
(`repositories/scope.py`). 표 구조와는 무관한 운영 규칙이다.

---

## 4. 마이그레이션

### 4-1. ai 리비전 순서

```
0001  analyst_reports 생성                         (기존)
0018  analyst_reports.source_category, 자연키 변경  (기존)
0019  stock_move_analysis 4개 표                    (기존)
0020  news 인수 + 칼럼 추가                          🆕
0021  telegram_messages, telegram_message_links     🆕
0022  source_card FK 3개 + 제약                      🆕
0023  analyst_reports.purged_at / purge_reason      🆕
0024  source_card.available_at, source_card_stocks,
      factor_sources.source_card_id                 🆕
```

### 4-2. 설치 순서

**backend 를 먼저 올린다.** `0020`~`0022` 는 backend 가 만든 `news`·`channel`·`source_card` 를
고치므로 그 표가 없으면 안내 문구와 함께 중단한다.

```bash
cd backend && uv run alembic upgrade head
cd ../ai && uv run alembic upgrade head
uv run alembic check
uv run python -m app.collectors.sources register   # 기존 데이터의 canonical_url·카드·공개 시각·종목·보고서 출처 채우기
```

### 4-3. 실행이 멈추는 조건

데이터를 지우거나 값을 지어내지 않기 위해, 아래 경우엔 아무것도 바꾸지 않고 중단한다.

| 리비전 | upgrade 중단 | downgrade 중단 |
| --- | --- | --- |
| `0020` | `news` 표가 없음 | `published_at` 이 NULL 인 행이 있음 / `purged` 행이 있음 |
| `0021` | `channel` 표가 없음 | — |
| `0022` | `source_card` 가 없음 / 원문 FK 없는 `news`·`pdf`·`message` 카드가 이미 있음 | 원문을 가리키는 카드가 있음 |
| `0023` | — | 본문을 지운 PDF 가 있음 |
| `0024` | — | 막지 않는다. 지금 들어가는 값은 모두 원문에서 다시 계산할 수 있다(`sources register`) |
