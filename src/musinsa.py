"""무신사 크롤러 (Playwright 기반 - 멀티스레드)
Poizon style_id로 무신사 검색 → 정확 매칭 상품 확인 → 가격 + 사이즈/재고 수집 → DB 저장
"""
import logging
import re
import time
import configparser
import random
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

from proxy_cred import get_proxy_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MusinsaCrawler:
    """무신사 상품 검색 + 가격/사이즈/재고 수집 크롤러 (멀티스레드 + 프록시)"""

    BASE_URL = "https://www.musinsa.com/search/goods"
    PRODUCT_URL = "https://www.musinsa.com/products/{goods_no}"

    def __init__(self, headless=True):
        self.headless = headless
        self._setup_logging()
        self._load_config()
        self._setup_proxy()
        self.playwright = None
        self.browser = None

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
        fmt = logging.Formatter('%(asctime)s [W%(worker)s] %(levelname)s %(message)s',
                                datefmt='%H:%M:%S')
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
        self.workers = self.config.getint('Musinsa', 'workers', fallback=8)
        self.cn_lowest_min = self.config.getint('Musinsa', 'cn_lowest_min', fallback=0)

    def _setup_proxy(self):
        """Bright Data 프록시 URL → Playwright proxy 설정으로 변환"""
        raw_url = get_proxy_url()
        parsed = urlparse(raw_url)
        self.proxy_config = {
            'server': f'{parsed.scheme}://{parsed.hostname}:{parsed.port}',
            'username': parsed.username,
            'password': parsed.password,
        }
        self.logger.info(f"프록시 설정 완료: {parsed.hostname}:{parsed.port}",
                         extra={'worker': 'M'})
        # TODO: Playwright + residential proxy 너무 느림 → 일단 비활성화
        self.proxy_config = None

    def _init_browser(self):
        """공유 브라우저 인스턴스만 생성 (context/page는 worker별로)"""
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--no-sandbox', '--disable-dev-shm-usage',
                    '--disable-gpu', '--disable-blink-features=AutomationControlled',
                ]
            )
            self.logger.info(f"무신사 브라우저 초기화 완료", extra={'worker': 'M'})
            return True
        except Exception as e:
            self.logger.error(f"브라우저 초기화 실패: {e}", extra={'worker': 'M'})
            return False

    def _create_context(self):
        """worker별 독립 context + page 생성 (프록시 적용)"""
        context = self.browser.new_context(
            viewport={'width': 1200, 'height': 1000},
            locale='ko-KR',
            proxy=self.proxy_config,
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
            ),
        )
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)
        return context, page

    def close(self):
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
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
        self.logger.info("musinsa 테이블 확인 완료", extra={'worker': 'M'})

    def get_style_ids(self, limit: int = None) -> list[dict]:
        conn = self._get_db()
        cur = conn.cursor()
        sql = """
            SELECT
                CAST(p.style_id AS CHAR) AS style_id,
                p.brand,
                p.item_name
            FROM poizon_spu p
            JOIN poizon_sku s ON p.spu_id = s.spu_id
            LEFT JOIN musinsa m ON
                CAST(p.style_id AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci
                = CAST(m.style_id AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_general_ci
                AND DATE(m.musinsa_update) = CURDATE()
            WHERE m.style_id IS NULL
              AND p.style_id IS NOT NULL
              AND p.style_id != ''
              AND p.style_id REGEXP '^[A-Za-z0-9-]+$'
              AND p.primary_cat = 'Shoes'
            GROUP BY p.style_id, p.brand, p.item_name
            HAVING MAX(s.total_sales) > 30
        """
        if self.cn_lowest_min > 0:
            sql += f" AND MIN(s.cn_lowest) >= {int(self.cn_lowest_min)}"
        sql += "\n            ORDER BY p.style_id"
        if limit:
            sql += f" LIMIT {limit}"
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        self.logger.info(f"무신사 검색 대상 style_id: {len(rows)}개", extra={'worker': 'M'})
        return rows

    # ── 검색 (page 기반) ──────────────────────────────

    def _random_sleep(self):
        time.sleep(random.uniform(self.min_sleep, self.max_sleep))

    @staticmethod
    def _extract_goods_no(href: str) -> str | None:
        m = re.search(r'/products/(\d+)', href or '')
        return m.group(1) if m else None

    def _search_on_page(self, page, style_id: str, total_count=None,
                        current_index=None, worker_id=0) -> dict | None:
        """style_id로 무신사 검색 → 첫 번째 매칭 상품 정보 반환 (지정된 page 사용)"""
        idx_str = ""
        if current_index and total_count:
            idx_str = f" ({current_index}/{total_count})"

        try:
            search_url = f"{self.BASE_URL}?keyword={style_id}&keywordType=keyword&gf=A"
            page.goto(search_url, wait_until='domcontentloaded', timeout=30000)

            # '검색 결과 없음'이 나타날 때까지 3초 대기
            try:
                page.wait_for_selector('text=검색 결과가 없습니다', timeout=3000)
                self.logger.info(f"{style_id}{idx_str}: 검색 결과 없음",
                                 extra={'worker': worker_id})
                return {'style_id': style_id, 'found': False}
            except Exception:
                pass
            try:
                page.wait_for_selector('text=검색결과가 없습니다', timeout=1000)
                self.logger.info(f"{style_id}{idx_str}: 검색 결과 없음",
                                 extra={'worker': worker_id})
                return {'style_id': style_id, 'found': False}
            except Exception:
                pass

            # 검색 결과 상품이 로드될 때까지 15초 대기
            try:
                page.wait_for_selector('a.gtm-select-item', timeout=15000)
            except Exception:
                self.logger.warning(f"{style_id}{idx_str}: 상품 링크 없음 (타임아웃)",
                                    extra={'worker': worker_id})
                return {'style_id': style_id, 'found': False}

            # style_id가 상품명에 포함된 첫 번째 결과 찾기 (잘못 매핑 방지)
            product_link = None
            product_name = ''
            sid_norm = re.sub(r'[-_]', '', style_id).lower()
            for link in page.locator('a.gtm-select-item').all()[:5]:
                img = link.locator('img').first
                alt = ''
                if img.count() > 0:
                    alt = (img.get_attribute('alt') or '').replace('[무료반품] ', '').strip()
                alt_norm = re.sub(r'[-_]', '', alt).lower()
                if sid_norm in alt_norm or style_id.upper() in alt.upper():
                    product_link = link
                    product_name = alt
                    break

            if not product_link:
                self.logger.warning(
                    f"{style_id}{idx_str}: 상품명에 style_id 미포함 → 검색 실패 처리",
                    extra={'worker': worker_id})
                return {'style_id': style_id, 'found': False}

            href = product_link.get_attribute('href') or ''
            goods_no = self._extract_goods_no(href)
            item_id = product_link.get_attribute('data-item-id') or ''

            if not product_name:
                img = product_link.locator('img').first
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
            self.logger.error(f"{style_id}{idx_str} 검색 실패: {e}",
                              extra={'worker': worker_id})
            return None

    # ── 사이즈/재고 수집 (page 기반) ──────────────────

    def _fetch_sizes_on_page(self, page, goods_no: str,
                             worker_id=0) -> list[dict] | None:
        """상품 페이지 접속 → API 응답 캡처 → 사이즈+재고 매핑"""
        try:
            captured_options = []
            captured_inventory = []

            def on_response(response):
                url = response.url
                if f'/goods/{goods_no}/options' in url and \
                   'prioritized' not in url and 'question' not in url:
                    try:
                        captured_options.append(response.json())
                    except Exception:
                        pass
                elif 'prioritized-inventories' in url:
                    try:
                        captured_inventory.append(response.json())
                    except Exception:
                        pass

            page.on('response', on_response)

            product_url = self.PRODUCT_URL.format(goods_no=goods_no)
            page.goto(product_url, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(3000)

            page.remove_listener('response', on_response)

            if not captured_options:
                self.logger.warning(f"  옵션 API 미수신", extra={'worker': worker_id})
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
                    inv_list = inv_data.get('data', [])
                    if isinstance(inv_list, list):
                        for inv in inv_list:
                            stock_map[inv['productVariantId']] = \
                                not inv.get('outOfStock', True)

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
            self.logger.error(f"  사이즈 수집 실패: {e}", extra={'worker': worker_id})
            return None

    # ── DB 저장 ──────────────────────────────────────

    def save_to_db(self, product: dict, worker_id=0) -> bool:
        try:
            conn = self._get_db()
            cur = conn.cursor()
            style_id = str(product['style_id'])

            size_data = product.get('sizes')
            size_json = json.dumps(size_data, ensure_ascii=False) if size_data else None
            in_stock = any(s.get('available') for s in (size_data or [])) \
                if size_data else False

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
            self.logger.error(f"  DB 저장 실패 ({style_id}): {e}",
                              extra={'worker': worker_id})
            return False

    def save_not_found(self, style_id: str, worker_id=0) -> bool:
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
            self.logger.error(f"  not_found 저장 실패: {e}",
                              extra={'worker': worker_id})
            return False

    # ── Worker 청크 처리 ─────────────────────────────

    def _process_chunk(self, style_ids: list, total: int, worker_id: int) -> dict:
        """하나의 worker가 할당된 style_id 청크를 처리 (독립 Playwright + 프록시)"""
        # 각 스레드에서 독립적인 Playwright 인스턴스 생성 (greenlet 충돌 방지)
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=self.headless,
            args=[
                '--no-sandbox', '--disable-dev-shm-usage',
                '--disable-gpu', '--disable-blink-features=AutomationControlled',
            ]
        )
        context_kwargs = {
            'viewport': {'width': 1200, 'height': 1000},
            'locale': 'ko-KR',
            'ignore_https_errors': True,
            'user_agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
            ),
        }
        if self.proxy_config:
            context_kwargs['proxy'] = self.proxy_config
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)
        # 불필요한 리소스 차단 → 프록시 속도 향상
        page.route("**/*.{png,jpg,jpeg,gif,svg,ico,webp,woff,woff2,ttf,eot,css}",
                   lambda route: route.abort())

        found = 0
        in_stock = 0

        try:
            for i, row in enumerate(style_ids):
                style_id = str(row['style_id'])
                product = self._search_on_page(
                    page, style_id, total, None, worker_id)

                if product is None:
                    continue

                if not product.get('found'):
                    self.save_not_found(style_id, worker_id)
                    continue

                found += 1
                info = (
                    f"  {product['product_name'][:45]} | "
                    f"{product['price']:,}원 | {product['brand']}"
                )

                # 사이즈 + 재고 수집
                goods_no = product.get('goods_no')
                if goods_no:
                    sizes = self._fetch_sizes_on_page(page, goods_no, worker_id)
                    product['sizes'] = sizes
                    if sizes:
                        available_sizes = [s['size'] for s in sizes
                                          if s['available']]
                        sold_out = [s['size'] for s in sizes
                                   if s['available'] is False]
                        unknown = [s['size'] for s in sizes
                                  if s['available'] is None]

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

                self.logger.info(info, extra={'worker': worker_id})

                if not self.save_to_db(product, worker_id):
                    self.logger.warning(f"  DB 저장 실패",
                                        extra={'worker': worker_id})

                self._random_sleep()

        finally:
            page.close()
            context.close()
            browser.close()
            pw.stop()

        return {'found': found, 'in_stock': in_stock}

    # ── 메인 ─────────────────────────────────────────

    def run(self, limit: int = None) -> dict:
        try:
            print("=" * 50)
            print(f"  무신사 크롤링 시작 (workers: {self.workers})")
            print("=" * 50)

            self.create_table()

            style_ids = self.get_style_ids(limit=limit)
            if not style_ids:
                print("검색할 style_id가 없습니다 (이미 오늘 전부 처리됨)")
                return {'total': 0, 'found': 0, 'in_stock': 0}

            total = len(style_ids)
            actual_workers = min(self.workers, total)

            # 청크 분할 (round-robin)
            chunks = [[] for _ in range(actual_workers)]
            for i, row in enumerate(style_ids):
                chunks[i % actual_workers].append(row)
            chunks = [c for c in chunks if c]

            print(f"\n대상 style_id: {total}개 | workers: {len(chunks)}개")
            print(f"worker당: {len(chunks[0])}~{len(chunks[-1])}개\n")

            found = 0
            in_stock = 0
            completed = 0

            with ThreadPoolExecutor(max_workers=len(chunks),
                                    thread_name_prefix="W") as executor:
                futures = {}
                for i, chunk in enumerate(chunks):
                    f = executor.submit(self._process_chunk, chunk, total, i)
                    futures[f] = i

                for f in as_completed(futures):
                    wid = futures[f]
                    try:
                        r = f.result()
                        found += r['found']
                        in_stock += r['in_stock']
                        completed += len(chunks[wid])
                        print(f"  → Worker {wid} 완료 | "
                              f"누적 {completed}/{total} "
                              f"(발견 {found}, 재고 {in_stock})")
                    except Exception as e:
                        self.logger.error(f"Worker {wid} 실패: {e}",
                                          extra={'worker': wid})

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
