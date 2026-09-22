"""정제 규칙이 지켜야 하는 성질을 잡는다. 네트워크도 DB 도 쓰지 않는다.

가장 중요한 건 **남는 글자가 원문 그대로**라는 것이다. 나중에 모델의 인용을 원문과
문자열로 대조하려면 그 성질이 살아 있어야 한다. 규칙을 고치다 이게 깨지면
환각 검증이 조용히 죽으므로, 테스트가 먼저 깨져야 한다.
"""

from app.services.news_link.clean import clean_paragraphs


def test_남는_문장은_원문_그대로다() -> None:
    paras = [
        "(서울=연합뉴스) 이도흔 기자 = 삼성전자가 차세대 메모리를 공개했다.",
        "회사는 내년 양산을 목표로 한다고 밝혔다.",
    ]
    kept, _log = clean_paragraphs(paras)
    joined = "\n".join(kept)
    assert "삼성전자가 차세대 메모리를 공개했다." in paras[0]
    assert joined.startswith("삼성전자가 차세대 메모리를 공개했다.")
    for sentence in kept:
        assert any(sentence in original for original in paras), "문장을 다시 쓰면 안 된다"


def test_바이라인은_앞머리만_뗀다() -> None:
    """문단을 통째로 버리면 리드 문장이 같이 날아간다. 연합뉴스가 그 형태다."""
    kept, log = clean_paragraphs(["(서울=연합뉴스) 이도흔 기자 = 본문이 여기서 시작된다."])
    assert kept == ["본문이 여기서 시작된다."]
    assert log[0][0] == "byline_paren"


def test_저작권_문단은_버린다() -> None:
    kept, _log = clean_paragraphs(
        ["기사 본문이 충분히 길게 이어지는 문장이다.", "ⓒ 무단 전재 및 재배포 금지"]
    )
    assert kept == ["기사 본문이 충분히 길게 이어지는 문장이다."]


def test_머리_규칙은_본문_시작_전까지만_적용된다() -> None:
    """기사 중간의 날짜 줄까지 지우면 떨어져 있던 문장이 붙어 원문에 없던 흐름이 생긴다."""
    paras = [
        "2026-09-18 15:30",  # 머리 — 지운다
        "본문 첫 문장이 여기서 시작된다.",
        "2026년 3분기 실적은 시장 기대를 웃돌았다.",  # 본문 — 날짜로 시작해도 남긴다
    ]
    kept, _log = clean_paragraphs(paras)
    assert kept == paras[1:]


def test_종결부호_없는_짧은_머리줄은_부제로_본다() -> None:
    paras = ["HBM 공급 확대", "회사는 공급을 늘리겠다고 밝혔다."]
    kept, log = clean_paragraphs(paras)
    assert kept == ["회사는 공급을 늘리겠다고 밝혔다."]
    assert ("subhead", "HBM 공급 확대") in log


def test_중국어_문단은_부제로_오해하지_않는다() -> None:
    """마침표가 '。' 라서 종결부호 판정에서 빠지면 멀쩡한 본문이 부제로 버려진다."""
    paras = ["台積電表示本季產能已經全部售罄。", "다음 문장이 이어진다."]
    kept, _log = clean_paragraphs(paras)
    assert paras[0] in kept


def test_제목을_본문에_한번_더_실은_것은_버린다() -> None:
    title = "칩 위에 메모리 통째로 얹었다 삼성전자 zHBM 승부수"
    kept, log = clean_paragraphs([title, "삼성전자가 기술 비전을 공개했다."], title=title)
    assert kept == ["삼성전자가 기술 비전을 공개했다."]
    assert log[0][0] == "title_echo"
