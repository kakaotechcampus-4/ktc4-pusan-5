"""자료 분류 — 자료(뉴스·PDF·메시지)를 사건으로 나누고, 사건마다 어느 종목에 해당하는지 판정한다.

설계는 docs/CLASSIFICATION_DB_DRAFT.md, 기준 데이터의 검증은 docs/INDUSTRY_REVIEW.md(회사–산업)와
docs/RELATION_REVIEW.md(회사–회사)다.

**DB 가 후보 종목을 정하고, LLM 은 그 후보마다 "이 사건이 이 종목에 해당하는가" 만 판정한다.**

    ① extract     사건 추출(LLM, 자료당 1회): scope·role·tense·근거 문장 번호·기사 속 표기
    ② link        표기 → 종목·산업·외부 기업: 별칭 사전 → 안 잡히면 LLM 이 코드 목록에서 고름
    ③ candidates  후보 모으기(코드): company / industry(stock_industries) / relation(company_relations)
    ④ judge       (사건, 후보)마다 DIRECT·INDIRECT_CONTEXT·NOT_APPLICABLE·UNKNOWN (LLM) + 저장 전 보정

    pipeline      ①~④ 를 잇는다. DB 를 쓰지 않는다
    basis         기준 JSON(app/data/classification_basis/) 읽기·검사
    llm           단계별 모델로 LLM 을 부른다
    evaluate      ① 추출을 실험 정답과 대조한다

저장·조회는 repositories/classification.py, 실행은 `python -m app.services.classification`(__main__.py).
DIRECT 판정은 source_card_stocks 에 tagged_by = classification 으로도 들어간다.

아직 정하지 않은 것 (CLASSIFICATION_DB_DRAFT 11절)
    - 사건 형식·role 최종안: 실험 E2·E3 결과로 정한다(전제 P10). 지금 프롬프트는 첫 안이다
    - 기준 JSON 은 사실 확인 전 초안이다(지금은 2026-11-03-draft). 확인이 끝나면 새 날짜 파일로 만든다
    - 긴 자료(PDF 본문 2만 자 초과)를 나눠 보내는 법. 지금은 건너뛴다(skipped)
    - 수집기 끝에 분류를 붙일지. 지금은 run 명령을 따로 돌린다
"""
