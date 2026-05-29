#!/usr/bin/env python3
"""
Poizon-Musinsa 교집합 상품 가격/재고 변경 감지 모니터

감지 항목:
  - poizon cn_lowest(최저가) 변동
  - musinsa price 변동
  - musinsa in_stock 변동 (Y→N, N→Y)

price_snapshot 테이블에 이전 상태를 저장하고, 설정 간격마다 비교.
설정: poizon_config.ini → [Monitor] check_interval (분, 기본 30)

Usage:
  python src/price_monitor.py
"""

import configparser
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pymysql

PROJECT_ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MONITOR] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("price_monitor")


def load_config() -> int:
    cfg = configparser.ConfigParser()
    cfg.read(str(PROJECT_ROOT / "config" / "poizon_config.ini"), encoding="utf-8")
    return cfg.getint("Monitor", "check_interval", fallback=30)


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


def get_intersection(conn) -> list[dict]:
    """poizon + musinsa 교집합 (style_id 기준, 재고 무관)"""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            p.spu_id,
            CAST(p.style_id AS CHAR) AS style_id,
            p.brand, p.item_name,
            s.sku_id, s.Size_KR, s.cn_lowest, s.est_payout,
            m.goods_no, m.price AS musinsa_price,
            m.in_stock AS musinsa_in_stock
        FROM poizon_spu p
        JOIN poizon_sku s ON p.spu_id = s.spu_id
        JOIN musinsa m ON
            CAST(p.style_id AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci
            = CAST(m.style_id AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci
        WHERE m.goods_no IS NOT NULL AND m.goods_no != ''
          AND s.Size_KR IS NOT NULL AND s.Size_KR != ''
        ORDER BY p.spu_id, s.Size_KR
    """)
    rows = cur.fetchall()
    cur.close()
    return rows


def get_last_snapshot(conn, spu_id: int, size_kr: str) -> dict | None:
    """해당 상품-사이즈의 마지막 스냅샷"""
    cur = conn.cursor()
    cur.execute("""
        SELECT poizon_cn_lowest, musinsa_price, musinsa_in_stock
        FROM price_snapshot
        WHERE spu_id = %s AND size_kr = %s
        ORDER BY snapshot_at DESC
        LIMIT 1
    """, (spu_id, size_kr))
    row = cur.fetchone()
    cur.close()
    return row


def save_snapshot(conn, row: dict):
    """현재 상태를 price_snapshot에 저장"""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO price_snapshot (
            spu_id, style_id, brand, item_name, size_kr,
            poizon_est_payout, poizon_cn_lowest, poizon_avg_30_day,
            poizon_total_sales,
            musinsa_price, musinsa_goods_no, musinsa_in_stock
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, %s, %s, %s)
    """, (
        row["spu_id"], row["style_id"], row["brand"], row["item_name"],
        row["Size_KR"],
        row["est_payout"] or 0,
        row["cn_lowest"] or 0,
        row["musinsa_price"] or 0,
        row["goods_no"],
        row["musinsa_in_stock"],
    ))
    conn.commit()
    cur.close()


def run(interval_minutes: int = 30):
    conn = get_db()
    log.info(f"모니터링 시작 (간격: {interval_minutes}분)")

    first = True

    while True:
        try:
            conn.ping(reconnect=True)
            products = get_intersection(conn)

            if first:
                # 최초 실행: 모든 상품 스냅샷 초기화 (기존 스냅샷 있으면 덮어쓰지 않음)
                log.info(f"초기화: 교집합 {len(products)}건")
                for row in products:
                    last = get_last_snapshot(conn, row["spu_id"], row["Size_KR"])
                    if last is None:
                        save_snapshot(conn, row)
                first = False
                log.info(f"초기 스냅샷 저장 완료")
            else:
                changed_cnt = 0
                cn_changes = 0
                price_changes = 0
                stock_changes = 0

                for row in products:
                    last = get_last_snapshot(conn, row["spu_id"], row["Size_KR"])
                    if last is None:
                        save_snapshot(conn, row)
                        continue

                    cn_now = row["cn_lowest"] or 0
                    cn_prev = last["poizon_cn_lowest"] or 0
                    price_now = row["musinsa_price"] or 0
                    price_prev = last["musinsa_price"] or 0
                    stock_now = row["musinsa_in_stock"]
                    stock_prev = last["musinsa_in_stock"]

                    changes = []
                    if cn_now != cn_prev:
                        cn_changes += 1
                        changes.append(f"CN최저가 {cn_prev:,}→{cn_now:,}")

                    if price_now != price_prev:
                        price_changes += 1
                        changes.append(f"무신사가 {price_prev:,}→{price_now:,}")

                    if stock_now != stock_prev:
                        stock_changes += 1
                        s_now = "Y" if stock_now else "N"
                        s_prev = "Y" if stock_prev else "N"
                        changes.append(f"재고 {s_prev}→{s_now}")

                    if changes:
                        changed_cnt += 1
                        name = f"{row['brand']} {row['style_id']} ({row['Size_KR']})"
                        log.warning(f"[변경] {name} | {' | '.join(changes)}")
                        save_snapshot(conn, row)

                if changed_cnt == 0:
                    log.info(f"체크 완료: {len(products)}건 — 변경 없음")
                else:
                    log.warning(
                        f"체크 완료: {len(products)}건 중 {changed_cnt}건 변경 "
                        f"(CN {cn_changes}, 가격 {price_changes}, 재고 {stock_changes})"
                    )

        except Exception as e:
            log.error(f"오류: {e}")

        log.info(f"다음 체크: {interval_minutes}분 후...")
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    interval = load_config()
    log.info(f"설정된 체크 간격: {interval}분")
    run(interval_minutes=interval)
