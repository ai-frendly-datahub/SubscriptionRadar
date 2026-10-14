# SubscriptionRadar - 구독 서비스 정보 레이더

**🌐 Live Report**: https://ai-frendly-datahub.github.io/SubscriptionRadar/


OTT, 음악, SaaS, AI 서비스의 요금제 변경과 청구 정책 변화를 수집하고 분석합니다.

## 프로젝트 목표

- **데이터 수집**: 테크 뉴스, 공식 가격 페이지, 벤더 공지, 커뮤니티 반응
- **엔티티 분석**: 서비스 유형별 키워드 매칭 (OTT, 음악, 클라우드 등)
- **트렌드 리포트**: DuckDB 저장 + HTML 리포트로 구독/요금제 동향 시각화
- **자동화**: GitHub Actions 일일 수집 + GitHub Pages 리포트 자동 배포

## 기술적 우수성

- **안정성**: HTTP 자동 재시도(지수 백오프), DB 트랜잭션 에러 처리
- **관찰성**: 구조화된 JSON 로깅으로 파이프라인 상태 실시간 모니터링
- **품질 보증**: 단위 테스트로 코드 변경 시 회귀 버그 사전 차단
- **고성능**: 배치 처리 최적화로 대량 데이터 수집 시 성능 향상
- **운영 자동화**: Email/Webhook 알림으로 무인 운영 가능

## 빠른 시작

1. 가상환경을 만들고 의존성을 설치합니다.
   ```bash
   pip install -r requirements.txt
   ```

2. 실행:
   ```bash
   python main.py --category subscription --recent-days 7
   # 리포트: reports/subscription_report.html
   ```

   주요 옵션: `--per-source-limit 20`, `--recent-days 5`, `--keep-days 60`, `--timeout 45`.

## 운영 계약

형제 Radar에서 확인된 실패(빈 수집을 성공으로 처리, 100MiB DuckDB 푸시 거절, `continue-on-error` 때문에 조용히 실패한 데이터 푸시)를 이 저장소에도 고정합니다. 기준은 [Radar-Template PR #4](https://github.com/ai-frendly-datahub/Radar-Template/pull/4)입니다.

1. **radar-core 핀.** `requirements.txt`와 `pyproject.toml`은 `radar-core @ git+https://github.com/ai-frendly-datahub/radar-core.git@main` 입니다.
2. **스냅샷 전에 압축.** `apply_date_storage_policy()`와 `RadarStorage.create_daily_snapshot()`은 일일 복사와 git add 전에 `radar_core.db_compact.compact_duckdb_file(database_path)`를 호출합니다. 압축이 실패해도 기존 파일을 스냅샷하고, 실행 로그에 바이트 수와 삭제된 행 수를 남깁니다. 기본 예산은 90MiB입니다.
3. **피드 클라이언트.** User-Agent는 `SubscriptionRadar/0.1` 입니다. RSS 타임아웃 기본값은 45초입니다. TLS 검증은 항상 켭니다. Cloudflare, "Just a moment", 쿠키 월, 403/404 페이지 제목은 저장하기 전에 버립니다.
4. **없는 시크릿.** 소스마다 GitHub `::warning`을 한 번 출력합니다. `data/raw/<날짜>/<소스>.skip.json`에는 환경 변수 이름만 기록합니다. 수집기는 실패하면 빈 리스트를 반환하며 샘플이나 가짜 기사를 만들지 않습니다.
5. **실패해야 하는 실행.** 활성 소스가 있는데 수집 건수가 0이면 프로세스가 종료 코드 1로 끝납니다. 출력이 0바이트이거나 DuckDB가 100MiB 이상이면 워크플로가 실패합니다. 데이터 auto-commit/push에는 `continue-on-error`가 없습니다.
6. **Pages는 푸시 성공 후에만.** `gh-pages` 배포는 auto-commit 단계의 `outcome == success`일 때만 실행됩니다.
7. **테스트.** 날짜 단정은 `tests/reference_dates.py`의 기준 시각(2026-03-13 12:00 UTC)과 `tests/fixtures/`를 사용합니다. 커버리지 설정은 `relative_files = true`입니다.

일일 DuckDB 스냅샷은 Git LFS로 올리지 않습니다. LFS 예산이 소진되면 데이터 푸시가 거절됩니다. 압축된 파일은 일반 git blob으로 커밋합니다.

## 소스 전략

- `공식`: Netflix, Spotify, Apple, Notion, Basecamp, Adobe의 가격/플랜 페이지
- `운영`: 한국 OTT 공지사항과 billing/renewal/plan change notice
- `시장`: 테크/구독경제 전문 미디어
- `커뮤니티`: Reddit 기반 해지, 대체재, 체감 가격 반응

JavaScript/browser 소스를 제대로 수집하려면 `pip install 'radar-core[browser]'`가 필요합니다.

## GitHub Actions & GitHub Pages

- 워크플로: `.github/workflows/radar-crawler.yml`
  - 스케줄: 매일 00:00 UTC (KST 09:00), 수동 실행도 지원.
  - 환경 변수 `RADAR_CATEGORY` 값은 `subscription`입니다.
  - 수집 타임아웃은 45초입니다.
  - 리포트 배포 디렉터리: `reports` → `gh-pages` 브랜치. 데이터 푸시가 성공한 뒤에만 배포합니다.
  - DuckDB 경로: `data/radar_data.duckdb` (Pages에 올라가지 않음). 커밋 전 90MiB 예산으로 압축하고, 100MiB 이상이면 작업을 실패시킵니다. 아티팩트로 30일 보관.

- 설정 방법:
  1) 저장소 Settings → Pages에서 `gh-pages` 브랜치를 선택해 활성화
  2) Actions 권한을 기본값으로 두거나 외부 PR에서도 실행되도록 설정
  3) 워크플로 파일의 `RADAR_CATEGORY`가 `subscription`인지 확인

