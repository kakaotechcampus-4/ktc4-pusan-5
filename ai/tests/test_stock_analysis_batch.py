"""보고서 일괄 생성(app/collectors/stock_analysis_batch) 시험. DB·LLM·러너는 가짜로 바꾼다."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.collectors import stock_analysis_batch as batch
from app.core.scope import KST
from app.services.stock_analysis import classified_input as adapter
from app.services.stock_analysis import stock_meta

MON = date(2026, 11, 16)  # 월요일. 직전 거래일은 금요일 11-13
TUE = date(2026, 11, 10)
SUNEUNG = date(2026, 11, 19)  # 수능일. 장 마감 16:30
AFTER_SUNEUNG = date(2026, 11, 20)  # 금요일. 직전 거래일이 수능일


def kst(day: date, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, ss, tzinfo=KST)


# ---------------------------------------------------------------- 종목표

def test_보고서_대상은_종목표_30종목_전부():
    codes = stock_meta.codes()
    assert len(codes) == 30
    assert list(codes) == sorted(codes)
    assert all(stock_meta.name(c) for c in codes)


# ---------------------------------------------------------------- 기준 시각·대상일 (어댑터 문서의 규칙)

def test_기준_시각은_실행_시각이_아니라_정각():
    assert batch.cutoff_of("close", TUE) == kst(TUE, 16, 0)
    assert batch.cutoff_of("morning", TUE) == kst(TUE, 8, 30)


def test_16시_보고서의_대상일은_오늘():
    assert batch.target_date_of("close", TUE, None) == TUE


def test_08시30분_보고서의_대상일은_직전_거래일():
    assert batch.target_date_of("morning", TUE, None) == date(2026, 11, 9)  # 화요일 → 월요일
    assert batch.target_date_of("morning", MON, None) == date(2026, 11, 13)  # 월요일 → 금요일(주말 건너뜀)


def test_휴장일_다음_날_08시30분은_달력으로_직전_거래일을_찾는다():
    # 월요일 11-16 이 휴장이면 화요일 11-17 의 직전 거래일은 금요일 11-13
    open_days = {date(2026, 11, 16): False, date(2026, 11, 13): True}
    assert batch.target_date_of("morning", date(2026, 11, 17), open_days) == date(2026, 11, 13)


def test_수능일_다음_날의_대상일은_수능일이고_마감은_16시30분():
    assert batch.target_date_of("morning", AFTER_SUNEUNG, None) == SUNEUNG
    assert batch.close_of(SUNEUNG) == kst(SUNEUNG, 16, 30)
    assert batch.close_of(TUE) == kst(TUE, 15, 30)


# ---------------------------------------------------------------- 시세를 등락률로 써도 되는가

def test_시세는_대상일_장_마감부터_기준_시각까지_받은_것만_인정한다():
    close = batch.close_of(TUE)  # 15:30
    cutoff = batch.cutoff_of("close", TUE)  # 16:00
    assert batch.quote_problem(close, TUE, cutoff) is None  # 마감 정각
    assert batch.quote_problem(close + timedelta(minutes=10), TUE, cutoff) is None
    assert batch.quote_problem(cutoff, TUE, cutoff) is None  # 기준 시각 정각까지 포함
    assert "전에 받은 시세" in batch.quote_problem(close - timedelta(seconds=1), TUE, cutoff)
    assert "뒤에 받은 시세" in batch.quote_problem(cutoff + timedelta(seconds=1), TUE, cutoff)


def test_08시30분_회차는_전날_저녁에_받은_시세도_종가로_인정한다():
    # 마감 무렵 수집기가 멈췄다 저녁 8시에 받은 정상 값. 마감~다음 개장 전엔 장이 안 열려 값이 같다
    monday = date(2026, 11, 9)
    cutoff = batch.cutoff_of("morning", TUE)  # 화요일 08:30, 대상일 월요일
    assert batch.quote_problem(kst(monday, 20, 0), monday, cutoff) is None
    assert batch.quote_problem(kst(TUE, 8, 29), monday, cutoff) is None  # 기준 시각 직전까지


def test_08시30분_회차는_다음날_장중_값을_거른다():
    # 08:30 회차를 장중에 수동으로 다시 돌릴 때를 포함해, 기준 시각 뒤에 받은 값은 보고서가 알면 안 된다
    monday = date(2026, 11, 9)
    cutoff = batch.cutoff_of("morning", TUE)
    assert "뒤에 받은 시세" in batch.quote_problem(kst(TUE, 9, 1), monday, cutoff)


def test_시세가_없으면_사유를_돌려준다():
    assert "행이 없다" in batch.quote_problem(None, TUE, batch.cutoff_of("close", TUE))


def test_수능일_종가는_16시30분_뒤_시세만_인정한다():
    cutoff = batch.cutoff_of("morning", AFTER_SUNEUNG)  # 다음 날 08:30
    assert batch.quote_problem(kst(SUNEUNG, 15, 31), SUNEUNG, cutoff) is not None  # 보통날 마감 뒤여도 그날은 장중
    assert batch.quote_problem(kst(SUNEUNG, 16, 31), SUNEUNG, cutoff) is None


def test_시간대가_다른_시각도_KST로_맞춰_본다():
    close = batch.close_of(TUE)
    assert batch.quote_problem(close.astimezone(datetime.now().astimezone().tzinfo), TUE,
                               batch.cutoff_of("close", TUE)) is None


# ---------------------------------------------------------------- 실행 흐름 (가짜 DB·러너)

class Fake:
    """DB 세션·어댑터·러너를 대신한다."""

    def __init__(self, monkeypatch, tmp_path: Path, *, quotes: dict, fail: dict | None = None,
                 open_days=None, run_result: dict | None = None, run_error: Exception | None = None):
        self.tmp = tmp_path
        self.quotes = quotes
        self.fail = fail or {}
        self.loaded: list[dict] = []
        self.run_calls: list[dict] = []
        self.opened = 0
        self.rolled_back = 0
        self.run_result = run_result if run_result is not None else {"errors": 0}
        self.run_error = run_error
        fake = self

        class Session:
            async def rollback(self_inner):
                fake.rolled_back += 1

        @asynccontextmanager
        async def session_factory():
            fake.opened += 1
            yield Session()

        async def read_open_days(session, day):
            return open_days

        async def read_quotes(session, codes):
            return {c: fake.quotes[c] for c in codes if c in fake.quotes}

        async def load_input(session, code, *, cutoff, change_pct, target_date=None, since=None):
            if code in fake.fail:
                raise fake.fail[code]
            fake.loaded.append({"code": code, "cutoff": cutoff, "change_pct": change_pct,
                                "target_date": target_date})
            payload = {"stock": code, "code": code, "target_date": target_date.isoformat(),
                       "cutoff": cutoff.isoformat(), "change_pct": change_pct, "messages": []}
            return payload, {"code": code}

        async def run(input_dir, *, out_root, concurrency, load):
            fake.run_calls.append({"input_dir": input_dir, "out_root": out_root,
                                   "concurrency": concurrency, "load": load,
                                   "files": sorted(p.name for p in input_dir.glob("*.json"))})
            if fake.run_error:
                raise fake.run_error
            return fake.run_result

        monkeypatch.setattr(batch, "SessionLocal", session_factory)
        monkeypatch.setattr(batch, "read_quotes", read_quotes)
        monkeypatch.setattr(batch.adapter, "read_open_days", read_open_days)
        monkeypatch.setattr(batch.adapter, "load_input", load_input)
        monkeypatch.setattr(batch.runner, "run", run)

    async def go(self, mode: str, now: datetime, codes, *, load=True, dry_run=False, concurrency=2,
                 chunk_size=batch.CHUNK_SIZE) -> int:
        return await batch.run_batch(mode, now=now, out_root=self.tmp, codes=codes, load=load,
                                     dry_run=dry_run, concurrency=concurrency, chunk_size=chunk_size)


def good_quote(day: date, change: float = -1.5) -> tuple[float, datetime]:
    return change, batch.close_of(day) + timedelta(minutes=1)


async def test_16시_회차는_대상일_오늘로_입력을_만들고_러너에_한_번_넘긴다(monkeypatch, tmp_path, capsys):
    f = Fake(monkeypatch, tmp_path, quotes={"005930": good_quote(TUE, -2.0), "000660": good_quote(TUE, 3.1)})
    assert await f.go("close", kst(TUE, 16, 0, 20), ["005930", "000660"]) == 0
    assert [(x["code"], x["change_pct"]) for x in f.loaded] == [("005930", -2.0), ("000660", 3.1)]
    assert all(x["target_date"] == TUE and x["cutoff"] == kst(TUE, 16, 0) for x in f.loaded)  # 정각
    (call,) = f.run_calls
    assert call["load"] is True and call["concurrency"] == 2 and call["out_root"] == tmp_path
    assert call["files"] == ["000660-2026-11-10-1600.json", "005930-2026-11-10-1600.json"]
    assert call["input_dir"].name == "run-01"
    assert call["input_dir"].parent.parent == tmp_path / "classified_inputs"
    assert "입력 2건 만듦" in capsys.readouterr().out


async def test_08시30분_회차는_직전_거래일을_대상일로_준다(monkeypatch, tmp_path):
    f = Fake(monkeypatch, tmp_path, quotes={"005930": good_quote(date(2026, 11, 13))})
    assert await f.go("morning", kst(MON, 8, 30, 5), ["005930"]) == 0
    (item,) = f.loaded
    assert item["target_date"] == date(2026, 11, 13)  # 월요일 08:30 → 금요일
    assert item["cutoff"] == kst(MON, 8, 30)
    assert f.run_calls[0]["files"] == ["005930-2026-11-13-0830.json"]


async def test_장_마감_값이_아닌_시세의_종목은_건너뛰고_나머지는_만든다(monkeypatch, tmp_path, capsys):
    stale = (0.5, batch.close_of(TUE) - timedelta(minutes=10))  # 장중에 받은 값
    f = Fake(monkeypatch, tmp_path, quotes={"005930": good_quote(TUE), "000660": stale})
    # 005380 은 시세 행이 아예 없다
    assert await f.go("close", kst(TUE, 16, 0), ["005930", "000660", "005380"]) == 1  # 건너뜀이 있어 1
    assert [x["code"] for x in f.loaded] == ["005930"]
    assert f.run_calls[0]["files"] == ["005930-2026-11-10-1600.json"]  # 러너에는 만든 것만
    out = capsys.readouterr().out
    assert "건너뜀 000660" in out and "전에 받은 시세" in out
    assert "건너뜀 005380" in out and "시세 없음" in out


async def test_한_종목의_입력_생성이_실패해도_나머지는_만든다(monkeypatch, tmp_path, capsys):
    f = Fake(monkeypatch, tmp_path,
             quotes={"005930": good_quote(TUE), "000660": good_quote(TUE)},
             fail={"005930": RuntimeError("DB 가 끊겼다")})
    assert await f.go("close", kst(TUE, 16, 0), ["005930", "000660"]) == 1
    assert [x["code"] for x in f.loaded] == ["000660"]
    assert f.rolled_back == 1  # 실패한 쿼리가 세션에 남지 않게
    assert "입력 생성 실패: RuntimeError" in capsys.readouterr().out


async def test_대상일과_기준시각이_안_맞으면_종목_문제가_아니라_멈춘다(monkeypatch, tmp_path):
    f = Fake(monkeypatch, tmp_path, quotes={"005930": good_quote(TUE)},
             fail={"005930": adapter.InputRangeError("target_date 가 맞지 않다")})
    with pytest.raises(adapter.InputRangeError):
        await f.go("close", kst(TUE, 16, 0), ["005930"])
    assert f.run_calls == []


async def test_만들_입력이_하나도_없으면_러너를_부르지_않고_1(monkeypatch, tmp_path):
    f = Fake(monkeypatch, tmp_path, quotes={})
    assert await f.go("close", kst(TUE, 16, 0), ["005930"]) == 1
    assert f.run_calls == []


async def test_dry_run은_입력만_만들고_러너를_부르지_않는다(monkeypatch, tmp_path, capsys):
    f = Fake(monkeypatch, tmp_path, quotes={"005930": good_quote(TUE)})
    assert await f.go("close", kst(TUE, 16, 0), ["005930"], dry_run=True, load=False) == 0
    assert len(f.loaded) == 1 and f.run_calls == []
    assert "dry-run" in capsys.readouterr().out


async def test_load를_안_주면_러너에_load_False로_넘긴다(monkeypatch, tmp_path):
    f = Fake(monkeypatch, tmp_path, quotes={"005930": good_quote(TUE)})
    await f.go("close", kst(TUE, 16, 0), ["005930"], load=False)
    assert f.run_calls[0]["load"] is False


async def test_러너가_실행_오류를_내면_1(monkeypatch, tmp_path):
    f = Fake(monkeypatch, tmp_path, quotes={"005930": good_quote(TUE)}, run_result={"errors": 2})
    assert await f.go("close", kst(TUE, 16, 0), ["005930"]) == 1


async def test_러너가_키_없음_같은_오류로_멈추면_1(monkeypatch, tmp_path, capsys):
    f = Fake(monkeypatch, tmp_path, quotes={"005930": good_quote(TUE)}, run_error=RuntimeError("LLM 키가 없다"))
    assert await f.go("close", kst(TUE, 16, 0), ["005930"]) == 1
    assert "LLM 키가 없다" in capsys.readouterr().out


async def test_수능일_16시_회차는_DB도_러너도_건드리지_않고_0(monkeypatch, tmp_path, capsys):
    f = Fake(monkeypatch, tmp_path, quotes={"005930": good_quote(SUNEUNG)})
    assert await f.go("close", kst(SUNEUNG, 16, 0), ["005930"]) == 0
    assert f.opened == 0 and f.loaded == [] and f.run_calls == []
    assert "늦춰진 날" in capsys.readouterr().out


async def test_수능일_다음날_08시30분은_수능일_16시30분_뒤_시세로_만든다(monkeypatch, tmp_path):
    ok = good_quote(SUNEUNG)  # close_of(수능일) = 16:30 → 16:31 에 받은 값
    f = Fake(monkeypatch, tmp_path, quotes={"005930": ok})
    assert await f.go("morning", kst(AFTER_SUNEUNG, 8, 30), ["005930"]) == 0
    assert f.loaded[0]["target_date"] == SUNEUNG

    stale = Fake(monkeypatch, tmp_path, quotes={"005930": (1.0, kst(SUNEUNG, 15, 31))})  # 보통날 마감 뒤 값
    assert await stale.go("morning", kst(AFTER_SUNEUNG, 8, 30), ["005930"]) == 1
    assert stale.run_calls == []


# ---------------------------------------------------------------- 명령줄

def test_모르는_종목은_명령줄에서_거절한다(capsys):
    with pytest.raises(SystemExit) as exc:
        batch.main(["--mode", "close", "--codes", "000000"])
    assert exc.value.code == 2
    assert "stock_meta.json 에 없는 종목" in capsys.readouterr().err


def test_dry_run과_load는_같이_못_준다(capsys):
    with pytest.raises(SystemExit) as exc:
        batch.main(["--mode", "close", "--dry-run", "--load"])
    assert exc.value.code == 2


def test_모드는_둘_중_하나(capsys):
    with pytest.raises(SystemExit):
        batch.main(["--mode", "noon"])


def test_입력_파일_이름은_러너가_읽는_모양():
    """어댑터 write 가 만드는 이름이 `<코드>-<대상일>-<HHMM>.json` 이고 meta 는 하위 폴더라 러너 --input 폴더 바로 아래에 섞이지 않는다."""
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as d:
        out = Path(d)
        payload = {"code": "005930", "target_date": "2026-11-10", "cutoff": kst(TUE, 16, 0).isoformat()}
        adapter.write(out, payload, {"code": "005930"})
        assert [p.name for p in out.glob("*.json")] == ["005930-2026-11-10-1600.json"]
        assert (out / "meta" / "005930-2026-11-10-1600.json").exists()
        assert json.loads((out / "005930-2026-11-10-1600.json").read_text(encoding="utf-8"))["code"] == "005930"


# ---------------------------------------------------------------- 묶음 나누기와 입력 검사

def many_quotes(n: int) -> tuple[list[str], dict]:
    codes = [f"{i:06d}" for i in range(n)]
    return codes, {c: good_quote(TUE) for c in codes}


def test_묶음_나누기():
    assert batch.chunked(list("abcdefg"), 3) == [["a", "b", "c"], ["d", "e", "f"], ["g"]]
    assert batch.chunked([], 3) == []
    assert batch.CHUNK_SIZE == 10


async def test_종목이_많으면_묶음마다_러너를_따로_부른다(monkeypatch, tmp_path, capsys):
    codes, quotes = many_quotes(25)
    f = Fake(monkeypatch, tmp_path, quotes=quotes)
    monkeypatch.setattr(batch.stock_meta, "name", lambda code: f"종목{code}")
    assert await f.go("close", kst(TUE, 16, 0), codes) == 0
    assert [len(c["files"]) for c in f.run_calls] == [10, 10, 5]
    # 묶음마다 그 묶음의 입력만 들어 있다(러너는 폴더 안 *.json 을 전부 읽는다)
    all_files = [name for c in f.run_calls for name in c["files"]]
    assert len(all_files) == len(set(all_files)) == 25
    assert [c["input_dir"].name for c in f.run_calls] == ["run-01", "run-02", "run-03"]
    assert "묶음 3/3" in capsys.readouterr().out


async def test_묶음_크기를_줄_수_있다(monkeypatch, tmp_path):
    codes, quotes = many_quotes(5)
    f = Fake(monkeypatch, tmp_path, quotes=quotes)
    assert await f.go("close", kst(TUE, 16, 0), codes, chunk_size=2) == 0
    assert [len(c["files"]) for c in f.run_calls] == [2, 2, 1]


async def test_한_묶음이_멈추면_뒤_묶음은_부르지_않고_앞_묶음은_남는다(monkeypatch, tmp_path, capsys):
    codes, quotes = many_quotes(25)
    f = Fake(monkeypatch, tmp_path, quotes=quotes)
    calls = {"n": 0}
    original = batch.runner.run

    async def run(input_dir, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("LLM 호출이 계속 실패한다")
        return await original(input_dir, **kwargs)

    monkeypatch.setattr(batch.runner, "run", run)
    assert await f.go("close", kst(TUE, 16, 0), codes) == 1
    assert len(f.run_calls) == 1  # 첫 묶음만 러너에 닿았다. 둘째는 예외, 셋째는 부르지 않음
    out = capsys.readouterr().out
    assert "묶음 2 에서 멈춤" in out and "앞 묶음 1개의 결과는 적재돼 있다" in out


async def test_한_묶음의_실행_오류는_표시하되_다음_묶음은_계속한다(monkeypatch, tmp_path):
    codes, quotes = many_quotes(12)
    f = Fake(monkeypatch, tmp_path, quotes=quotes, run_result={"errors": 1})
    assert await f.go("close", kst(TUE, 16, 0), codes) == 1
    assert len(f.run_calls) == 2  # 오류가 있어도 둘째 묶음은 돈다


async def test_러너_입력_검사에_걸리는_종목은_미리_빼고_나머지만_넘긴다(monkeypatch, tmp_path, capsys):
    f = Fake(monkeypatch, tmp_path, quotes={"005930": good_quote(TUE), "000660": good_quote(TUE)})
    real = batch.check_input
    monkeypatch.setattr(batch, "check_input",
                        lambda payload: ["messages 가 배열이 아니다"] if payload["code"] == "005930" else real(payload))
    assert await f.go("close", kst(TUE, 16, 0), ["005930", "000660"]) == 1  # 건너뜀이 있어 1
    assert f.run_calls[0]["files"] == ["000660-2026-11-10-1600.json"]  # 러너가 전체를 멈추지 않게 미리 뺐다
    assert "러너 입력 검사 실패" in capsys.readouterr().out


def test_묶음_크기는_1_이상(capsys):
    with pytest.raises(SystemExit) as exc:
        batch.main(["--mode", "close", "--chunk-size", "0"])
    assert exc.value.code == 2


async def test_08시30분_회차는_전날_저녁에_받은_시세의_종목도_만든다(monkeypatch, tmp_path):
    """수정 전에는 마감 +1시간을 넘겨 이 종목이 건너뛰어졌다."""
    friday = date(2026, 11, 13)
    evening = (1.25, kst(friday, 20, 0))  # 마감 무렵 수집기가 멈췄다 저녁에 받은 정상 값
    f = Fake(monkeypatch, tmp_path, quotes={"005930": evening})
    assert await f.go("morning", kst(MON, 8, 30), ["005930"]) == 0
    assert [x["code"] for x in f.loaded] == ["005930"]


async def test_08시30분_회차를_장중에_다시_돌리면_그때_받은_값은_거른다(monkeypatch, tmp_path, capsys):
    friday = date(2026, 11, 13)
    intraday = (4.0, kst(MON, 9, 1))  # 월요일 장중에 받은 값(보고서 기준 시각 08:30 뒤)
    f = Fake(monkeypatch, tmp_path, quotes={"005930": intraday})
    assert await f.go("morning", kst(MON, 11, 0), ["005930"]) == 1  # 수동 재실행. 건너뜀이라 1
    assert f.loaded == [] and f.run_calls == []
    assert "기준 시각" in capsys.readouterr().out and friday < MON
