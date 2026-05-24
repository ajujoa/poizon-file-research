"""최신 엑셀 파일 → DB 적재 (스냅샷 + 최신 유지)"""
import pandas as pd
import pymysql
import re
import sys
import configparser
import os
from datetime import datetime

# --- 경로 ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLS_DIR = os.path.join(BASE_DIR, "xls")
DB_CONFIG = os.path.join(BASE_DIR, "config", "dbconfig.ini")

# --- 제거 대상 컬럼 ---
DROP_COLS = [
    "Secondary Category",
    "Tertiary Category",
    "Listing Eligibility: 1: Eligible; 2. Not Eligible",
    "Barcode/UPC",
    "Sales by Local Sellers",
    "SKU Source",
    "Seller SKU ID",
]


def find_latest_file() -> tuple[str, str]:
    """xls/ 폴더에서 Export item search resultsYYYYMMDD.xlsx 중 최신 파일 찾기.
    Returns: (파일경로, 날짜문자열 YYYY-MM-DD)
    """
    pattern = re.compile(r"Export item search results(\d{8})\.xlsx$")
    latest_date = None
    latest_path = None

    for f in os.listdir(XLS_DIR):
        m = pattern.match(f)
        if m:
            dt = datetime.strptime(m.group(1), "%Y%m%d")
            if latest_date is None or dt > latest_date:
                latest_date = dt
                latest_path = os.path.join(XLS_DIR, f)

    if latest_path is None:
        raise FileNotFoundError(f"{XLS_DIR}에서 날짜 패턴의 xlsx 파일을 찾을 수 없음")

    date_str = latest_date.strftime("%Y-%m-%d")
    return latest_path, date_str


def parse_price(val) -> int | None:
    """'KRW85,000' → 85000"""
    if pd.isna(val):
        return None
    s = str(val).replace("KRW", "").replace(",", "").strip()
    try:
        return int(s)
    except ValueError:
        return None


def parse_sales(val) -> int | None:
    """'1,500+' → 1500"""
    if pd.isna(val):
        return None
    s = str(val).replace(",", "").replace("+", "").strip()
    try:
        return int(s)
    except ValueError:
        return None


def is_number_plus(val) -> bool:
    """Total Sales가 '숫자+' 형태인지"""
    if pd.isna(val):
        return False
    return bool(re.match(r"^[\d,]+\+$", str(val).strip()))


def is_a_prefix(val) -> bool:
    """Size/Spec/Color가 A/ 로 시작하는지"""
    if pd.isna(val):
        return False
    return str(val).strip().startswith("A/")


def load_db_config() -> dict:
    cfg = configparser.ConfigParser()
    cfg.read(DB_CONFIG)
    db = cfg["database"]
    return {
        "host": db["host"],
        "port": int(db["port"]),
        "user": db["user"],
        "password": db["password"],
        "database": db["database"],
        "charset": db["charset"],
    }


