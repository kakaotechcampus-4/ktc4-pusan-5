"""PDF 텍스트 추출. 임시 PDF 를 직접 만들어 실제로 pdftotext 를 태운다."""

import hashlib
from pathlib import Path

from app.services.analyst.pdf import PDF_MAX_BYTES, extract_pdf_text, pdf_text_from_bytes


def _three_page_pdf(path: Path) -> Path:
    """'page 1' ~ 'page 3' 이 적힌 3쪽짜리 최소 PDF."""
    pages = b"".join(
        b"%d 0 obj<</Type/Page/Parent 1 0 R/MediaBox[0 0 200 200]/Contents %d 0 R"
        b"/Resources<</Font<</F1 9 0 R>>>>>>endobj\n" % (n, n + 3)
        for n in (2, 3, 4)
    )
    streams = b"".join(
        b"%d 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 100 Td (page %d) Tj ET\nendstream endobj\n"
        % (n + 3, n - 1)
        for n in (2, 3, 4)
    )
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Pages/Kids[2 0 R 3 0 R 4 0 R]/Count 3>>endobj\n"
        + pages
        + streams
        + b"9 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"8 0 obj<</Type/Catalog/Pages 1 0 R>>endobj\n"
        # xref 오프셋은 일부러 0 으로 둔다 — pdftotext 는 그래도 읽고, pypdf 는 깨진
        # xref 를 만나면 파일 전체를 훑어 객체를 다시 찾는다. 다만 `%%EOF` 는 있어야 한다.
        # 없으면 pypdf 가 "Stream has ended unexpectedly" 로 죽는다.
        b"trailer<</Root 8 0 R/Size 10>>\nstartxref\n0\n%%EOF\n"
    )
    return path


def test_page_count_comes_from_form_feeds(tmp_path: Path) -> None:
    r"""pdftotext 는 페이지 수를 따로 안 준다. 페이지 사이 폼피드(\f)를 세서 얻는다."""
    text, how, pages = extract_pdf_text(_three_page_pdf(tmp_path / "t.pdf"))
    assert how == "pdftotext"
    assert pages == 3
    assert "page 1" in text


def test_falls_back_to_pypdf_when_pdftotext_returns_nothing(tmp_path: Path, monkeypatch) -> None:
    """poppler 26.07 은 Catalog 를 못 읽고도 **종료코드 0** 을 준다.

    받아온 PDF 55건 중 21건이 그랬고, 그중 203쪽짜리 리포트가 본문 0자로 들어갔다.
    rc 만 보고 성공으로 치면 안 된다는 것을 고정한다.
    """
    import subprocess

    from app.services.analyst import pdf as pdf_mod

    class EmptySuccess:
        returncode = 0
        stdout = ""
        stderr = 'Syntax Error: Catalog dictionary does not contain a valid "Pages" entry'

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: EmptySuccess())
    monkeypatch.setattr(pdf_mod.shutil, "which", lambda _: "/usr/bin/pdftotext")

    text, how, pages = extract_pdf_text(_three_page_pdf(tmp_path / "t.pdf"))
    assert how == "pypdf"  # rc=0 이어도 글자가 없으면 폴백한다
    assert pages == 3
    assert "page 1" in text


# ---------------------------------------------------------- 바이트 → PdfText
#
# 여기가 네이버와 텔레그램이 같이 쓰는 자리다. 처음에는 이 판정이 네이버 클라이언트
# 안에 있었는데, 텔레그램 수집기를 만들면서 같은 코드를 그대로 베끼게 돼서 옮겼다.


def test_pdf_text_from_bytes_returns_ok_with_text(tmp_path: Path) -> None:
    blob = _three_page_pdf(tmp_path / "t.pdf").read_bytes()
    result = pdf_text_from_bytes(blob)
    assert result.status == "ok"
    assert result.pages == 3
    assert "page 1" in result.text
    assert result.sha256 == hashlib.sha256(blob).hexdigest()
    assert result.size_bytes == len(blob)


def test_pdf_text_from_bytes_rejects_non_pdf() -> None:
    """확장자만 .pdf 인 파일이 실제로 온다. 서명을 본다."""
    result = pdf_text_from_bytes(b"<html>Not Found</html>")
    assert result.status == "failed"
    assert "서명" in result.error


def test_pdf_text_from_bytes_rejects_oversized() -> None:
    result = pdf_text_from_bytes(b"%PDF-1.4" + b"0" * PDF_MAX_BYTES)
    assert result.status == "failed"
    assert "용량" in result.error


def test_pdf_text_from_bytes_marks_empty_when_no_text(tmp_path: Path, monkeypatch) -> None:
    """글자가 0자여도 failed 가 아니다. 이미지 스캔본이라 OCR 말고는 방법이 없다.

    쪽수는 남긴다 — 나중에 OCR 대상을 고를 때 쓴다.
    """
    from app.services.analyst import pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "extract_pdf_text", lambda _: ("", "pdftotext", 44))
    result = pdf_text_from_bytes(_three_page_pdf(tmp_path / "t.pdf").read_bytes())
    assert result.status == "empty"
    assert result.pages == 44
    assert result.sha256  # 해시는 남는다. 같은 PDF 인지 나중에 비교한다


def test_pdf_text_from_bytes_survives_broken_pdf(tmp_path: Path, monkeypatch) -> None:
    """pypdf 는 깨진 PDF 에서 온갖 예외를 낸다. 한 건만 버리고 배치는 계속 간다."""
    from app.services.analyst import pdf as pdf_mod

    def boom(_):
        raise ValueError("깨진 xref")

    monkeypatch.setattr(pdf_mod, "extract_pdf_text", boom)
    result = pdf_text_from_bytes(_three_page_pdf(tmp_path / "t.pdf").read_bytes())
    assert result.status == "failed"
    assert "ValueError" in result.error
    assert result.sha256  # 어느 파일이 깨졌는지 알 수 있어야 한다
