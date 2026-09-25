"""뉴스 발췌 방식 비교 실험. 운영 코드가 아니다 — 방식을 고르기 위한 측정 도구다.

(기사, 종목) 한 쌍마다 세 방식을 돌려 사람이 적은 정답과 비교한다.

    A  앞 3문장       지금 fetch.py 가 쓰는 방식. 같은 함수·같은 상한으로 자른다
    B  문장 번호 선택  모델은 번호만 고르고, 문장은 코드가 원문에서 그대로 꺼낸다
    C  생성 요약       모델이 새로 쓴다

## 순서

    uv run python -m app.services.news_link.compare prepare   # 기사를 열어 문장 번호를 붙인다
    (사람)  sheet.md 를 읽고 labels.csv 에 정답을 적는다
    uv run python -m app.services.news_link.compare run       # 세 방식을 돌린다 (B·C 는 LLM)
    (사람)  review.csv 에 B·C 를 채점한다
    uv run python -m app.services.news_link.compare score     # report.md 를 만든다

**정답을 다 적기 전에는 run 이 돌지 않는다.** 결과를 먼저 보면 정답을 결과에 맞춰
적게 되고, 그러면 측정이 아니라 확인이 된다.

## 작업 폴더

기본은 `ai/eval_data/news_compare/` 이고 git 에 올라가지 않는다(.gitignore).
기사 본문 전체가 들어 있어서다. 우리가 저장하는 것도 조심스러운데 공개 repo 에
올리면 재배포가 된다.
"""
