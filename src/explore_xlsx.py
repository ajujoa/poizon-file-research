"""Poizon 엑셀 파일 분석 - 초기 탐색"""
import pandas as pd
import sys

PATH = "xls/Export item search results20260524.xlsx"

def main():
    xls = pd.ExcelFile(PATH)
    print("=== Sheet names ===")
    print(xls.sheet_names)

    df = pd.read_excel(PATH, sheet_name=0)
    print(f"\n=== Shape: {df.shape} (rows x cols) ===")
    print(f"\n=== Column names ===")
    for i, col in enumerate(df.columns):
        print(f"  [{i}] {col}")

    print(f"\n=== Dtypes ===")
    print(df.dtypes.to_string())

    print(f"\n=== First 3 rows ===")
    for i in range(min(3, len(df))):
        print(f"\n--- Row {i} ---")
        for col in df.columns:
            val = df.iloc[i][col]
            print(f"  {col}: {val}")

    # Null / unique stats
    print(f"\n=== Null counts ===")
    print(df.isnull().sum().to_string())

    print(f"\n=== Unique counts (top 10 cols) ===")
    for col in df.columns[:10]:
        print(f"  {col}: {df[col].nunique()} unique / {df[col].count()} non-null")

    return 0

if __name__ == "__main__":
    sys.exit(main())
