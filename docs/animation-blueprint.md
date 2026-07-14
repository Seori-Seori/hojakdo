# 호작도 워치페이스 애니메이션 구현 기준서

> 문서 상태: V2.1 시각 보정 완료 기준서
>
> 구현 기준: Watch Face Format(WFF) v1, 논리 좌표계 450×450
>
> 우선순위: 이 문서와 README·임시 예시가 충돌하면 이 문서를 우선한다.

정적 레이어의 실측값과 분리 진행 상황은 [`asset-extraction-plan.md`](asset-extraction-plan.md), V2 계산값과 출력은 [`../prototype/hojakdo_v2`](../prototype/hojakdo_v2)에서 관리한다.

## 1. 핵심 목표와 현재 경계

> 손목 위에서 살아 움직이는 호작도 한 점.

까치는 화면이 켜질 때마다 처음부터 등장하지 않는다. 현재 날짜와 시각만으로 다음을 결정적으로 복원한다.

- 현재 까치 종류
- 경로와 선택 바늘
- 거시 상태와 발 위치
- 방향과 다음 상태
- 세부 행동 예약
- 호랑이 반응 예약

V2.1에서 완성한 것은 두 까치의 **통합 시뮬레이션과 정적 자산 보정**이다. 아직 최종 17개 AGIF, WFF 연결, 에뮬레이터·실기기 구현은 완료되지 않았다.

## 2. 절대 타임라인

| 항목 | 확정값 |
|---|---:|
| 논리 캔버스 | 450×450 |
| 사이클 | 43분 |
| `HIDDEN` | 첫 2분 |
| 동시 까치 | 최대 1마리 |
| 교대 | 큰 까치 ↔ 작은 까치 |
| 퇴장 | 항상 오른쪽 화면 밖까지 |

개념식:

```text
timelineMinute = YEAR·DAY_OF_YEAR·HOUR·MINUTE 기반 절대 분
cycleIndex = floor((timelineMinute - offset) / 43)
cycleLocalMinute = modulo(timelineMinute - offset, 43)
character = cycleIndex 짝수/홀수 교대
```

- 자정에 진행 중인 사이클을 초기화하지 않는다.
- 사이클 시작 때 경로·바늘·세부 행동을 고정하고 중간에 다시 선택하지 않는다.
- 날짜와 사이클 번호를 섞은 고정 난수를 사용한다.
- 같은 시각을 다시 계산하면 같은 결과가 나와야 한다.

## 3. WFF 구현 모델

현재 프로젝트는 `android:hasCode="false"`인 리소스 전용 WFF 워치페이스다. 문서의 상태 머신은 저장 객체가 아니라 WFF 표현식·Condition·Transform으로 계산하는 무상태 시간표를 뜻한다.

### WFF가 담당할 것

- 사이클과 까치 교대
- 경로·바늘·상태 결정
- 거시 좌표와 렌더링 슬롯
- 바늘과 함께 움직이는 발 기준점
- 실제 방향 전환 전후의 정적 자세 선택
- AOD 가시성

### AGIF가 담당할 것

- 짧은 비행·착지·한 걸음·홉
- 고개와 상체 행동
- 실제 방향 전환 동작
- 캐릭터별 퇴장 동작
- 호랑이의 짧은 머리·눈 반응

WFF v1은 AGIF의 임의 프레임으로 탐색할 수 없다. 화면 재점등 시 현재 전환 상태의 짧은 AGIF가 처음부터 한 번 다시 재생될 수 있으나, 거시 좌표·경로·상태·다음 결정값은 바뀌지 않는다.

## 4. 공통 상태 머신

```text
HIDDEN
SPAWN_PINE
FLY_PINE_TO_HAND
LAND_ON_HAND
PERCH_HAND
RIDE_HOUR 또는 RIDE_MINUTE
WAIT_HAND_MEET
HOP_HAND_TO_HAND
SPAWN_PLUM
WALK_FROM_PLUM
LAND_ON_TIGER
PERCH_TIGER
EXIT_RIGHT
```

바늘 경로:

```text
HIDDEN
→ SPAWN_PINE
→ FLY_PINE_TO_HAND
→ LAND_ON_HAND
→ PERCH_HAND
→ RIDE_MINUTE
  또는 RIDE_HOUR → WAIT_HAND_MEET → HOP_HAND_TO_HAND → RIDE_MINUTE
→ LAND_ON_TIGER
→ PERCH_TIGER
→ EXIT_RIGHT
→ HIDDEN
```

