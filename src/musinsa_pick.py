#!/usr/bin/env python3
"""
무신사 가격 경쟁력 Pick — musinsa_price < cn_lowest * 0.85 조건 필터링

poizon_sku + musinsa 직접 조인 (price_snapshot 의존 제거).
style_id + Size_KR 기준으로 매칭하여 pick_snapshot에 저장.

Usage:
  python src/musinsa_pick.py              # 전체 pick
  python src/musinsa_pick.py --dry-run     # DB 저장 없이 출력만
"""
import configparser
import logging
import sys
from pathlib import Path

import pymysql

PROJECT_ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("musinsa_pick")


def get_db():
    cfg = configparser.ConfigParser()
    cfg.read(str(PROJECT_ROOT / "config" / "dbconfig.ini"))
    db = cfg["database"]
    return pymysql.connect(
        host=db["host"], port=int(db["port"]),
        user=db["user"], password=db["password"],
        database=db["database"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def pick_products(conn, dry_run=False):
    """poizon_sku + musinsa 직접 조인 → 조건 만족 상품 pick_snapshot에 저장"""
    cur = conn.cursor()

    # 조건: musinsa_price < cn_lowest * 0.85, 재고 있음, Size_KR 있음
    sql = """
        INSERT INTO pick_snapshot (
            spu_id, style_id, brand, item_name, size_kr,
            poizon_est_payout, poizon_cn_lowest, poizon_avg_30_day,
            poizon_total_sales,
            musinsa_price, musinsa_goods_no, musinsa_in_stock,
            margin, margin_pct, cn_margin, cn_margin_pct,
            pick_reason
        )
        SELECT
            p.spu_id,
            CAST(p.style_id AS CHAR) AS style_id,
            p.brand,
            p.item_name,
            s.Size_KR,
            s.est_payout,
            s.cn_lowest,
            s.avg_30_day,
            s.total_sales,
            m.price,
            m.goods_no,
            m.in_stock,
            (m.price - s.est_payout) AS margin,
            ROUND((m.price - s.est_payout) / NULLIF(s.est_payout, 0) * 100, 1) AS margin_pct,
            (m.price - s.cn_lowest) AS cn_margin,
            ROUND((m.price - s.cn_lowest) / NULLIF(s.cn_lowest, 0) * 100, 1) AS cn_margin_pct,
            CONCAT('musinsa(', m.price, ') < cn_lowest(', s.cn_lowest,
                   ') * 0.85 = ', ROUND(s.cn_lowest * 0.85),
                   ' (수수료 15% 감안)') AS pick_reason
        FROM poizon_spu p
        JOIN poizon_sku s ON p.spu_id = s.spu_id
        JOIN musinsa m ON
            CAST(p.style_id AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci
            = CAST(m.style_id AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci
        WHERE m.price IS NOT NULL AND m.price > 0
          AND s.cn_lowest IS NOT NULL AND s.cn_lowest > 0
          AND m.in_stock = 1
          AND s.Size_KR IS NOT NULL AND s.Size_KR != ''
          AND m.price < s.cn_lowest * 0.85
    """

    if dry_run:
        # count만 확인
        cur.execute("""
            SELECT COUNT(*) as cnt
            FROM poizon_spu p
            JOIN poizon_sku s ON p.spu_id = s.spu_id
            JOIN musinsa m ON
                CAST(p.style_id AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci
                = CAST(m.style_id AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci
            WHERE m.price IS NOT NULL AND m.price > 0
              AND s.cn_lowest IS NOT NULL AND s.cn_lowest > 0
              AND m.in_stock = 1
              AND s.Size_KR IS NOT NULL AND s.Size_KR != ''
              AND m.price < s.cn_lowest * 0.85
        """)
        count = cur.fetchone()["cnt"]
        log.info(f"[dry-run] Pick 대상: {count}건 (저장 안 함)")
    else:
        cur.execute(sql)
        conn.commit()
        count = cur.rowcount
        log.info(f"Pick 저장: {count}건")

    cur.close()
    return count


def show_summary(conn):
    """최근 pick 요약"""
    cur = conn.cursor()
    cur.execute("""
        SELECT brand, COUNT(*) as cnt,
               ROUND(AVG(cn_margin_pct), 1) as avg_cn_pct,
               ROUND(AVG(musinsa_price), 0) as avg_price,
               ROUND(AVG(poizon_cn_lowest), 0) as avg_cn
        FROM pick_snapshot
        WHERE snapshot_at >= NOW() - INTERVAL 10 MINUTE
        GROUP BY brand
        ORDER BY cnt DESC
    """)
    print("\n=== 브랜드별 Pick (방금) ===")
    for r in cur.fetchall():
        print(f"  {r['brand']:20s} {r['cnt']:3d}건  "
              f"평균가 {r['avg_price']:>8,}원  "
              f"CN평균 {r['avg_cn']:>8,}원  "
              f"CN마진 {r['avg_cn_pct']}%")
    cur.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    conn = get_db()
    try:
        count = pick_products(conn, dry_run=dry_run)
        if count > 0 and not dry_run:
            show_summary(conn)
    finally:
        conn.close()
