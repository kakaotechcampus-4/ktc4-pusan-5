## 폴더구조
```text
backend/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt  -> uv로 변경
├── .env.example
│
├── app/
│   ├── main.py                      # FastAPI 앱 진입점
│   │
│   ├── core/                        # 설정·공통 인프라
│   │   ├── config.py                 # 환경변수, API 키 로드
│   │   ├── database.py               # DB 세션, 커넥션
│   │   ├── cache.py                  # Redis 캐시 클라이언트
│   │   └── scheduler.py              # 배치 스케줄러 등록
│   │
│   ├── models/                      # DB 테이블 (SQLAlchemy)
│   │   ├── market.py                  # price_daily, sector_daily, macro_indicator, market_profile, market_event
│   │   ├── brief.py                    # brief, brief_block
│   │   ├── concept.py                  # concept, concept_edge, quiz_question
│   │   ├── user.py                     # user_concept_state, user_path_edge
│   │   └── registration.py             # pending_term, concept_registration_queue
│   │
│   ├── schemas/                     # Pydantic (요청/응답 검증)
│   │   ├── market.py
│   │   ├── brief.py
│   │   └── concept.py
│   │
│   ├── services/                     # 소스별 외부 API 클라이언트
│   │   ├── krx_client.py
│   │   ├── ecos_client.py
│   │   ├── dart_client.py
│   │   ├── kis_client.py
│   │   ├── fred_client.py
│   │   ├── news_client.py            # NAVER + KIS 뉴스
│   │   └── telegram_client.py
│   │
│   ├── collectors/                  # 소스 데이터 → 정규화 → DB 저장 (폴링 배치)
│   │   ├── price_collector.py
│   │   ├── sector_collector.py 
│   │   ├── macro_collector.py
│   │   └── news_collector.py
│   │
│   ├── orchestrator/                 # 오케스트레이션 + 시나리오 판정
│   │   ├── scenario.py                # classify_market() 등 규칙 함수
│   │   ├── config/
│   │   │   └── scenario.yaml
│   │   └── pipeline.py                 # generate_market_insight() 등 파이프라인 조립
│   │
│   ├── skills/                       # LLM 호출 (블록별 생성, has_issue 판정 등)
│   │   ├── issue_detector.py           # detect_issue (has_issue 신호)
│   │   ├── block_writer.py             # write_block()
│   │   └── prompts/                    # 프롬프트 템플릿 분리 보관
│   │       ├── issue_detection.txt
│   │       └── block_templates/
│   │
│   ├── routers/                      # API 엔드포인트
│   │   ├── market.py                   # GET /reports/market 등
│   │   ├── concepts.py
│   │   ├── chatbot.py
│   │
│   └── repositories/                 # DB 접근 로직 (모델과 서비스 사이 계층)
│       ├── market_repo.py
│       └── brief_repo.py
│
└── tests/                 # 테스트케이스
    ├── test_scenario_classification.py   
    └── test_collectors/
```