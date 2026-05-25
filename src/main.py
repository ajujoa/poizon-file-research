"""Poizon File Research — 완전 파이프라인
1. 크롤링 (Playwright) → xls/ 다운로드
2. DB 적재 (load_db)
3. 사이즈 추출 (size_extractor)
4. 무신사 크롤링 (musinsa) [옵션]
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _count_xlsx_rows(filepath: str) -> int | None:
    """xlsx 파일의 필터링 후 예상 행 수"""
    import re
    import pandas as pd

    df = pd.read_excel(filepath, sheet_name=0)
    df = df[df["30-Day Average"].notna()]
    df = df[df["Total Sales"].apply(
        lambda v: bool(re.match(r"^[\d,]+\+$", str(v).strip())) if not pd.isna(v) else False
    )]
    df = df[df["Primary Category"] != "Underwear"]
    return len(df)


def main():
    print("=" * 50)
    print("  Poizon File Research Pipeline")
    print("=" * 50)

    # ── Step 1: 크롤링 ──
    print("\n[Step 1/4] 크롤링 시작...\n")
    from crawler import PoizonCrawler

    crawler = PoizonCrawler(headless=True)
    result = crawler.run()

    if not result:
        print("\n크롤링 실패 — DB 적재 건너뜀")
        return 1

    r = result[0]
    print(f"\n크롤링 완료: {r['file']}")

    # ── Step 2: DB 적재 (또는 검증) ──
    from load_db import main as load_db_main
    from db import Database

    db_status = r.get('db_status')
    if db_status and db_status['loaded']:
        print(f"\n[Step 2/4] DB 이미 적재됨 → 검증")
        print(f"  DB: SPU {db_status['spu_count']:,}개, SKU {db_status['sku_count']:,}개")
        try:
            xlsx_rows = _count_xlsx_rows(r['file'])
            if xlsx_rows:
                diff = abs(xlsx_rows - db_status['sku_count'])
                pct = diff / max(xlsx_rows, 1) * 100
                if diff <= 10 and pct <= 1.0:
                    print(f"  xlsx: {xlsx_rows:,}행 → DB: {db_status['sku_count']:,}행 (차이 {diff}건, {pct:.1f}%) ✓")
                else:
                    print(f"  xlsx: {xlsx_rows:,}행 → DB: {db_status['sku_count']:,}행 (차이 {diff}건, {pct:.1f}%) ⚠")
                    print(f"  차이가 크므로 재적재 진행")
                    ret = load_db_main()
                    if ret != 0:
                        print("DB 적재 실패")
                        return 1
        except Exception as e:
            print(f"  xlsx 검증 실패: {e} — 재적재 진행")
            ret = load_db_main()
            if ret != 0:
                return 1
    else:
        print(f"\n[Step 2/4] DB 적재 시작...\n")
        if db_status:
            print(f"  DB 상태: 미적재")
        ret = load_db_main()
        if ret != 0:
            print("DB 적재 실패")
            return 1

    # ── Step 3: 사이즈 추출 ──
    print("\n[Step 3/4] 사이즈 추출...\n")
    from size_extractor import (
        extract_kr_size, extract_apparel_size,
        clean_apparel_size, show_summary,
    )

    db = Database()

    kr_updated = extract_kr_size(db)
    print(f"  KR 사이즈 추출: {kr_updated}건")

    apparel_updated = extract_apparel_size(db)
    print(f"  의류 사이즈 추출: {apparel_updated}건")

    cleaned = clean_apparel_size(db)
    print(f"  불필요 사이즈 정리: {cleaned}건 제거")

    summary = show_summary(db)
    print(f"\n{'=' * 50}")
    print(f"  Poizon DB 현황")
    print(f"  총 SKU: {summary['total']:,}")
    print(f"  Size_KR: {summary['kr']:,}")
    print(f"  Size_Apparel: {summary['apparel']:,}")
    print(f"  미추출: {summary['neither']:,}")

    # ── Step 4: 무신사 크롤링 ──
    print(f"\n[Step 4/4] 무신사 크롤링...\n")
    from musinsa import MusinsaCrawler

    musinsa = MusinsaCrawler(headless=True)
    result = musinsa.run()

    print(f"\n{'=' * 50}")
    print(f"  전체 완료")
    print(f"  Poizon SKU: {summary['total']:,} | 무신사: {result['found']}개 발견, 재고 {result['in_stock']}개")
    print(f"{'=' * 50}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
