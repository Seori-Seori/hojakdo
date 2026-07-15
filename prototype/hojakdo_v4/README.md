# 호작도 V4 프로덕션 후보

승인된 V3.1 구도와 작은 까치 고정 비행을 Watch Face Format v1에 연결한 V4 제작 파이프라인이다.

## 확정된 시각값

- 논리 캔버스: 450×450
- 작은 비행 까치: 100×78, 기준점 `(67.0, 49.92)`, 날갯짓 0회
- 시침: 길이·피벗·착지점 유지, 수직 두께 1.24배, 밝기 0.88배
- `鵲虎圖`·도장: 왼쪽 20px, 위 3px 이동
- 매화: 배터리 5단계 정적 교체
- 중앙 표시: 실시간 `HH:mm`, `MM.DD`, 대문자 요일
- 중앙 표시: 구형 글자·구름선 제거 후 기준점을 `(-12px, +20px)` 이동해 회전 바늘과 분리
- 날짜 조용한 영역: `(198, 250)~(252, 300)`의 옅은 구름 잔상까지 종이 질감으로 복원
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
  hojakdo_v4_review_board.png
  hojakdo_v4_animation_catalog.png
```

## WFF 시간표

- 43분 사이클, 첫 2분 숨김, 큰·작은 까치 엄격 교대
- 11사이클마다 시침 경로 1회와 분침 경로 1회, 나머지는 매화 경로
- 장기 평균 바늘 착석 약 6.09회/일
- AGIF는 `ON_VISIBLE`로 한 번 재생하고 마지막에 숨김
- 긴 체류는 대응 정적 자세로 유지
- AOD에서는 AGIF와 까치를 숨기고 배경·바늘·호랑이·현재 매화 단계·실시간 표시만 감광 유지

## 생성과 검증

```bash
python -m prototype.hojakdo_v4.build_v4_assets
python -m prototype.hojakdo_v4.generate_watchface
python -m unittest discover -v
./gradlew :watchface:assembleDebug
```

자동 검증은 16개 AGIF·6개 정적 자세·3개 가림막·5개 매화 단계·WFF 자원 참조·표현식 괄호·무상태 시간표·AOD 가시성·메모리 예산을 확인한다. 현재 저장소 전체 49개 테스트가 통과한다.

이 작업 환경에서는 Gradle 8.13 배포본과 Android SDK를 내려받을 수 없어 APK 조립과 Wear OS 에뮬레이터 검증만 남아 있다.