def main():
    # --- 1. 최신 파일 찾기 ---
    xlsx_path, load_date = find_latest_file()
    file_name = os.path.basename(xlsx_path)
    print(f"[1] 최신 파일: {file_name} (load_date={load_date})")

    # --- 2. 엑셀 로드 ---
    df = pd.read_excel(xlsx_path, sheet_name=0)
    print(f"    원본: {len(df)} rows")

    # --- 3. 필터 적용 ---
    # (a) 30-Day Average null
    before = len(df)
    df = df[df["30-Day Average"].notna()]
    print(f"    [a] 30-Day Average null 제거: {before} → {len(df)} (-{before - len(df)})")

    # (b) Total Sales "숫자+" 필터
    before = len(df)
    df = df[df["Total Sales"].apply(is_number_plus)]
    print(f"    [b] Total Sales '숫자+' 필터: {before} → {len(df)} (-{before - len(df)})")

    # (c) Underwear 제외
    before = len(df)
    df = df[df["Primary Category"] != "Underwear"]
    print(f"    [c] Underwear 제외: {before} → {len(df)} (-{before - len(df)})")

    # (d) A/ 프리픽스 제외
    before = len(df)
    df = df[~df["Size/Spec/Color"].apply(is_a_prefix)]
    print(f"    [d] A/ 프리픽스 제외: {before} → {len(df)} (-{before - len(df)})")

    # (e) 불필요 컬럼 제거
    existing_drop = [c for c in DROP_COLS if c in df.columns]
    df = df.drop(columns=existing_drop)
    print(f"    [e] 컬럼 제거 ({len(existing_drop)}개): {len(df.columns)} cols 남음")

    # --- 4. 가격/판매량 변환 ---
    df["avg_30_day_int"] = df["30-Day Average"].apply(parse_price)
    df["cn_lowest_int"] = df["CN Lowest"].apply(parse_price)
    df["est_payout_int"] = df["Est. payout:"].apply(parse_price)
    df["total_sales_int"] = df["Total Sales"].apply(parse_sales)

    # NaN → None
    df = df.replace({float("nan"): None, pd.NA: None})
    df = df.astype(object).where(pd.notna(df), None)

    # --- 5. DB 연결 ---
    db_cfg = load_db_config()
    conn = pymysql.connect(**db_cfg)
    cursor = conn.cursor()

    # --- 6. 기존 데이터 → 스냅샷 복사 (load_date 포함) ---
    cursor.execute(
        f"INSERT IGNORE INTO poizon_sku_snapshot "
        f"SELECT NULL, sku_id, spu_id, size_spec, Size_KR, Size_Apparel, "
        f"sku_image, listing_status, avg_30_day, cn_lowest, est_payout, "
        f"total_sales, file_name, '{load_date}', created_at "
        f"FROM poizon_sku"
    )
    sku_snapped = cursor.rowcount
    print(f"    poizon_sku → snapshot: {sku_snapped} rows")

    cursor.execute(
        f"INSERT IGNORE INTO poizon_spu_snapshot "
        f"SELECT NULL, spu_id, style_id, item_name, brand, primary_cat, "
        f"spu_image, file_name, '{load_date}', created_at "
        f"FROM poizon_spu"
    )
    spu_snapped = cursor.rowcount
    print(f"    poizon_spu → snapshot: {spu_snapped} rows")

    # --- 7. 메인 테이블 초기화 ---
    cursor.execute("DELETE FROM poizon_sku")
    cursor.execute("DELETE FROM poizon_spu")
    print("    메인 테이블 초기화 완료")

    # --- 8. SPU 적재 ---
    spu_cols = ["SPU ID", "Style ID", "Item Name", "Brand", "Primary Category", "SPU Image"]
    spu_df = df[spu_cols].drop_duplicates(subset=["SPU ID"])

    spu_sql = """
        INSERT INTO poizon_spu (spu_id, style_id, item_name, brand, primary_cat, spu_image, file_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    spu_data = [
        (
            int(row["SPU ID"]),
            str(row["Style ID"]),
            str(row["Item Name"]),
            str(row["Brand"]),
            str(row["Primary Category"]),
            str(row["SPU Image"]),
            file_name,
        )
        for _, row in spu_df.iterrows()
    ]
    cursor.executemany(spu_sql, spu_data)
    print(f"    poizon_spu: {len(spu_data)} rows inserted")

    # --- 9. SKU 적재 ---
    sku_sql = """
        INSERT INTO poizon_sku
            (sku_id, spu_id, size_spec, sku_image, listing_status,
             avg_30_day, cn_lowest, est_payout, total_sales, file_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    sku_data = [
        (
            int(row["SKU ID"]),
            int(row["SPU ID"]),
            str(row["Size/Spec/Color"]),
            str(row["SKU Image"]),
            int(row["Listing Status: 0: Not Listed; 1: Listed"]),
            row["avg_30_day_int"],
            row["cn_lowest_int"],
            row["est_payout_int"],
            row["total_sales_int"],
            file_name,
        )
        for _, row in df.iterrows()
    ]
    cursor.executemany(sku_sql, sku_data)
    print(f"    poizon_sku: {len(sku_data)} rows inserted")

    conn.commit()

    # --- 10. 검증 ---
    cursor.execute("SELECT COUNT(*) FROM poizon_spu")
    spu_cnt = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM poizon_sku")
    sku_cnt = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT load_date) FROM poizon_sku_snapshot")
    snap_dates = cursor.fetchone()[0]

    print(f"\n{'='*50}")
    print(f"  최종: SPU {spu_cnt}개, SKU {sku_cnt}개")
    print(f"  스냅샷 날짜 수: {snap_dates}일")
    print(f"  로드 파일: {file_name} ({load_date})")

    # 날짜별 조회 예시
    cursor.execute("""
        SELECT load_date, COUNT(*) as cnt
        FROM poizon_sku_snapshot
        GROUP BY load_date
        ORDER BY load_date DESC
        LIMIT 5
    """)
    print(f"\n  --- 스냅샷 날짜별 SKU 수 ---")
    for row in cursor.fetchall():
        print(f"    {row[0]}: {row[1]:,}개")

    cursor.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
