"""분류에 쓰는 문장 분리 규칙의 버전.

사건은 근거를 "몇 번 문장" 으로 남긴다(전제 P2). 그 번호는 분리 규칙이 같아야 다시 찾을 수 있다.
그래서 회차마다 `splitter_version` 을 남기고, 예전 회차는 그 버전의 함수로 원문을 다시 나눈다.

**배포한 버전의 동작은 바꾸지 않는다.** 규칙을 고쳐야 하면 새 버전을 더한다(DRAFT 8절).
v1 은 news_link 의 규칙을 그대로 쓴다. 그쪽 규칙이 바뀌면 test_classification_splitter 의
고정 입력 시험이 깨진다 — 그때 v1 을 지금 동작 그대로 이 파일에 옮겨 두고 v2 를 더한다.
"""

from collections.abc import Callable

from app.services.news_link.sentence import split_sentences

SPLITTERS: dict[str, Callable[[str], list[str]]] = {
    "v1": split_sentences,
}
LATEST = "v1"


def split(body: str, version: str = LATEST) -> list[str]:
    if version not in SPLITTERS:
        raise KeyError(f"없는 문장 분리 버전: {version}")
    return SPLITTERS[version](body)


def numbered(sentences: list[str]) -> str:
    """LLM 에 넣는 형태. 번호는 1부터다 — 사건의 sentence_indices 와 같다."""
    return "\n".join(f"[{i}] {sentence}" for i, sentence in enumerate(sentences, start=1))
