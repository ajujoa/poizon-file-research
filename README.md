# Poizon File Research

Poizon(중고거래 플랫폼) 데이터 수집 및 리서치 도구

## 개요

- **Poizon API 크롤링**: 상품 정보, 가격 데이터, 거래 내역 수집
- **데이터 저장**: MariaDB 기반 데이터 적재
- **리서치/분석**: 수집된 데이터 분석 및 인사이트 도출

## 기술 스택

- Python 3.12+
- uv (패키지 관리)
- MariaDB
- requests, pandas, numpy

## 시작하기

```bash
# 의존성 설치
uv sync

# 실행
uv run python src/main.py
```

## 프로젝트 구조

```
poizon_file_research/
├── src/
│   ├── main.py       # 진입점
│   ├── crawler.py    # Poizon API 크롤러
│   └── db.py         # DB 연결 관리
├── config/
│   └── settings.ini  # 설정 파일
├── pyproject.toml
└── README.md
```