매화 경로:

```text
HIDDEN
→ SPAWN_PLUM
→ WALK_FROM_PLUM
→ LAND_ON_TIGER
→ PERCH_TIGER
→ EXIT_RIGHT
→ HIDDEN
```

`EXIT_RIGHT`는 공통 논리 상태다. 큰 까치는 접은 날개 점프, 작은 까치는 두 번의 날갯짓으로 렌더링한다.

## 5. 경로와 바늘 선택

바늘 착석 후보는 다음을 함께 평가한다.

- 좌상단 2사분면 착지
- 캐릭터가 화면 안에 완전히 들어오는지
- 소나무에서의 접근성
- 분침이 호랑이 접근점에 도달하는 시각과 거리
- 시침 선택 시 사이클 안에서 가능한 시침→분침 만남
- 캐릭터별 착석 반경과 약한 선호 가중치

```text
분침만 적합 → MINUTE_DIRECT
시침만 적합 → HOUR_TO_MINUTE
둘 다 적합 → 캐릭터별 약한 선호와 고정 난수
둘 다 부적합 → PLUM_WALK
```

- 큰 까치와 작은 까치 모두 시침·분침·매화 경로를 사용할 수 있다.
- 큰 까치는 안쪽·두꺼운 착석점과 시침에 조금 더 무게를 둔다.
- 작은 까치는 바깥쪽·얇은 착석점과 분침 직접 경로에 조금 더 무게를 둔다.
- 정확한 3회/3회 같은 일일 할당량은 두지 않는다.
- 기본 거리와 경계 거리 후보를 결정적으로 섞어 착지 빈도를 자연스럽게 분산한다.

V2 장기 검증:

| 집계 | 결과 |
|---|---:|
| 기준 | 실제 `LAND_ON_HAND` 완료 시각 |
| 365일 평균 | 5.997회/일 |
| 하루 범위 | 4~8회 |
| 2026-07-14부터 30일 | 181회, 평균 6.033회/일 |

## 6. 큰 까치 행동

성격은 느리고 무게감 있으며 점잖다.

- 낮고 넓은 비행 궤적
- 소나무 등장·비행·첫 착석은 항상 오른쪽을 봄
- 승인된 112% 마스터는 보존하고, V2 화면에서는 발 기준점 중심 0.893배로 렌더링
- 안쪽의 두꺼운 바늘 착석점
- 시침 경로에 약한 선호
- 8분 이상 긴 체류에서 느린 고개 동작 1회
- 구도상 필요할 때 오른쪽→뒤보기→오른쪽 복귀를 한 전환 동작으로 최대 1회
- 등장 순간 즉시 좌우 미러 금지. 전환 AGIF가 긴 체류 중의 뒤보기와 복귀를 담당
- 호랑이에서 날개를 접은 채 낮고 긴 포물선 점프로 화면 오른쪽 밖까지 퇴장
- 작은 까치처럼 퇴장 날갯짓을 넣지 않음

## 7. 작은 까치 행동

성격은 가볍고 활발하며 주변을 자주 살핀다.

- 큰 까치보다 높고 짧은 비행 궤적
- 바깥쪽의 얇은 바늘 착석점
- 분침 직접 경로에 약한 선호
- 8분 이상 긴 체류의 약 25%·50%·75% 지점에 최대 3개 행동
- 기본 순서: `HEAD_SCAN` → `LOOK_PLUM` → `CHECK_TARGET`
- 방향 전환이 필요하면 세 번째 행동을 작은 홉 `TURN`으로 대체
- 발과 장면 좌표는 고정하고 상체만 움직임
- 호랑이 위에서 연속 작은 까치 3사이클 중 정확히 2사이클에 귀 쪼기
- 귀 쪼기는 빠른 두 번의 동작으로 구성
- 오른쪽 퇴장 날개는 피영극의 관절식 조형을 참고해 어깨 관절·상완판·깃 부채가 끊기지 않게 연결
- 날개를 접은 프레임은 원본 몸통 자세를 사용하고, 오른쪽 퇴장 중 정확히 두 번 날갯짓한 뒤 완전히 화면 밖으로 이동

