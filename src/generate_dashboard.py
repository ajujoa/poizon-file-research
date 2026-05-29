#!/usr/bin/env python3
"""
Poizon Pick Dashboard Generator

pick_snapshot 데이터로 HTML 대시보드 생성.
Tailscale 파일 서버: https://ubuntu-llm.tail931162.ts.net/poizon_dashboard/
"""
import configparser
import json
from datetime import datetime
from pathlib import Path

import pymysql

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "src" / "dashboard_template.html"
OUTPUT_DIR = Path("/app/output")
POIZON_SEARCH = "https://www.poizon.com/search?keyword={style_id}"
MUSINSA_PRODUCT = "https://www.musinsa.com/products/{goods_no}"


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


def get_pick_data(conn):
    """pick_snapshot + musinsa 상품명 JOIN"""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT
            ps.spu_id, ps.style_id, ps.brand, ps.item_name, ps.size_kr,
            ps.poizon_est_payout, ps.poizon_cn_lowest,
            ps.poizon_avg_30_day, ps.poizon_total_sales,
            ps.musinsa_price, ps.musinsa_goods_no, ps.musinsa_in_stock,
            DATE(ps.snapshot_at) AS snap_date,
            m.product_name AS musinsa_name
        FROM pick_snapshot ps
        LEFT JOIN musinsa m ON ps.musinsa_goods_no = m.goods_no
        ORDER BY ps.brand, ps.style_id, ps.size_kr
    """)
    rows = cur.fetchall()
    cur.close()
    return rows


def get_snapshot_dates(conn):
    """날짜별 히스토리 목록"""
    cur = conn.cursor()
    cur.execute("""
        SELECT DATE(snapshot_at) AS snap_date, COUNT(*) AS cnt
        FROM pick_snapshot
        GROUP BY snap_date
        ORDER BY snap_date DESC
    """)
    rows = cur.fetchall()
    cur.close()
    return rows


def render_dashboard(conn):
    """HTML 대시보드 생성"""
    pick_data = get_pick_data(conn)
    dates = get_snapshot_dates(conn)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # JSON 데이터
    data_json = []
    for row in pick_data:
        data_json.append({
            "spu_id": row["spu_id"],
            "style_id": row["style_id"],
            "brand": row["brand"] or "",
            "item_name": row["item_name"] or "",
            "size_kr": row["size_kr"] or "",
            "est_payout": row["poizon_est_payout"] or 0,
            "cn_lowest": row["poizon_cn_lowest"] or 0,
            "avg_30_day": row["poizon_avg_30_day"] or 0,
            "total_sales": row["poizon_total_sales"] or 0,
            "musinsa_price": row["musinsa_price"] or 0,
            "goods_no": row["musinsa_goods_no"] or "",
            "in_stock": bool(row["musinsa_in_stock"]),
            "musinsa_name": row["musinsa_name"] or "",
            "snap_date": str(row["snap_date"]),
            "poizon_link": POIZON_SEARCH.format(style_id=row["style_id"]),
            "musinsa_link": MUSINSA_PRODUCT.format(goods_no=row["musinsa_goods_no"]),
        })

    date_options = "\n".join(
        f'        <option value="{d["snap_date"]}">{d["snap_date"]} ({d["cnt"]}건)</option>'
        for d in dates
    )

    history_rows = "\n".join(
        f'      <tr><td>{d["snap_date"]}</td><td>{d["cnt"]}건</td>'
        f'<td><a href="#" onclick="document.getElementById(\'date-filter\')'
        f'.value=\'{d["snap_date"]}\';switchTab(\'pick\');filterTable();'
        f'return false">보기</a></td></tr>'
        for d in dates
    )

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("__GENERATED_AT__", now)
    html = html.replace("__DATE_OPTIONS__", date_options)
    html = html.replace("__HISTORY_ROWS__", history_rows)
    html = html.replace("__DATA_JSON__", json.dumps(data_json, ensure_ascii=False))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "index.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path, len(pick_data)


if __name__ == "__main__":
    conn = get_db()
    try:
        path, count = render_dashboard(conn)
        print(f"대시보드 생성: {path} ({count}건)")
        print(f"URL: https://ubuntu-llm.tail931162.ts.net/poizon_dashboard/")
    finally:
        conn.close()
