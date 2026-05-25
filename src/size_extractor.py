"""사이즈 추출: size_spec 컬럼에서 KR 사이즈와 의류 사이즈 분리"""
import re
from db import Database


KR_PATTERN = re.compile(r"KR\s+(\d+)", re.IGNORECASE)
APPAREL_PATTERN = re.compile(r"SIZE\s+([A-Z0-9]+)")

APPAREL_CATEGORIES = (
    "Apparel", "Women's Apparel", "Kids' Apparel",
)
UNDERWEAR_CATEGORY = "Underwear"


def extract_kr_size(db: Database):
    """size_spec에서 KR 사이즈 숫자를 추출하여 Size_KR 컬럼에 저장"""
    with db as conn:
        cur = conn.cursor()

        # 컬럼 추가 (없으면)
        cur.execute("""
            SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = 'poizon_research'
              AND TABLE_NAME = 'poizon_sku'
              AND COLUMN_NAME = 'Size_KR'
        """)
        if cur.fetchone()["cnt"] == 0:
            cur.execute("ALTER TABLE poizon_sku ADD COLUMN Size_KR varchar(10) DEFAULT NULL AFTER size_spec")
            conn.commit()

        # KR 사이즈 추출
        rows = cur.execute("SELECT sku_id, size_spec FROM poizon_sku WHERE size_spec REGEXP '(?i)KR[[:space:]]+[0-9]+'")
        rows = cur.fetchall()
        updates = 0
        for row in rows:
            m = KR_PATTERN.search(row["size_spec"])
            if m:
                cur.execute("UPDATE poizon_sku SET Size_KR = %s WHERE sku_id = %s", (m.group(1), row["sku_id"]))
                updates += 1
        conn.commit()
        return updates


def extract_apparel_size(db: Database):
    """의류 카테고리에서 SIZE XL 등 사이즈를 추출하여 Size_Apparel 컬럼에 저장"""
    with db as conn:
        cur = conn.cursor()

        # 컬럼 추가 (없으면)
        cur.execute("""
            SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = 'poizon_research'
              AND TABLE_NAME = 'poizon_sku'
              AND COLUMN_NAME = 'Size_Apparel'
        """)
        if cur.fetchone()["cnt"] == 0:
            cur.execute("ALTER TABLE poizon_sku ADD COLUMN Size_Apparel varchar(10) DEFAULT NULL AFTER Size_KR")
            conn.commit()

        # 의류 카테고리 SPU ID 목록
        placeholders = ",".join(["%s"] * len(APPAREL_CATEGORIES))
        cur.execute(f"SELECT spu_id FROM poizon_spu WHERE primary_cat IN ({placeholders})", APPAREL_CATEGORIES)
        apparel_spu_ids = [r["spu_id"] for r in cur.fetchall()]

        if not apparel_spu_ids:
            return 0

        # SIZE 패턴이 있는 행 조회
        placeholders = ",".join(["%s"] * len(apparel_spu_ids))
        cur.execute(f"""
            SELECT sku_id, size_spec FROM poizon_sku
            WHERE spu_id IN ({placeholders})
              AND size_spec REGEXP 'SIZE[[:space:]]+[A-Z0-9]+'
        """, apparel_spu_ids)
        rows = cur.fetchall()

        updates = 0
        for row in rows:
            m = APPAREL_PATTERN.search(row["size_spec"])
            if m:
                cur.execute("UPDATE poizon_sku SET Size_Apparel = %s WHERE sku_id = %s", (m.group(1), row["sku_id"]))
                updates += 1
        conn.commit()
        return updates


def clean_apparel_size(db: Database):
    """불필요한 의류 사이즈 삭제: Underwear 카테고리, A/프리픽스"""
    with db as conn:
        cur = conn.cursor()
        deleted = 0

        # Underwear 카테고리 초기화
        cur.execute("SELECT spu_id FROM poizon_spu WHERE primary_cat = %s", (UNDERWEAR_CATEGORY,))
        undie_ids = [r["spu_id"] for r in cur.fetchall()]
        if undie_ids:
            placeholders = ",".join(["%s"] * len(undie_ids))
            cur.execute(f"SELECT COUNT(*) AS cnt FROM poizon_sku WHERE spu_id IN ({placeholders}) AND Size_Apparel IS NOT NULL", undie_ids)
            cnt = cur.fetchone()["cnt"]
            cur.execute(f"UPDATE poizon_sku SET Size_Apparel = NULL WHERE spu_id IN ({placeholders})", undie_ids)
            deleted += cnt

        # A/프리픽스 삭제
        cur.execute("SELECT COUNT(*) AS cnt FROM poizon_sku WHERE Size_Apparel = 'A'")
        cnt = cur.fetchone()["cnt"]
        cur.execute("UPDATE poizon_sku SET Size_Apparel = NULL WHERE Size_Apparel = 'A'")
        deleted += cnt

        conn.commit()
        return deleted


def show_summary(db: Database):
    """사이즈 컬럼 현황 출력"""
    with db as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN Size_KR IS NOT NULL THEN 1 ELSE 0 END) AS kr,
                SUM(CASE WHEN Size_Apparel IS NOT NULL THEN 1 ELSE 0 END) AS apparel,
                SUM(CASE WHEN Size_KR IS NULL AND Size_Apparel IS NULL THEN 1 ELSE 0 END) AS neither
            FROM poizon_sku
        """)
        return cur.fetchone()


def show_no_size_samples(db: Database, limit=5):
    """사이즈가 전혀 없는 상품 샘플 반환"""
    with db as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.sku_id, s.spu_id, sp.item_name, sp.primary_cat, s.size_spec
            FROM poizon_sku s
            JOIN poizon_spu sp ON s.spu_id = sp.spu_id
            WHERE s.Size_KR IS NULL AND s.Size_Apparel IS NULL
            LIMIT %s
        """, (limit,))
        return cur.fetchall()