## 8. 호랑이 반응

한 사이클에 정확히 한 번만 반응한다.

```text
머리 작은 기울임
→ 한 박자 뒤 눈동자 이동
→ 작은 반동
→ 중립 자세 복귀
```

- 작은 까치가 귀를 쪼는 사이클: 쪼기가 유일한 반응 원인
- 그 밖의 사이클: 비행·착지·홉·걷기 중 결정된 한 순간이 반응 원인
- 작은 까치에 대한 머리 진폭은 큰 까치보다 작게 설정
- 귀·입·눈 깜박임 등 추가 반응은 넣지 않음
- 퇴장 동작은 반응 후보에서 제외

## 9. 움직임 스타일

중국 피영극이나 그림자 인형극처럼 조금 뻣뻣하고 절제된 움직임을 사용한다.

```text
빠른 동작 2~3프레임
→ 정지 2프레임
→ 작은 반동 1프레임
→ 마지막 자세 2~3프레임
```

- 대략 6~10fps
- 주로 6~12프레임
- 정지 시간이 움직임보다 길어야 함
- 과도한 스쿼시·스트레치와 부드러운 반복 대기 애니메이션 금지
- 모든 프레임에서 발 또는 출발 기준점 유지

## 10. 최종 움직임 자산 17개

### 큰 까치 7개

```text
magpie_large_fly_pine_to_hand.agif
magpie_large_land_on_hand.agif
magpie_large_walk_step.agif
magpie_large_hop_to_tiger.agif
magpie_large_exit_right_jump.agif
magpie_large_head_tilt.agif
magpie_large_turn_perch.agif
```

- `hop_to_tiger`는 초기에는 시침→분침 환승 홉에도 재사용한다.
- 화면에서 부자연스러울 때만 별도 환승 자산을 추가한다.
- `exit_right_jump`는 날개를 접고 낮고 긴 점프로 완전히 퇴장한다.

### 작은 까치 9개

```text
magpie_small_fly_pine_to_hand.agif
magpie_small_land_on_hand.agif
magpie_small_walk_step.agif
magpie_small_hop_to_tiger.agif
magpie_small_exit_right_two_flaps.agif
magpie_small_head_scan.agif
magpie_small_look_plum.agif
magpie_small_turn_hop.agif
magpie_small_peck_tiger_ear.agif
```

- `head_scan`은 다음 목표 확인에도 재사용할 수 있다.
- `peck_tiger_ear` 안에 두 번의 쪼기 동작을 포함한다.
- `exit_right_two_flaps`는 정확히 두 번 날갯짓하고 화면 밖에서 종료한다.

### 호랑이 1개

```text
tiger_head_eye_reaction.agif
```

머리와 눈동자 레이어의 시작 시점을 어긋나게 두고 마지막 프레임에서 중립으로 복귀한다.

## 11. 정적 자세와 가림막

필수 정적 자세:

```text
magpie_large_perch_hand.png
magpie_large_walk_idle.png
magpie_large_perch_tiger.png
magpie_small_perch_hand.png
magpie_small_walk_idle.png
magpie_small_perch_tiger.png
```

필수 전경 가림막:

```text
plum_foreground_mask.png
pine_foreground_mask.png
tiger_body_foreground_mask.png
```

- 기존 `minute_magpie.png`는 큰 까치, `hour_magpie.png`는 작은 까치다.
- 큰 까치의 깨끗한 기반 마스터는 승인됐다.
- 작은 까치 기존 레이어에는 가지와 붉은 노리개가 붙어 있다.
- V2.1은 가지·붉은 노리개가 없는 깨끗한 작은 까치 마스터를 사용한다.
- 작은 까치 퇴장 날개는 몸 높이 비율로 크기를 정하고 몸과 동일한 상하 오프셋을 사용한다.

## 12. 애니메이션 원본과 메타데이터

AGIF 바이너리만 원본으로 보관하지 않는다.

```text
assets/animation_src/<asset_name>/
  frame_00.png
  frame_01.png
  ...
  metadata.json
```

`metadata.json` 필수 항목:

```text
fps
anchorX
anchorY
cropX
cropY
cropWidth
cropHeight
facing
startPose
endPose
loopCount
```

