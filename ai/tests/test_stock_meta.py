"""종목 정보 표(stock_meta.json)."""

import json

from app.services.stock_analysis import stock_meta


def test_table_shape_and_lookup():
    table = json.loads(stock_meta.META_PATH.read_text(encoding="utf-8"))["stocks"]
    assert len(table) >= 30
    for code, info in table.items():
        assert len(code) == 6 and code.isdigit()
        assert isinstance(info["sector"], list) and info["sector"]
        assert info["universe_weight"] is None or 0 < info["universe_weight"] < 1
    # 유니버스 20종목 비중의 합은 1 에 가깝다(스냅숏)
    assert abs(sum(i["universe_weight"] for i in table.values() if i["universe_weight"]) - 1) < 0.01
    assert stock_meta.sector("009150") == ["전자부품", "MLCC", "카메라모듈", "반도체 기판"]
    assert stock_meta.sector("005930") == ["반도체", "스마트폰"]
    # 라벨 기준: 한 종목 라벨은 많아야 4개
    assert all(len(info["sector"]) <= 4 for info in table.values())
    assert stock_meta.universe_weight("005930") > 0.3
    assert stock_meta.sector("999990") is None and stock_meta.universe_weight("999990") is None
