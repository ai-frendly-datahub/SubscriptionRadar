# Data Quality Plan

- 생성 시각: `2026-04-11T16:05:37.910248+00:00`
- 우선순위: `P2`
- 데이터 품질 점수: `97`
- 가장 약한 축: `추적성`
- Governance: `medium`
- Primary Motion: `conversion`

## 현재 이슈

- 현재 설정상 즉시 차단 이슈 없음. 운영 지표와 freshness SLA만 명시하면 됨

## 필수 신호

- vendor pricing page와 plan change 공지
- app store ranking·review·churn proxy
- 카드 결제 카테고리와 구독료 변동 신호

## 품질 게이트

- 요금제명·청구주기·지역·통화를 별도 필드로 유지
- 가격 변경일과 적용 시작일을 분리
- 뉴스 기사와 공식 pricing page를 같은 근거로 병합하지 않음

## 다음 구현 순서

- vendor pricing page와 app store ranking source를 보강
- plan/price canonicalization rule과 변경 diff를 추가
- churn proxy와 카드 결제 카테고리 데이터를 보조 신호로 분리 평가

## 운영 규칙

- 원문 URL, 수집일, 이벤트 발생일은 별도 필드로 유지한다.
- 공식 source와 커뮤니티/시장 source를 같은 신뢰 등급으로 병합하지 않는다.
- collector가 인증키나 네트워크 제한으로 skip되면 실패를 숨기지 말고 skip 사유를 기록한다.
- 이 문서는 `scripts/build_data_quality_review.py --write-repo-plans`로 재생성한다.