- 모든 프레임의 캔버스 크기와 기준점을 일치시킨다.
- 마지막 프레임은 대응 정적 PNG와 자연스럽게 연결한다.
- 원본 정렬 레이어는 1254×1254로 보존하고 런타임 자산만 450 좌표계에 맞춰 크롭한다.
- 완전 투명 픽셀의 RGB는 0으로 정규화한다.

## 13. 렌더링 슬롯과 앞뒤 순서

활성 슬롯은 한 시점에 정확히 하나다.

```text
GROUND
HAND
TIGER
NONE
```

기본 순서:

```text
배경
→ 지면 까치
→ 시침·분침 가지
→ 바늘 까치
→ 호랑이 머리
→ 호랑이 위 까치
→ 호랑이 눈동자
→ 전경 가림막
```

## 14. AOD와 메모리

AOD:

- 모든 AGIF 숨김
- 까치 숨김
- 호랑이 반응용 머리·눈동자 세부 레이어 숨김
- 시간 표시와 필요한 최소 윤곽만 유지
- 대화형 전환 시 잔상과 위치 점프 검증

메모리 목표:

```text
대화형 모드 60MB 이하 목표
AOD 8MB 이하 목표
```

- 압축 파일 크기가 아니라 모든 프레임의 압축 해제 크기로 계산한다.
- 전체 450×450 AGIF와 큰 투명 여백을 금지한다.
- 동일 정적 이미지는 중복 저장하지 않는다.

## 15. 자동 검증 불변조건

```text
같은 시각은 같은 결과
화면에 까치 최대 1마리
큰·작은 까치 엄격 교대
첫 2분 HIDDEN
경로·바늘·까치가 사이클 중간에 바뀌지 않음
자정에도 진행 상태 연속
모든 경로가 EXIT_RIGHT와 HIDDEN으로 종료
큰 까치 퇴장 날갯짓 0회
작은 까치 퇴장 날갯짓 정확히 2회
작은 까치 귀 쪼기 정확히 3회 중 2회
호랑이 반응 사이클당 정확히 1회
AOD에서 까치·세부 행동·반응 숨김
```

시뮬레이션 범위에는 하루 1,440분, 평년 전체, 윤년 2월 29일, 연말 자정, 장시간 화면 꺼짐 뒤 복원, 대화형↔AOD 전환을 포함한다.

## 16. V2.1 출력과 판정 기준

현재 생성된 출력:

```text
hojakdo_v21_24h_debug.gif
hojakdo_v21_large_cycle_detail.gif
hojakdo_v21_small_cycle_detail.gif
hojakdo_v21_small_ear_peck_detail.gif
hojakdo_v21_motion_comparison.png
hojakdo_v21_asset_repairs.png
route_report_30d_v21.json
```

현재 자동 테스트는 결정성·교대·한 마리·상태 연결·실제 착지 빈도·양쪽 바늘 사용·쪼기·실제 이동 방향·날개 접합·날개 비율·호랑이 턱 복원·AOD·자정 연속성을 검사한다.

정적 이미지나 미리보기 GIF만 만든 경우 `애니메이션 구현 완료`라고 보고하지 않는다.

## 17. V2.1 승인 뒤 제작 순서

1. V2.1 GIF의 구도·성격·빈도 승인
2. 17개 AGIF 원본 프레임·메타데이터 제작
3. 정적 자세 6개와 전경 가림막 3개 확정
4. 공통 무상태 결정식을 WFF 표현식으로 이식
5. Transform과 렌더링 슬롯 연결
6. AOD와 메모리 예산 검증
7. Wear OS 에뮬레이터 검증
8. 가능하면 실제 갤럭시 워치 검증

## 18. 남은 조정 항목

다음은 V2를 직접 본 뒤 조정할 수 있다.

- 시침→분침 환승 거리 90px의 실제 구도
- 두 까치 비행 높이와 퇴장 포물선
- 상체 동작의 각도와 정지 프레임 수
- 호랑이 머리·눈동자 진폭과 한 박자 간격
- AGIF별 최종 프레임 수와 fps

사이클 43분, 첫 2분 숨김, 엄격 교대, 하루 평균 약 6회, 작은 까치의 2회 날갯짓·3회 중 2회 귀 쪼기, 큰 까치의 접은 날개 점프는 승인된 핵심 규칙으로 유지한다.
