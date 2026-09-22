"""문장 세는 규칙. 자르는 쪽과 세는 쪽이 어긋나면 있지도 않은 문제가 보고된다."""

from app.services.news_link.sentence import first_sentences, sentence_ends, split_sentences


def test_소수점에서_끊지_않는다() -> None:
    body = "주가는 $1.56 에 마감했다. 거래량은 평소의 두 배였다."
    assert len(split_sentences(body)) == 2


def test_약어에서_끊지_않는다() -> None:
    """U.S. · Sept. 에서 끊으면 3문장 발췌가 6문장으로 세어진다."""
    body = "The U.S. market closed higher on Sept. 17 amid chip demand. Traders were upbeat."
    assert len(split_sentences(body)) == 2


def test_숫자로_끝나는_문장은_안_끊긴다_알려진_한계다() -> None:
    """소수점($1.56)에서 안 끊으려고 숫자 뒤 마침표를 전부 제외한 대가다.

    발췌가 의도보다 길어질 뿐 글자를 바꾸지는 않으므로 상한이 받아낸다.
    고치려면 '숫자.공백+대문자/한글' 을 따로 봐야 하는데, 오탐 쪽이 더 비싸서 두었다.
    """
    body = "매출은 전년 대비 늘어 100. 영업이익도 개선됐다."
    assert len(split_sentences(body)) == 1


def test_문단_경계도_문장_끝으로_친다() -> None:
    """마침표 없이 끝나는 소제목에서 안 끊으면 세 문장이 본문 절반을 삼킨다."""
    body = "1. 유가\n유가가 올랐다. 정유주가 강세였다."
    assert split_sentences(body)[0] == "1. 유가"


def test_발췌는_언제나_본문의_앞부분_그대로다() -> None:
    body = "첫 문장이다. 둘째 문장이다. 셋째 문장이다. 넷째 문장이다."
    excerpt = first_sentences(body, 3, 400)
    assert body.startswith(excerpt)
    assert excerpt.endswith("셋째 문장이다.")


def test_상한을_넘으면_문장_경계로_되돌린다() -> None:
    """상한에서 그냥 자르면 발췌가 문장 중간에서 끝나 모델이 잘못 읽는다."""
    body = "짧은 문장이다. " + "아주 " * 100 + "긴 문장이다."
    excerpt = first_sentences(body, 3, 40)
    assert excerpt == "짧은 문장이다."


def test_문장이_하나도_안_끝나면_전체를_준다() -> None:
    body = "마침표가 없는 한 줄짜리 본문"
    assert first_sentences(body, 3, 400) == body
    assert sentence_ends(body) == []


def test_문장_경계가_없고_상한도_넘으면_상한에서_자른다() -> None:
    """유일하게 발췌가 문장 중간에서 끝나는 경로다. 그래도 **앞부분 그대로**는 지킨다.

    되돌릴 문장 경계가 하나도 없으니 상한에서 자르는 수밖에 없다. 말은 끊기지만
    글자를 바꾸지는 않으므로 인용 대조는 살아 있다. 그쪽이 더 중요하다.
    """
    body = "마침표도 줄바꿈도 없이 " * 60
    excerpt = first_sentences(body, 3, 400)
    assert len(excerpt) <= 400
    assert body.startswith(excerpt)