## 동작 방식

- **수집**: 카테고리 YAML에 정의된 소스를 수집합니다. 실행 시 DuckDB에 적재하고 보존 기간(`keep_days`)을 적용합니다.
- **분석**: 엔티티별 키워드 매칭. 매칭된 키워드를 리포트에 칩으로 표시합니다.
- **리포트**: `reports/<category>_report.html`을 생성하며, 최근 N일(기본 7일) 기사와 엔티티 히트 카운트, 수집 오류를 표시합니다.

## 기본 경로

- DB: `data/radar_data.duckdb`
- 리포트 출력: `reports/`

## 디렉터리 구성

```
SubscriptionRadar/
  main.py                 # CLI 엔트리포인트
  requirements.txt        # 의존성
  config/
    config.yaml           # DB/리포트 경로 설정
    categories/
      subscription.yaml  # 소스 + 엔티티 정의
  subscriptionradar/
    collector.py          # 데이터 수집
    analyzer.py           # 엔티티 태깅
    reporter.py           # HTML 렌더링
    storage.py            # DuckDB 저장/정리
    config_loader.py      # YAML 로더
    models.py             # 데이터 클래스
  .github/workflows/      # GitHub Actions (crawler + Pages 배포)
```

<!-- DATAHUB-OPS-AUDIT:START -->
## DataHub Operations

- CI/CD workflows: `pr-checks.yml`, `radar-crawler.yml`, `release.yml`.
- GitHub Pages visualization: `reports/index.html` (valid HTML); https://ai-frendly-datahub.github.io/SubscriptionRadar/.
- Latest remote Pages check: HTTP 200, HTML.
- Local workspace audit: 56 Python files parsed, 0 syntax errors.
- Re-run audit from the workspace root: `python scripts/audit_ci_pages_readme.py --syntax-check --write`.
- Latest audit report: `_workspace/2026-04-14_github_ci_pages_readme_audit.md`.
- Latest Pages URL report: `_workspace/2026-04-14_github_pages_url_check.md`.
<!-- DATAHUB-OPS-AUDIT:END -->
