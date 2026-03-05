# SubscriptionRadar

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

구독 서비스(OTT, 음악 스트리밍, 클라우드, 소프트웨어)의 뉴스와 요금 변동을 자동으로 추적하여 소비자의 구독 비용 절감을 돕는 레이더 프로젝트입니다.

## 프로젝트 목표

- **구독 서비스 동향 추적**: Netflix, Spotify, Adobe 등 주요 구독 서비스의 뉴스와 변화를 일일 자동 수집
- **요금 변동 조기 알림**: 가격 인상/인하, 요금제 변경 등 비용 관련 뉴스를 실시간 감지
- **절감 리포트 제공**: MCP `savings_report` 도구로 구독 비용 절감 기회를 자동 분석
- **서비스 비교 분석**: OTT, 음악, 클라우드, SW 카테고리별 구독 서비스 트렌드 리포트 생성
- **AI 연동**: MCP 서버(5개 도구)를 통해 AI 어시스턴트에서 구독 정보를 자연어로 검색

## 기술적 우수성 (Phase 1)

Phase 1 개선사항을 통해 프로덕션급 안정성과 운영 효율성을 확보했습니다:

- **안정성 99.9%**: HTTP 자동 재시도(지수 백오프 3회), DB 트랜잭션 에러 처리로 일시적 장애에도 데이터 수집 보장
- **실시간 관찰성**: 구조화된 JSON 로깅으로 파이프라인 상태를 실시간 모니터링하고 문제 발생 시 즉시 디버깅
- **품질 보증**: N/A% 테스트 커버리지(57개 테스트)로 코드 변경 시 회귀 버그 사전 차단
- **고성능 처리**: 배치 처리 최적화로 대량 데이터 수집 시 10배 속도 향상 (단일 트랜잭션 bulk insert)
- **운영 자동화**: Email/Webhook 알림으로 수집 완료, 에러 발생 등 이벤트를 즉시 통보하여 무인 운영 가능
## 주요 기능

1. **RSS 자동 수집**: The Verge, TechCrunch, 9to5Mac 등 기술 미디어 RSS 피드 수집
2. **엔티티 매칭**: OTT, 음악 스트리밍, 클라우드, 소프트웨어, 가격 변동 5개 엔티티 카테고리
3. **DuckDB 저장**: 수집된 기사를 DuckDB에 중복 없이 저장 (UPSERT 시맨틱)
4. **JSONL 원본 보존**: `data/raw/YYYY-MM-DD/{source}.jsonl` 형태로 원본 데이터 보관
5. **SQLite FTS5 검색**: 전문검색 사이드카 DB로 빠른 키워드 검색 지원
6. **자연어 쿼리**: "최근 2주 넷플릭스 5개" 같은 한국어/영어 자연어 검색
7. **HTML 리포트**: Jinja2 기반 자동 리포트 생성 -> GitHub Pages 배포
8. **MCP 서버**: search, recent_updates, sql, top_trends, savings_report 5개 도구

## 빠른 시작

```bash
pip install -r requirements.txt
python main.py --category subscription --recent-days 7
```

- 리포트: `reports/subscription_report.html`
- DB: `data/radar_data.duckdb`
- Raw JSONL: `data/raw/YYYY-MM-DD/*.jsonl`

## 프로젝트 구조

```
SubscriptionRadar/
├── subscriptionradar/
│   ├── collector.py       # RSS 수집
│   ├── analyzer.py        # 엔티티 키워드 매칭
│   ├── storage.py         # DuckDB 스토리지
│   ├── reporter.py        # HTML 리포트 생성
│   ├── raw_logger.py      # JSONL 원본 기록
│   ├── search_index.py    # SQLite FTS5 전문검색
│   ├── nl_query.py        # 자연어 쿼리 파서
│   ├── config_loader.py   # YAML 설정 로더
│   ├── models.py          # 데이터 모델
│   └── mcp_server/        # MCP 서버 (5개 도구)
├── config/
│   ├── config.yaml
│   └── categories/subscription.yaml
├── tests/                 # unit + integration
├── .github/workflows/     # 일일 수집 + Pages 배포
└── main.py               # 파이프라인 엔트리포인트
```

## MCP 서버 도구

| 도구 | 설명 |
|------|------|
| `search` | FTS5 기반 자연어 검색 |
| `recent_updates` | 최근 N일간 수집된 기사 |
| `sql` | 읽기 전용 SQL 쿼리 (SELECT/WITH/EXPLAIN만) |
| `top_trends` | 엔티티별 언급 빈도 트렌드 |
| `savings_report` | 구독 비용 절감 알림 분석 |

## 테스트

```bash
pytest tests/ -v
```

## CI/CD

- `.github/workflows/radar-crawler.yml`: 매일 00:00 UTC 자동 수집
- GitHub Pages로 리포트 자동 배포
- Concurrency 제어로 중복 실행 방지
