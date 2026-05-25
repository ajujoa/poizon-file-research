"""무신사 크롤러 (Playwright 기반)
Poizon style_id로 무신사 검색 → 정확 매칭 상품 확인 → 가격 + 사이즈/재고 수집 → DB 저장
"""
import logging
import re
import time
import configparser
import random
import json
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MusinsaCrawler:
    """무신사 상품 검색 + 가격/사이즈/재고 수집 크롤러"""

    BASE_URL = "https://www.musinsa.com/search/goods"
    PRODUCT_URL = "https://www.musinsa.com/products/{goods_no}"

    def __init__(self, headless=True):
        self.headless = headless
        self._setup_logging()
        self._load_config()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def _setup_logging(self):
        self.logger = logging.getLogger('MusinsaCrawler')
        if self.logger.handlers:
            return
        self.logger.setLevel(logging.INFO)
        log_dir = PROJECT_ROOT / 'logs'
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f'musinsa_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        fh = logging.FileHandler(str(log_file), encoding='utf-8')
        fh.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(fmt)
        ch.setFormatter(fmt)
        self.logger.addHandler(fh)
        self.logger.addHandler(ch)
        self.logger.propagate = False

    def _load_config(self):
        self.config = configparser.ConfigParser()
        config_path = PROJECT_ROOT / 'config' / 'poizon_config.ini'
        self.config.read(str(config_path), encoding='utf-8')
        self.min_sleep = self.config.getfloat('Musinsa', 'min_sleep', fallback=0.5)
        self.max_sleep = self.config.getfloat('Musinsa', 'max_sleep', fallback=1.5)

    def _init_browser(self):
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--no-sandbox', '--disable-dev-shm-usage',
                    '--disable-gpu', '--disable-blink-features=AutomationControlled',
                ]
            )
            self.context = self.browser.new_context(
                viewport={'width': 1200, 'height': 1000},
                locale='ko-KR',
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
                ),
            )
            self.page = self.context.new_page()
            self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)
            self.logger.info("무신사 브라우저 초기화 완료")
            return True
        except Exception as e:
            self.logger.error(f"브라우저 초기화 실패: {e}")
            return False

    def close(self):
        try:
            if self.page: self.page.close()
            if self.context: self.context.close()
            if self.browser: self.browser.close()
            if self.playwright: self.playwright.stop()
        except Exception:
            pass

    # ── DB ───────────────────────────────────────────

    @staticmethod
    def _get_db():
        import pymysql
        db_cfg_path = PROJECT_ROOT / 'config' / 'dbconfig.ini'
        cfg = configparser.ConfigParser()
        cfg.read(str(db_cfg_path))
        db = cfg['database']
        return pymysql.connect(
            host=db['host'], port=int(db['port']),
            user=db['user'], password=db['password'],
            database=db['database'], charset=db.get('charset', 'utf8mb4'),
            cursorclass=pymysql.cursors.DictCursor,
        )

    def create_table(self):
        conn = self._get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS musinsa (
                id INT AUTO_INCREMENT PRIMARY KEY,
                style_id VARCHAR(50) NOT NULL,
                brand VARCHAR(100),
                musinsa_link VARCHAR(500),
                product_name VARCHAR(500),
                price INT,
                original_price INT,
                discount_rate INT,
                goods_no VARCHAR(50),
                sizes JSON COMMENT '사이즈별 재고: [{"size":"270","available":true},...]',
                in_stock BOOLEAN DEFAULT FALSE COMMENT '구매 가능한 사이즈 1개 이상',
                musinsa_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_style_id (style_id),
                INDEX idx_goods_no (goods_no),
                INDEX idx_in_stock (in_stock),
                INDEX idx_musinsa_update (musinsa_update)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """)
        conn.commit()
        cur.close()
        conn.close()
        self.logger.info("musinsa 테이블 확인 완료")

    def get_style_ids(self, limit: int = None) -> list[dict]:
        conn = self._get_db()
        cur = conn.cursor()
        sql = """
            SELECT DISTINCT
                CAST(p.style_id AS CHAR) AS style_id,
                p.brand,
                p.item_name
            FROM poizon_spu p
            LEFT JOIN musinsa m ON
                CAST(p.style_id AS CHAR) = CAST(m.style_id AS CHAR)
                AND DATE(m.musinsa_update) = CURDATE()
            WHERE m.style_id IS NULL
              AND p.style_id IS NOT NULL
              AND p.style_id != ''
            ORDER BY p.style_id
        """
        if limit:
            sql += f" LIMIT {limit}"
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        self.logger.info(f"무신사 검색 대상 style_id: {len(rows)}개")
        return rows

    # ── 검색 ─────────────────────────────────────────

    def _random_sleep(self):
        time.sleep(random.uniform(self.min_sleep, self.max_sleep))

    def _extract_goods_no(self, href: str) -> str | None:
        m = re.search(r'/products/(\d+)', href or '')
        return m.group(1) if m else None

    def _check_no_results(self) -> bool:
        try:
            return (self.page.locator('text=검색 결과가 없습니다').count() > 0 or
                    self.page.locator('text=검색결과가 없습니다').count() > 0)
        except Exception:
            return False

    def search_product(self, style_id: str, total_count=None, current_index=None) -> dict | None:
        """style_id로 무신사 검색 → 첫 번째 매칭 상품 정보 반환"""
        idx_str = f" ({current_index}/{total_count})" if current_index and total_count else ""

        try:
            search_url = f"{self.BASE_URL}?keyword={style_id}&keywordType=keyword&gf=A"
            self.page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
            self.page.wait_for_timeout(300)

            if self._check_no_results():
                self.logger.info(f"{style_id}{idx_str}: 검색 결과 없음")
                return {'style_id': style_id, 'found': False}

            product_link = self.page.locator('a.gtm-select-item').first
            if not product_link.count():
                self.page.wait_for_timeout(1000)
                product_link = self.page.locator('a.gtm-select-item').first

            if not product_link.count():
                self.logger.warning(f"{style_id}{idx_str}: 상품 링크 없음")
                return {'style_id': style_id, 'found': False}

            href = product_link.get_attribute('href') or ''
            goods_no = self._extract_goods_no(href)
            item_id = product_link.get_attribute('data-item-id') or ''

            img = product_link.locator('img').first
            product_name = ''
            if img.count() > 0:
                alt = img.get_attribute('alt') or ''
                product_name = alt.replace('[무료반품] ', '').strip()

            return {
                'style_id': style_id,
                'found': True,
                'musinsa_link': href,
                'product_name': product_name,
                'price': int(product_link.get_attribute('data-price') or 0),
                'original_price': int(product_link.get_attribute('data-original-price') or 0),
                'discount_rate': int(product_link.get_attribute('data-discount-rate') or 0),
                'brand': product_link.get_attribute('data-item-brand'),
                'item_id': item_id,
                'goods_no': goods_no,
            }
        except Exception as e:
            self.logger.error(f"{style_id}{idx_str} 검색 실패: {e}")
            return None

    # ── 사이즈/재고 수집 (상품 페이지 접속 + API 응답 캡처) ──

    def _fetch_sizes(self, goods_no: str) -> list[dict] | None:
        """상품 페이지 접속 → API 응답 캡처 → 사이즈+재고 매핑"""
        try:
            captured_options = []
            captured_inventory = []

            def on_response(response):
                url = response.url
                if f'/goods/{goods_no}/options' in url and 'prioritized' not in url and 'question' not in url:
                    try:
                        captured_options.append(response.json())
                    except Exception:
                        pass
                elif 'prioritized-inventories' in url:
                    try:
                        captured_inventory.append(response.json())
                    except Exception:
                        pass

            self.page.on('response', on_response)

            product_url = self.PRODUCT_URL.format(goods_no=goods_no)
            self.page.goto(product_url, wait_until='domcontentloaded', timeout=30000)
            self.page.wait_for_timeout(3000)

            self.page.remove_listener('response', on_response)

            if not captured_options:
                self.logger.warning(f"  옵션 API 미수신")
                return None

            opt_data = captured_options[0]
            if opt_data.get('meta', {}).get('result') != 'SUCCESS':
                return None

            option_items = opt_data['data'].get('optionItems', [])
            if not option_items:
                return None

            # 재고 맵
            stock_map = {}
            if captured_inventory:
                inv_data = captured_inventory[0]
                if inv_data.get('meta', {}).get('result') == 'SUCCESS':
                    for inv in inv_data.get('data', []) if isinstance(inv_data.get('data'), list) else []:
                        stock_map[inv['productVariantId']] = not inv.get('outOfStock', True)

            # 사이즈 리스트
            sizes = []
            for item in option_items:
                vid = item['no']
                vals = item.get('optionValues', [])
                size_name = vals[0].get('name', '') if vals else ''
                available = stock_map.get(vid, None)
                if size_name:
                    sizes.append({'size': size_name, 'available': available})

            return sizes

        except Exception as e:
            self.logger.error(f"  사이즈 수집 실패: {e}")
            return None

    # ── DB 저장 ──────────────────────────────────────

    def save_to_db(self, product: dict) -> bool:
        try:
            conn = self._get_db()
            cur = conn.cursor()
            style_id = str(product['style_id'])

            size_data = product.get('sizes')
            size_json = json.dumps(size_data, ensure_ascii=False) if size_data else None
            in_stock = any(s.get('available') for s in (size_data or [])) if size_data else False

            cur.execute("""
                INSERT INTO musinsa (
                    style_id, brand, musinsa_link, product_name,
                    price, original_price, discount_rate,
                    goods_no, sizes, in_stock, musinsa_update
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    brand = VALUES(brand),
                    musinsa_link = VALUES(musinsa_link),
                    product_name = VALUES(product_name),
                    price = VALUES(price),
                    original_price = VALUES(original_price),
                    discount_rate = VALUES(discount_rate),
                    goods_no = VALUES(goods_no),
                    sizes = VALUES(sizes),
                    in_stock = VALUES(in_stock),
                    musinsa_update = CURRENT_TIMESTAMP
            """, (
                style_id, product.get('brand'), product.get('musinsa_link'),
                product.get('product_name'), product.get('price'),
                product.get('original_price'), product.get('discount_rate'),
                product.get('goods_no'), size_json, in_stock,
            ))

            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"  DB 저장 실패 ({style_id}): {e}")
            return False

    def save_not_found(self, style_id: str) -> bool:
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO musinsa (style_id, musinsa_update)
                VALUES (%s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE musinsa_update = CURRENT_TIMESTAMP
            """, (str(style_id),))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"  not_found 저장 실패: {e}")
            return False

    # ── 메인 ─────────────────────────────────────────

    def run(self, limit: int = None) -> dict:
        try:
            print("=" * 50)
            print("  무신사 크롤링 시작")
            print("=" * 50)

            self.create_table()

            style_ids = self.get_style_ids(limit=limit)
            if not style_ids:
                print("검색할 style_id가 없습니다 (이미 오늘 전부 처리됨)")
                return {'total': 0, 'found': 0, 'in_stock': 0}

            if not self._init_browser():
                return {'total': 0, 'found': 0, 'in_stock': 0}

            total = len(style_ids)
            found = 0
            in_stock = 0

            print(f"\n대상 style_id: {total}개\n")

            for i, row in enumerate(style_ids, 1):
                style_id = str(row['style_id'])
                product = self.search_product(style_id, total, i)

                if product is None:
                    continue

                if not product.get('found'):
                    self.save_not_found(style_id)
                    continue

                found += 1
                info = (
                    f"  {product['product_name'][:45]} | "
                    f"{product['price']:,}원 | {product['brand']}"
                )

                # 사이즈 + 재고 수집 (상품 페이지 접속)
                goods_no = product.get('goods_no')
                if goods_no:
                    sizes = self._fetch_sizes(goods_no)
                    product['sizes'] = sizes
                    if sizes:
                        available_sizes = [s['size'] for s in sizes if s['available']]
                        sold_out = [s['size'] for s in sizes if s['available'] is False]
                        unknown = [s['size'] for s in sizes if s['available'] is None]

                        parts = []
                        if available_sizes:
                            in_stock += 1
                            parts.append(f"재고:{','.join(available_sizes[:5])}")
                        if sold_out:
                            parts.append(f"품절:{len(sold_out)}개")
                        if unknown:
                            parts.append(f"미확인:{len(unknown)}개")
                        if not parts:
                            parts.append(f"옵션:{len(sizes)}개")

                        info += f" | {' '.join(parts)}"

                self.logger.info(info)

                if not self.save_to_db(product):
                    self.logger.warning(f"  DB 저장 실패")

                if i % 50 == 0:
                    print(f"  → 진행: {i}/{total} (발견 {found}, 재고 {in_stock})")

                self._random_sleep()

            print(f"\n{'=' * 50}")
            print(f"  완료: {total}개 검색")
            print(f"  발견: {found}개 | 재고 있음: {in_stock}개")
            print(f"{'=' * 50}")

            return {'total': total, 'found': found, 'in_stock': in_stock}

        finally:
            self.close()


if __name__ == '__main__':
    crawler = MusinsaCrawler()
    crawler.run()
