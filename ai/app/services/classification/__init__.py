"""자료 분류 — 사건 추출 결과를 종목·산업에 연결하고 종목별로 조립한다.

설계는 docs/CLASSIFICATION_DB_DRAFT.md(표 구조·조립 규칙)와 docs/INDUSTRY_MAP.md(연결 기준)다.

    원문 → 문장 번호(splitter) → LLM 사건 추출 → 응답 검사(events)
         → 표기 → 종목·산업(link) → 종목별 조립(assemble)

**LLM 은 사건의 scope 와 기사 속 표기만 낸다. 어느 종목에 붙일지는 기준(basis)이 정한다.**
산업–종목 연결은 사람이 근거를 확인한 것(`status = confirmed`)만 쓴다.

아직 없는 것 — 정해지지 않아서 일부러 비워 뒀다.
    - LLM 호출과 프롬프트: 사건 형식은 실험 E2·E3 결과로 정한다(전제 P10)
    - DB 표와 마이그레이션: E3 채택 뒤 만든다(DRAFT 11절 11번)
    - 운영용 기준 JSON: INDUSTRY_MAP 3절 연결을 검토한 뒤 만든다. 지금은 테스트용 mock 만 있다
"""
