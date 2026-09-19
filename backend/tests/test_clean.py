from app.services.news.clean import MAX_CHARS, clean_text


def test_clean_text_drops_byline_and_copyright_tail():
    raw = (
        "본문 첫 문단입니다. " * 20
        + "\n홍길동 기자 hong@news.com\n"
        + "둘째 문단. " * 20
        + "\nⓒ 뉴스사 무단 전재 및 재배포 금지\n이 줄은 버려져야 한다"
    )
    out = clean_text(raw)
    assert out.startswith("본문 첫 문단입니다.")
    assert "hong@" not in out
    assert "무단 전재" not in out
    assert "이 줄은 버려져야 한다" not in out


def test_clean_text_caps_length():
    assert len(clean_text("가" * (MAX_CHARS + 2000))) == MAX_CHARS
