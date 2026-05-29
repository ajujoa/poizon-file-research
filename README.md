# Poizon File Research

Poizon(得物) + Musinsa 크로스보더 리서치 자동화 파이프라인.

## 개요

- **Poizon 크롤링**: Poizon Seller에서 브랜드별 상품 xlsx Export → DB 적재
- **무신사 매칭**: style_id로 무신사 검색 → 상품/가격/재고 매핑
- **Pick 필터링**: `musinsa_price < cn_lowest * 0.85` 조건으로 수익성 높은 상품 선별
- **가격/재고 모니터링**: 교집합 상품의 cn_lowest, musinsa price, in_stock 변경 실시간 감지
- **대시보드**: Pick 결과 HTML 대시보드 (nginx 서빙)

## 3pc 서버

| 항목 | 값 |
|------|-----|
| SSH | `ssh mh@3pc` |
| Tailscale IP | `100.119.217.109` |
| 프로젝트 경로 | `/home/mh/projects/poizon_file_research` |
| GitHub | `ajujoa/poizon-file-research` |

## Docker 컨테이너

```
poizon_file_research-app-1       orchestrator (매일 07:00 파이프라인, GitHub 폴링)
poizon_file_research-monitor-1   price_monitor (30분 간격 가격/재고 변경 감지)
poizon_file_research-mariadb-1   MariaDB 10.11 (poizon_research DB)
poizon_file_research-nginx-1     nginx (대시보드 서빙, :8080)
```

## 파이프라인

### 데일리 (app 컨테이너, 매일 07:00)

```
main.py (크롤링→DB적재→사이즈추출→무신사검색)
  → 10초 sleep
  → musinsa_pick.py (Pick 필터링)
  → generate_dashboard.py (대시보드 생성)
```

### 실시간 (monitor 컨테이너, 30분 간격)

```
price_monitor.py: poizon+musinsa 교집합 1,000건
  → cn_lowest / musinsa_price / in_stock 변경 감지
  → 변경 시 로그 출력 + price_snapshot 저장
```

### GitHub 폴링 (5분 간격)

```
origin/main 변경 감지 → git pull → 컨테이너 재시작
```

## 파일 구조

```
poizon_file_research/
├── Dockerfile              # Playwright Python v1.60.0 + 의존성
├── docker-compose.yml      # mariadb + app + monitor + nginx
├── orchestrator.py         # 데일리 스케줄러 + GitHub 폴링
├── docker/
│   ├── init.sql            # DB 스키마 (7개 테이블)
│   └── nginx.conf          # nginx 정적 파일 서빙
├── config/
│   ├── poizon_config.ini   # 크롤링/스케줄/모니터 설정
│   └── dbconfig.ini        # DB 접속 정보 (host=mariadb)
└── src/
    ├── main.py             # 전체 파이프라인 진입점
    ├── crawler.py          # Poizon xlsx Export (Playwright)
    ├── load_db.py          # xlsx → DB 적재
    ├── size_extractor.py   # Size_KR / Size_Apparel 추출
    ├── musinsa.py          # 무신사 검색 + 가격/재고 수집 (Playwright)
    ├── musinsa_pick.py     # Pick 필터링 (poizon_sku+musinsa 직접 조인)
    ├── price_monitor.py    # 가격/재고 변경 감지 모니터
    ├── generate_dashboard.py  # HTML 대시보드 생성
    ├── dashboard_template.html # 대시보드 템플릿 (다크 테마)
    ├── db.py               # DB 연결 헬퍼
    └── proxy_cred.py       # Bright Data 프록시 URL 빌더
```

## DB 스키마

| 테이블 | 설명 |
|--------|------|
| poizon_spu | Poizon 상품 기본 정보 (SPU ID, style_id, 브랜드 등) |
| poizon_sku | 사이즈별 가격/판매량 (cn_lowest, est_payout, total_sales 등) |
| poizon_spu_snapshot | 날짜별 SPU 스냅샷 |
| poizon_sku_snapshot | 날짜별 SKU 스냅샷 |
| musinsa | 무신사 매핑 정보 (goods_no, price, in_stock, sizes) |
| price_snapshot | 가격 비교 스냅샷 (모니터링 기준값) |
| pick_snapshot | Pick 선별 결과 (musinsa_price < cn_lowest * 0.85) |

## 대시보드

- **URL**: `http://100.119.217.109:8080/` (Tailscale 네트워크 내)
- Poizon 링크: `https://kr.poizon.com/search?keyword={style_id}&track_referer_source=m1`
- Musinsa 링크: `https://www.musinsa.com/products/{goods_no}`

## 설정

### poizon_config.ini

```ini
[Schedule]
crawl_hour = 7           # 매일 크롤링 시간
crawl_minute = 0
github_poll_interval = 300  # GitHub 폴링 간격 (초)

[Monitor]
check_interval = 30      # 가격/재고 체크 간격 (분)

[Musinsa]
workers = 4              # 동시 worker 수
cn_lowest_min = 50000    # CN 최저가 최소 금액

[Crawl]
recency = today          # today / 1hour / 4hour / 0(무조건 새로)
```

## 운영 명령어

```bash
# 3pc 접속
ssh mh@3pc

# 컨테이너 상태
cd /home/mh/projects/poizon_file_research && docker compose ps

# 로그 확인
docker compose logs app --tail 30
docker compose logs monitor --tail 30

# 수동 파이프라인 실행
docker exec poizon_file_research-app-1 python /app/src/main.py
docker exec poizon_file_research-app-1 python /app/src/musinsa_pick.py
docker exec poizon_file_research-app-1 python /app/src/generate_dashboard.py

# DB 조회
docker exec poizon_file_research-mariadb-1 mysql -u naver -pnaver1234 poizon_research

# 재시작
docker compose up -d --build
```
