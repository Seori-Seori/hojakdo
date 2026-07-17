# 호작도 V4.1 판독성 개선 후보

승인된 V3.1 구도와 작은 까치 고정 비행을 Watch Face Format v1에 연결하고 바늘 판독성을 개선한 V4.1 제작 파이프라인이다.

## 확정된 시각값

- 논리 캔버스: 450×450
- 작은 비행 까치: 70×54, 기준점 `(46.9, 34.56)`, 날갯짓 0회
- 시침: 유효 길이 92px, 수직 두께 1.24배, 밝기 0.78배
- 분침: 유효 길이 126px, 기존 굵기·밝기 유지
- 바늘 착석점: 시침 큰/작은 `(293, 152)`·`(290, 157)`, 분침 큰/작은 `(155, 114)`·`(168, 118)`
- `鵲虎圖`·도장: 왼쪽 20px, 위 3px 이동
- 매화: 배터리 5단계 정적 교체
- 중앙 표시: 실시간 `HH:mm`, `MM.DD`, 대문자 요일
- 중앙 표시: 구형 글자·구름선 제거 후 세로 20px를 내리고 가로 중심을 `x=225`에 정렬
- 날짜 조용한 영역: 배경 복원에 더해 `(188, 272)~(270, 294)` 한지 덮개를 배경 바로 위·시침과 분침 아래에 배치
- 호랑이: 94% 몸 뒤에 남은 원래 100% 뒷다리 외곽선 제거
- 바늘: 매화·소나무·호랑이 전경과 호랑이 머리를 먼저 렌더한 뒤 시침·분침을 올려 모든 각도에서 가시성 유지
- 매화 걷기 까치: 가지와 배터리 꽃보다 위에 렌더해 만개 상태에서도 전 프레임 표시
- 호랑이 위 까치: 호랑이 머리보다 위에 렌더하고 발 기준점을 큰 까치 `(335, 233)`, 작은 까치 `(340, 241)`에 고정
- 호랑이 반응: 정적 머리·눈동자와 반응 AGIF를 같은 `Condition`에서 배타적으로 전환하고, 반응 분의 AOD에는 알파 0→복원 방식의 정적 백업 사용
- 상단 한지 여백: 고립된 솔잎 조각 `(282, 158)~(306, 181)`을 인접 종이 질감으로 복원
- 하단 표시: 실시간 배터리 아이콘과 퍼센트

## 산출물

```text
assets/layers/v4/
  drawable/       정적 자세·가림막·썸네일·WFF 이미지
  frames/         16개 애니메이션의 원본 PNG 프레임
  animations/     16개 AGIF와 개별 metadata.json
  manifest.json   전체 자산·장면·메모리 명세

prototype/hojakdo_v4/output/
  hojakdo_v4_integrated_static.png
  hojakdo_v4_readout_cleanup_review.png
  hojakdo_v4_emulator_regression_review.png
  hojakdo_v4_review_board.png
  hojakdo_v4_animation_catalog.png
  hojakdo_v4_day_00_06.gif
  hojakdo_v4_day_06_12.gif
  hojakdo_v4_day_12_18.gif
  hojakdo_v4_day_18_24.gif
  hojakdo_v4_day_review_manifest.json
```

## WFF 시간표

- 43분 사이클, 첫 2분 숨김, 큰·작은 까치 엄격 교대
- 11사이클마다 시침 경로 1회와 분침 경로 1회, 나머지는 매화 경로
- 장기 평균 바늘 착석 약 6.09회/일
- AGIF는 `ON_VISIBLE`로 한 번 재생하고 숨기며, 호랑이 반응만 중립 첫 프레임을 유지
- 긴 체류는 대응 정적 자세로 유지
- AOD에서는 AGIF와 까치를 숨기고 배경·바늘·호랑이·현재 매화 단계·실시간 표시만 감광 유지

## 생성과 검증

```bash
python -m prototype.hojakdo_v4.build_v4_assets
python -m prototype.hojakdo_v4.generate_watchface
python -m prototype.hojakdo_v4.render_day_gifs --date 2026-07-13 --battery 100
python -m unittest discover -v
./gradlew :watchface:assembleDebug
```

자동 검증은 16개 AGIF·6개 정적 자세·3개 가림막·5개 매화 단계·WFF 자원 참조·표현식 괄호·무상태 시간표·AOD 가시성·V4.1 바늘 길이비와 네 착석점·바늘 레이어·작은 까치 접촉 픽셀·호랑이 배타 반응·메모리 예산을 확인한다. 현재 저장소 전체 51개 테스트가 통과한다.

이 작업 환경에서는 Gradle 8.13 배포본과 Android SDK를 내려받을 수 없어 APK 조립과 Wear OS 에뮬레이터 검증만 남아 있다.
