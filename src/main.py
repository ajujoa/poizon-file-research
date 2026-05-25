"""Poizon File Research — 완전 파이프라인
1. 크롤링 (Playwright) → xls/ 다운로드
2. DB 적재 (load_db)
3. 사이즈 추출 (size_extractor)
"""
import sys
import os

# 프로젝트 루트를 path에 추가 (src 내부 import 용)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    print("=" * 50)
    print("  Poizon File Research Pipeline")
    print("=" * 50)

    # ── Step 1: 크롤링 ──
    print("\n[Step 1/3] 크롤링 시작...\n")
    from crawler import PoizonCrawler

    crawler = PoizonCrawler(headless=True)
    result = crawler.run()

    if not result:
        print("\n크롤링 실패 — DB 적재 건너뜀")
        return 1

    print(f"\n크롤링 완료: {len(result)}개 파일 다운로드")

    # ── Step 2: DB 적재 ──
    print("\n[Step 2/3] DB 적재 시작...\n")
    from load_db import main as load_db_main

    ret = load_db_main()
    if ret != 0:
        print("DB 적재 실패")
        return 1

    # ── Step 3: 사이즈 추출 ──
    print("\n[Step 3/3] 사이즈 추출...\n")
    from db import Database
    from size_extractor import (
        extract_kr_size,
        extract_apparel_size,
        clean_apparel_size,
        show_summary,
    )

    db = Database()

    kr_updated = extract_kr_size(db)
    print(f"  KR 사이즈 추출: {kr_updated}건")

    apparel_updated = extract_apparel_size(db)
    print(f"  의류 사이즈 추출: {apparel_updated}건")

    cleaned = clean_apparel_size(db)
    print(f"  불필요 사이즈 정리: {cleaned}건 제거")

    # ── 현황 ──
    summary = show_summary(db)
    print(f"\n{'=' * 50}")
    print(f"  최종 현황")
    print(f"  총 SKU: {summary['total']:,}")
    print(f"  Size_KR: {summary['kr']:,}")
    print(f"  Size_Apparel: {summary['apparel']:,}")
    print(f"  미추출: {summary['neither']:,}")
    print(f"{'=' * 50}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
