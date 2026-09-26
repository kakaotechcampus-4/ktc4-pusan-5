"""PDF → 텍스트.

받아오는 방법(네이버는 HTTP, 텔레그램은 Telethon)은 각 어댑터가 갖고, **받아온
바이트를 판정해 PdfText 로 만드는 일은 여기 하나로 모은다.** 처음에는 이 판정을
네이버 클라이언트 안에 뒀는데, 텔레그램 수집기를 만들면서 같은 코드를 그대로 베끼게 됐다.
용량 확인·%PDF 서명·sha256·임시파일·empty 판정이 전부 출처와 무관하다.
"""

import hashlib
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.services.analyst.schema import PdfText

logger = logging.getLogger(__name__)

# 폭주 방지용 상한이지 "이만큼이면 충분하다"는 값이 아니다.
# Postgres TEXT 는 사실상 무제한(1GB)이고 PDF 자체를 50MB 로 이미 막고 있으므로
# 내용 때문에 자를 이유가 없다. 손상된 PDF 가 수백 MB 텍스트를 토해내는 경우에만 걸리라고 둔다.
MAX_BODY_CHARS = 5_000_000
PDF_MAX_BYTES = 50 * 1024 * 1024


def extract_pdf_text(path: Path) -> tuple[str, str, int | None]:
    """(텍스트, 추출기, 페이지수). pdftotext -raw 우선, 한 글자도 못 뽑으면 pypdf.

    **`-raw` 를 쓴다.** pdftotext 에는 `-layout`(화면 위치 재현)과 `-raw`(읽기 순서)가
    있는데, -layout 은 좌우 위치를 공백으로 흉내 내느라 사이드바가 본문 문장
    한가운데로 끼어든다 — 실제로 `영업이익 1,514억` 다음에 사이드바 두 줄이 들어가고
    그 뒤에 `원(+10%...)` 이 붙었다. -raw 는 그 문제가 없고 표도 행 단위로 살아남는다.
    리포트 46건을 둘 다 돌려 비교했고 -raw 가 전부 낫거나 같았다.

    **성공 판정을 종료코드가 아니라 글자수로 한다.** poppler 26.07 은
    `Catalog dictionary does not contain a valid "Pages" entry` 로 아무것도 못 읽고도
    종료코드 0 을 준다. 받아온 PDF 55건 중 21건이 그랬고, 그중 203쪽짜리 리포트가
    본문 0자로 들어갔다. pypdf 는 같은 파일을 정상으로 읽는다.

    페이지 수는 pdftotext 가 따로 안 알려주는 대신 **페이지마다 끝에** 폼피드(\\f)를
    붙여준다. 그래서 자르기 전 원본에서 세면 그대로 페이지 수다 —
    프로세스를 한 번 더 띄울 필요가 없다.
    """
    if shutil.which("pdftotext"):
        proc = subprocess.run(
            ["pdftotext", "-raw", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,  # 실패는 아래에서 글자수로 판정한다. 예외로 올리지 않는다
        )
        raw = proc.stdout if proc.returncode == 0 else ""
        if raw.strip():
            return raw.strip()[:MAX_BODY_CHARS], "pdftotext", raw.count("\f") or 1
        logger.warning(
            "pdftotext가 본문을 못 뽑았다(rc=%s, %d자) → pypdf로 넘어간다: %s",
            proc.returncode,
            len(proc.stdout),
            (proc.stderr or "").strip()[:120],
        )

    import pypdf  # 없으면 여기서 ImportError. 호출부가 failed 로 기록한다.

    reader = pypdf.PdfReader(str(path))
    # pypdf 는 폼피드를 안 넣는다. 위에서 \f 로 쪽을 세므로 여기서 직접 끼워넣는다.
    text = "\f".join((p.extract_text() or "") for p in reader.pages)
    return text.strip()[:MAX_BODY_CHARS], "pypdf", len(reader.pages)


def pdf_text_from_bytes(blob: bytes) -> PdfText:
    """받아온 PDF 바이트 → PdfText. **동기 함수다** — 호출부가 to_thread 로 돌린다.

    임시 폴더에 썼다가 블록을 나오면서 지운다. 원본은 남기지 않는다.
    상태를 셋으로 가른다.

        ok      텍스트가 나왔다
        empty   PDF 는 멀쩡한데 글자가 0자다. 이미지로만 된 스캔본이라 OCR 말고는
                방법이 없다. 파이프라인 실패가 아니라서 failed 와 구분한다.
                쪽수는 남긴다 — 나중에 OCR 대상을 고를 때 쓴다.
        failed  용량 초과, PDF 가 아님, 추출 중 예외
    """
    if len(blob) > PDF_MAX_BYTES:
        return PdfText(status="failed", error=f"용량 초과 {len(blob)}B")
    if not blob.startswith(b"%PDF"):
        return PdfText(status="failed", error="PDF 서명 없음")

    sha = hashlib.sha256(blob).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.pdf"
        path.write_bytes(blob)
        try:
            text, how, pages = extract_pdf_text(path)
        # pypdf 는 깨진 PDF 에서 온갖 예외를 낸다. 한 건만 버리고 배치는 계속 간다.
        except Exception as exc:  # noqa: BLE001
            return PdfText(
                status="failed",
                sha256=sha,
                size_bytes=len(blob),
                error=f"{type(exc).__name__}: {exc}"[:500],
            )

    if not text:
        return PdfText(
            status="empty", sha256=sha, size_bytes=len(blob), pages=pages, extractor=how
        )
    return PdfText(
        status="ok",
        text=text,
        chars=len(text),
        sha256=sha,
        size_bytes=len(blob),
        pages=pages,
        extractor=how,
    )
