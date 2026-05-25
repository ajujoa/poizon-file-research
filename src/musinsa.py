"""무신사 크롤러 (Playwright 기반)
Poizon style_id로 무신사 검색 → 상품 정보 수집 → DB 저장
※ 사이즈 추출: 무신사 신규 UI 적용으로 API 기반 전환 필요 (TODO)
"""
import logging
import re
import time
import configparser
import random
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MusinsaCrawler:
    """무신사 상품 검색 + 정보 수집 크롤러"""

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

    # ── 로깅 / 설정 ──────────────────────────────────

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
        self.exclude_days = self.config.getint('Musinsa', 'exclude_days', fallback=30)

    # ── 브라우저 ─────────────────────────────────────

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
        """musinsa 테이블 생성"""
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
                item_id VARCHAR(50),
                goods_no VARCHAR(50),
                size_kr TEXT,
                musinsa_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_style_id (style_id),
                INDEX idx_brand (brand),
                INDEX idx_goods_no (goods_no),
                INDEX idx_musinsa_update (musinsa_update)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
        """)
        conn.commit()
        cur.close()
        conn.close()
        self.logger.info("musinsa 테이블 생성 완료")

    def get_style_ids(self, limit: int = None) -> list[dict]:
        """Poizon SPU에서 무신사 검색할 style_id 목록 가져오기"""
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

    # ── 검색 / 수집 ──────────────────────────────────

    def _random_sleep(self):
        time.sleep(random.uniform(self.min_sleep, self.max_sleep))

    def _check_no_results(self) -> bool:
        try:
            return self.page.locator('text=검색 결과가 없습니다').count() > 0
        except Exception:
            return False

    def _extract_goods_no(self, href: str) -> str | None:
        """musinsa_link에서 goods_no 추출 (/products/3976350 → 3976350)"""
        m = re.search(r'/products/(\d+)', href or '')
        return m.group(1) if m else None

    def collect_data_by_keyword(self, style_id: str, total_count=None, current_index=None) -> list[dict] | None:
        """style_id로 무신사 검색 → 상품 정보 수집 (사이즈 제외)"""
        idx_str = f" ({current_index}/{total_count})" if current_index and total_count else ""
        self.logger.info(f"{style_id}{idx_str}")

        try:
            # 1. 검색 페이지 접속
            search_url = f"{self.BASE_URL}?keyword={style_id}&keywordType=keyword&gf=A"
            self.page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
            self.page.wait_for_timeout(500)

            if self._check_no_results():
                self.logger.info(f"{style_id}: 검색 결과 없음")
                return [{'style_id': style_id, 'brand': None, 'musinsa_link': None,
                         'product_name': None, 'price': None, 'original_price': None,
                         'discount_rate': None, 'item_id': None, 'goods_no': None,
                         'size_kr': None}]

            self._random_sleep()

            # 2. 검색 결과에서 상품 링크 찾기
            product_links = self.page.locator('a.gtm-select-item').all()
            if not product_links:
                self.page.wait_for_timeout(1000)
                product_links = self.page.locator('a.gtm-select-item').all()

            if not product_links:
                self.logger.warning(f"{style_id}: 상품 링크 없음")
                return None

            # 3. 각 상품 정보 추출
            all_products = []
            seen_ids = set()

            for link_el in product_links:
                item_id = link_el.get_attribute('data-item-id')
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                try:
                    href = link_el.get_attribute('href') or ''
                    goods_no = self._extract_goods_no(href)

                    # 상품명 (img alt)
                    product_name = ''
                    img = link_el.locator('img').first
                    if img.count() > 0:
                        alt = img.get_attribute('alt') or ''
                        product_name = alt.replace('[무료반품] ', '').strip()

                    product = {
                        'style_id': style_id,
                        'musinsa_link': href,
                        'product_name': product_name,
                        'price': int(link_el.get_attribute('data-price') or 0),
                        'original_price': int(link_el.get_attribute('data-original-price') or 0),
                        'discount_rate': int(link_el.get_attribute('data-discount-rate') or 0),
                        'brand': link_el.get_attribute('data-item-brand'),
                        'item_id': item_id,
                        'goods_no': goods_no,
                        'size_kr': '',  # TODO: API 기반 사이즈 추출
                    }

                    self.logger.info(
                        f"  {product['product_name'][:50]} | "
                        f"{product['price']:,}원 | {product['brand']} | "
                        f"goods_no={goods_no}"
                    )
                    all_products.append(product)

                except Exception as e:
                    self.logger.warning(f"  상품 추출 실패: {e}")
                    continue

            if not all_products:
                self.logger.warning(f"{style_id}: 추출된 상품 없음")
                return None

            return all_products

        except Exception as e:
            self.logger.error(f"{style_id} 수집 실패: {e}")
            return None

    # ── DB 저장 ──────────────────────────────────────

    def save_to_db(self, products: list[dict]) -> int:
        """수집된 상품 데이터를 DB에 저장 (UPSERT)"""
        if not products:
            return 0

        conn = self._get_db()
        cur = conn.cursor()
        saved = 0

        for p in products:
            try:
                style_id = str(p['style_id'])

                if p['musinsa_link'] is None:
                    cur.execute("""
                        INSERT INTO musinsa (style_id, musinsa_update)
                        VALUES (%s, CURRENT_TIMESTAMP)
                        ON DUPLICATE KEY UPDATE musinsa_update = CURRENT_TIMESTAMP
                    """, (style_id,))
                else:
                    cur.execute("""
                        INSERT INTO musinsa (
                            style_id, brand, musinsa_link, product_name,
                            price, original_price, discount_rate,
                            item_id, goods_no, size_kr, musinsa_update
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON DUPLICATE KEY UPDATE
                            brand = VALUES(brand),
                            musinsa_link = VALUES(musinsa_link),
                            product_name = VALUES(product_name),
                            price = VALUES(price),
                            original_price = VALUES(original_price),
                            discount_rate = VALUES(discount_rate),
                            item_id = VALUES(item_id),
                            goods_no = VALUES(goods_no),
                            size_kr = VALUES(size_kr),
                            musinsa_update = CURRENT_TIMESTAMP
                    """, (
                        style_id, p['brand'], p['musinsa_link'], p['product_name'],
                        p['price'], p['original_price'], p['discount_rate'],
                        p['item_id'], p.get('goods_no'), p['size_kr'],
                    ))

                saved += 1
            except Exception as e:
                self.logger.error(f"DB 저장 실패 (style_id={p.get('style_id')}): {e}")
                conn.rollback()

        conn.commit()
        cur.close()
        conn.close()
        self.logger.info(f"DB 저장 완료: {saved}건")
        return saved

    # ── 메인 ─────────────────────────────────────────

    def run(self, limit: int = None) -> dict:
        """무신사 크롤링 메인 루프"""
        try:
            print("=" * 50)
            print("  무신사 크롤링 시작")
            print("=" * 50)

            self.create_table()

            style_ids = self.get_style_ids(limit=limit)
            if not style_ids:
                print("검색할 style_id가 없습니다 (이미 오늘 전부 처리됨)")
                return {'total': 0, 'found': 0, 'saved': 0}

            if not self._init_browser():
                return {'total': 0, 'found': 0, 'saved': 0}

            total = len(style_ids)
            found = 0
            total_saved = 0
            batch = []

            print(f"\n대상 style_id: {total}개\n")

            for i, row in enumerate(style_ids, 1):
                style_id = str(row['style_id'])
                products = self.collect_data_by_keyword(style_id, total, i)

                if products:
                    has_link = any(p.get('musinsa_link') for p in products)
                    if has_link:
                        found += 1
                    batch.extend(products)

                # 200개 단위로 DB 저장
                if len(batch) >= 200:
                    saved = self.save_to_db(batch)
                    total_saved += saved
                    batch = []
                    print(f"  → 중간 저장: 누적 {total_saved}건 (발견 {found}/{i})")

                self._random_sleep()

            if batch:
                saved = self.save_to_db(batch)
                total_saved += saved

            print(f"\n{'=' * 50}")
            print(f"  완료: {total}개 검색, {found}개 발견, {total_saved}건 저장")
            print(f"{'=' * 50}")

            return {'total': total, 'found': found, 'saved': total_saved}

        finally:
            self.close()


# ── Entry Point ───────────────────────────────────────

if __name__ == '__main__':
    crawler = MusinsaCrawler()
    crawler.run()
