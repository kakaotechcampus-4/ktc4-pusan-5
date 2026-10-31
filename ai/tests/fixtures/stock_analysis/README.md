# stock_analysis 샘플 입력

**모든 종목·메시지·주소는 가상이며 테스트 전용이다.**

- 종목명·종목코드(`솔마루전자 999990`, `하늬결화학 999980`)는 실제 상장 종목과 겹치지 않는다.
  2026-09-28 에 KRX 상장법인 목록과 네이버 증권 종목 검색(ETF 포함)으로 확인했다.
- 메시지 본문에 실존 회사·인물·기관 이름을 쓰지 않는다.
- `url`·`channel` 은 `t.me/sample_channel_*`, `example.com` 처럼 가상임이 드러나는 값만 쓴다.

본문에 "샘플"·"가짜" 같은 표시를 넣지 않은 이유: 모델이 그 표시를 "출처 스스로 확인되지
않았다고 밝힌 정보" 로 읽어 `unconfirmed` 를 켜고 판정을 낮춘다. 또 quote 에서 표시를 빼고
인용하면 근거 검사가 오탐을 낸다. 입력이 실제와 같은 모양이어야 러너 검증이 의미가 있다.

보고서는 두 층을 따로 판정한다. 등락 층(`layer: "move"`, `verdict`)은 종목 등락률의 부호,
상대 층(`layer: "relative"`, `relative_verdict`)은 `excess_pct` 의 부호가 방향이다.
층마다 절댓값이 1 이하면 그 층 판정은 `no_clear_cause` 이고 그 층 link 를 가진 factor 는 없다.
사건 하나는 factor 하나이고, 어느 층에 답하는지는 factor 의 `links` 로 단다.

| 파일 | 케이스 |
|---|---|
| `sample_cause.json` | 원인이 있는 하락(-4.2%, 코스피 -0.5%, `excess_pct` -3.6). 직접 공시 + 간접 업황. 두 층 모두 아래 |
| `sample_flat.json` | 두 층 모두 ±1% 이내(+0.45%, `excess_pct` +0.25, 11:00 기준). 원인 없음이 정답인 케이스 |
| `sample_market_driven.json` | `move_case: opposite`. 다른 대형주보다 덜 내린 하락(-1.8%, 대형주 중간값 -3.2%, `excess_pct` +1.4). 악재(2대 주주 지분 처분)는 등락 층 원인이 될 수 있지만 상대 층(위쪽) 원인은 될 수 없다 |
| `sample_less_down.json` | 덜 내린 날(-0.39%, 중간값 -2.41%, `excess_pct` +2.02). 등락 층은 ±1% 이내라 `move` factor 가 없고, 호재 1개가 상대 층 원인 |
| `sample_up_no_cause.json` | 재료 없이 오른 날(+0.54%, 중간값 -2.41%, `excess_pct` +2.95). 등락 층은 ±1% 이내, 상대 층은 종목 고유 재료가 없어 `factors` 는 비고 `not_found` 를 채운다 |
| `sample_two_layers.json` | 덜 내린 하락일(-1.2%, 중간값 -2.41%, `excess_pct` +1.21). 업종 악재(간접)가 등락 층, 자사주 매입 호재(직접)가 상대 층 원인 |
| `sample_more_down.json` | 시장보다 더 내린 날(-7.0%, 중간값 -1.5%, `excess_pct` -5.5). 업종 악재(간접)가 등락 층, 고객사 공급사 제외(직접)가 상대 층 원인. 두 층 모두 아래 |
| `sample_big_up.json` | 크게 오르고 다른 대형주보다도 크게 오른 날(+6.5%, 중간값 -0.6%, `excess_pct` +7.1). 공급 계약 호재(직접) 하나가 factor 하나에 `move`·`relative` 두 link 로 들어간다. 층마다 factor 를 복제하면 통과하되 `DUPLICATE_SOURCES` 경고가 붙는다 |
| `sample_market_share_down.json` | 하락 대부분이 시장 몫인 날(-3.57%, 중간값 -2.62%, `excess_pct` -0.95). 종목 고유 재료(직접, 공장 보수) 하나로 `move` 가 `sufficient` 면 `MOVE_SUFFICIENT_STOCK_ONLY`, `partial` 이면 통과. 상대 층은 ±1% 이내 |

`sample_less_down.json`·`sample_up_no_cause.json`·`sample_two_layers.json`·`sample_more_down.json`·
`sample_big_up.json`·`sample_market_share_down.json`
은 위 원칙의 예외로 메시지 앞에 `[샘플]` 을 붙였다. 요청에 따른 것이고, 이것들로 실제 모델을
돌리면 `unconfirmed` 가 켜질 수 있다.

실제 케이스는 사람이 채운다. 실제 종목·메시지를 이 폴더에 넣지 않는다.
