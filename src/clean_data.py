"""데이터 정제: 조건 필터링 및 컬럼 제거"""
import pandas as pd
import re
import sys

PATH = "xls/Export item search results20260524.xlsx"

# 삭제 대상 컬럼
DROP_COLS = [
    "Secondary Category",
    "Tertiary Category",
    "Listing Eligibility: 1: Eligible; 2. Not Eligible",
    "Barcode/UPC",
    "Sales by Local Sellers",
    "SKU Source",
    "Seller SKU ID",
]

def is_number_plus(val: str) -> bool:
    """'1,500+', '100+' 등의 패턴 체크"""
    if pd.isna(val):
        return False
    return bool(re.match(r'^[\d,]+(\+|\+)$', str(val).strip())) or \
           bool(re.match(r'^[\d,]+\+$', str(val).strip()))

def main():
    df = pd.read_excel(PATH, sheet_name=0)
    total_before = len(df)
    print(f"정제 전: {total_before} rows x {len(df.columns)} cols")

    # --- Total Sales 패턴 분석 ---
    print("\n=== Total Sales unique 값 샘플 (상위 30) ===")
    ts = df["Total Sales"].value_counts().head(30)
    for val, cnt in ts.items():
        ok = is_number_plus(val)
        print(f"  [{'+' if ok else 'x'}] '{val}' → {cnt}건")

    # --- 1) 30-Day Average null 제거 ---
    before = len(df)
    df = df[df["30-Day Average"].notna()]
    print(f"\n[1] 30-Day Average null 제거: {before} → {len(df)} (-{before - len(df)})")

    # --- 2) Total Sales 패턴 필터 ---
    before = len(df)
    df = df[df["Total Sales"].apply(is_number_plus)]
    print(f"[2] Total Sales '숫자+' 필터: {before} → {len(df)} (-{before - len(df)})")

    # --- 3) 컬럼 제거 ---
    existing_drop = [c for c in DROP_COLS if c in df.columns]
    df = df.drop(columns=existing_drop)
    print(f"[3] 컬럼 제거 ({len(existing_drop)}개): {len(df.columns)} cols 남음")

    print(f"\n정제 후: {len(df)} rows x {len(df.columns)} cols")
    print(f"총 제거: {total_before - len(df)} rows ({(total_before - len(df)) / total_before * 100:.1f}%)")

    # 남은 컬럼
    print("\n=== 남은 컬럼 ===")
    for i, col in enumerate(df.columns):
        print(f"  [{i}] {col}")

    # 브랜드/카테고리 분포
    print("\n=== 브랜드 분포 ===")
    print(df["Brand"].value_counts().to_string())

    print("\n=== Primary Category 분포 ===")
    print(df["Primary Category"].value_counts().to_string())

    return 0

if __name__ == "__main__":
    sys.exit(main())
