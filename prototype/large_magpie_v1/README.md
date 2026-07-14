# 큰 까치 V1 정적 프로토타입

승인된 큰 까치 V1 기획을 실제 WFF에 연결하기 전에 검증하는 개발용 프로토타입이다.

## 포함 범위

- 절대 시각 기반 43분 사이클
- 분침 직접 경로
- 시침에서 분침으로 환승하는 경로
- 매화 걷기 경로
- 사이클당 호랑이 반응 1회 예약
- 마지막 호랑이 머리 체류와 오른쪽 퇴장
- 현재 시각에서 상태·좌표를 복원하는 무상태 계산
- 24시간 압축 GIF와 시침 환승 상세 GIF

현재 숫자와 좌표는 첫 시뮬레이션을 위한 튜닝값이다. 산출물은 정적 합성 시뮬레이션이며 AGIF 제작이나 WFF 연결 완료를 뜻하지 않는다.

## 결과물

- [`large_magpie_v1_24h_debug.gif`](output/large_magpie_v1_24h_debug.gif): 2026-07-14 하루를 약 20초로 압축
- [`large_magpie_v1_hour_transfer_detail.gif`](output/large_magpie_v1_hour_transfer_detail.gif): 시침 착석부터 분침 환승·호랑이 착석·퇴장까지 상세 흐름
- [`large_magpie_v1_hour_transfer_contact_sheet.png`](output/large_magpie_v1_hour_transfer_contact_sheet.png): 상태별 정지 화면
- [`prototype_report.json`](output/prototype_report.json): 경로 횟수, 상세 사이클, 프레임 수 기록

## 실행

저장소 루트에서 다음을 실행한다.

```bash
python3 -m unittest prototype.large_magpie_v1.test_scene_calculator -v
python3 -m prototype.large_magpie_v1.render_prototype
```

설정값은 `config.json`, 결정 규칙과 위치 계산은 `scene_calculator.py`, 렌더링은 `render_prototype.py`에서 관리한다.
