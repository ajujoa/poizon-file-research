"""
Poizon Seller 크롤러 (Playwright 기반)
- 로그인 → Item Search → 브랜드 선택 → 상품 목록 수집
"""
import logging
import os
import time
import configparser
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class PoizonCrawler:
    """Poizon Seller 플랫폼 크롤러"""

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
        self.logger = logging.getLogger('PoizonCrawler')
        if self.logger.handlers:
            return
        self.logger.setLevel(logging.INFO)
        log_dir = PROJECT_ROOT / 'logs'
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f'crawler_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
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
        self.email = self.config.get('Credentials', 'email')
        self.password = self.config.get('Credentials', 'password')
        raw = self.config.get('Brands', 'list', fallback='')
        self.brand_list = [b.strip() for b in raw.split(',') if b.strip()]

    # ── 브라우저 ─────────────────────────────────────

    def _init_browser(self):
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-blink-features=AutomationControlled',
                ]
            )
            self.context = self.browser.new_context(
                viewport={'width': 1500, 'height': 1300},
                locale='ko-KR',
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
                ),
            )
            self.page = self.context.new_page()

            # 자동화 감지 우회
            self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)

            self.logger.info("브라우저 초기화 완료")
            return True
        except Exception as e:
            self.logger.error(f"브라우저 초기화 실패: {e}")
            return False

    # ── 로그인 ───────────────────────────────────────

    def _login(self) -> bool:
        try:
            self.logger.info("로그인 시작")
            self.page.goto(
                'https://seller.poizon.com/',
                wait_until='domcontentloaded',
                timeout=45000
            )
            self.page.wait_for_load_state('domcontentloaded')
            time.sleep(4)

            self.page.fill('#mobile_number', self.email)
            time.sleep(0.5)
            self.page.fill('#password', self.password)
            time.sleep(0.5)
            self.page.click('button.ant-btn-primary')

            # SPA: 로그인 폼이 사라질 때까지 대기
            for _ in range(15):
                time.sleep(1)
                if not self.page.query_selector('input#mobile_number'):
                    self.logger.info(f"로그인 완료: {self.page.url}")
                    return True

            self.logger.error("로그인 폼이 사라지지 않음")
            return False

        except Exception as e:
            self.logger.error(f"로그인 실패: {e}")
            return False

    # ── Item Search ──────────────────────────────────

    def _go_to_item_search(self) -> bool:
        """Item Search 페이지로 이동"""
        try:
            self.page.goto(
                'https://seller.poizon.com/main/goods/search',
                wait_until='domcontentloaded',
                timeout=30000
            )
            self.page.wait_for_timeout(5000)
            self.logger.info(f"Item Search 진입: {self.page.url}")
            return True
        except Exception as e:
            self.logger.error(f"Item Search 이동 실패: {e}")
            return False

    def _get_brands(self) -> list[str]:
        """Item Search 페이지에서 브랜드 목록 추출"""
        brands = []
        try:
            brand_selectors = [
                'span.brandTxt___eBXxW',
                'span[class*="brandTxt"]',
            ]
            for sel in brand_selectors:
                elements = self.page.query_selector_all(sel)
                if elements:
                    brands = [el.inner_text().strip() for el in elements]
                    break

            self.logger.info(f"브랜드 {len(brands)}개 발견: {brands[:10]}...")
        except Exception as e:
            self.logger.error(f"브랜드 추출 실패: {e}")

        return brands

    def _select_brand(self, brand_name: str) -> bool:
        """Brand 필터 팝오버 열기 → 검색 → 선택 → OK → 적용"""
        try:
            self.logger.info(f"브랜드 필터 '{brand_name}' 적용 시도...")

            # 1. Brand 트리거 버튼 클릭
            brand_btn = self.page.locator('button._trigger_1ftnr_1').first
            if brand_btn.count() == 0:
                self.logger.warning("Brand 트리거 버튼을 찾을 수 없음")
                return False

            brand_btn.click()
            self.page.wait_for_timeout(2000)

            # 2. 팝오버 검색창에 브랜드명 입력
            popover_input = self.page.locator(
                '._popover_1ftnr_123 input.ant-input'
            ).first
            if popover_input.count() == 0:
                self.logger.warning("팝오버 검색 input을 찾을 수 없음")
                return False

            popover_input.fill(brand_name)
            self.page.wait_for_timeout(2000)

            # 3. 매칭된 브랜드 아이템 클릭
            brand_items = self.page.locator(
                '._popover_1ftnr_123 .ant-list-item'
            ).all()
            matching = [b for b in brand_items if b.inner_text().strip().upper() == brand_name.upper()]
            if not matching:
                # 부분 매칭 시도
                matching = [b for b in brand_items if brand_name.upper() in b.inner_text().strip().upper()]

            if not matching:
                self.logger.warning(f"'{brand_name}'에 매칭되는 브랜드 없음")
                # 팝오버 닫기
                self.page.keyboard.press('Escape')
                return False

            matching[0].click()
            self.page.wait_for_timeout(500)

            # 4. OK 버튼 클릭
            ok_btn = self.page.locator(
                '._popover_1ftnr_123 button:has-text("OK")'
            ).first
            if ok_btn.count() > 0:
                ok_btn.click()
                self.page.wait_for_timeout(1500)

            self.logger.info(f"브랜드 '{brand_name}' 선택 완료")
            return True

        except Exception as e:
            self.logger.error(f"브랜드 선택 오류: {e}")
            return False

    def _select_all_brands(self) -> bool:
        """Brand 팝오버에서 설정된 모든 브랜드를 누적 선택 → OK → 리로드 대기"""
        try:
            self.logger.info(f"모든 브랜드 선택 시작: {self.brand_list}")

            # 1. Brand 트리거 버튼 클릭
            brand_btn = self.page.locator('button._trigger_1ftnr_1').first
            if brand_btn.count() == 0:
                self.logger.warning("Brand 트리거 버튼을 찾을 수 없음")
                return False
            brand_btn.click()
            self.page.wait_for_timeout(2000)

            popover_input = self.page.locator(
                '._popover_1ftnr_123 input.ant-input'
            ).first
            if popover_input.count() == 0:
                self.logger.warning("팝오버 검색 input을 찾을 수 없음")
                return False

            selected = []
            for brand in self.brand_list:
                # 검색창에 브랜드명 입력
                popover_input.fill(brand)
                self.page.wait_for_timeout(1500)

                # 매칭된 브랜드 아이템 찾기
                brand_items = self.page.locator(
                    '._popover_1ftnr_123 .ant-list-item'
                ).all()
                matching = [b for b in brand_items 
                          if b.inner_text().strip().upper() == brand.upper()]
                if not matching:
                    matching = [b for b in brand_items 
                              if brand.upper() in b.inner_text().strip().upper()]

                if not matching:
                    self.logger.warning(f"'{brand}' 매칭 실패, 건너뜀")
                    continue

                matching[0].click()
                self.page.wait_for_timeout(300)
                selected.append(brand)

            self.logger.info(f"선택 완료: {len(selected)}/{len(self.brand_list)} → {selected}")

            # OK 버튼 클릭 (한 번만)
            ok_btn = self.page.locator(
                '._popover_1ftnr_123 button:has-text("OK")'
            ).first
            if ok_btn.count() > 0:
                ok_btn.click()
                self.page.wait_for_timeout(3000)

            self.logger.info("모든 브랜드 선택 + OK 완료")
            return len(selected) > 0

        except Exception as e:
            self.logger.error(f"전체 브랜드 선택 오류: {e}")
            return False

    # ── API 수집 (deprecated — Export All 방식으로 대체) ──

    def _fetch_aurora_api(self, brand_name: str, page_num: int = 1, page_size: int = 20) -> dict | None:
        """aurora-spu/merchant/search API 응답을 인터셉트하여 상품 목록 수집"""
        import json as _json
        try:
            self.logger.info(f"[{brand_name}] 페이지 {page_num} aurora API (size={page_size})...")

            # Search & List 버튼 클릭 → API 호출을 가로채서 pageNum/pageSize 수정
            search_btn = self.page.locator('button:has-text("Search & List")').first
            if search_btn.count() == 0:
                self.logger.warning("Search & List 버튼을 찾을 수 없음")
                return None

            resp_data = [None]

            def handle_route(route):
                req = route.request
                if 'aurora-spu/merchant/search' in req.url:
                    try:
                        body = _json.loads(req.post_data or '{}')
                        body['pageNum'] = page_num
                        body['pageSize'] = page_size
                        body['current'] = page_num
                        body['page'] = page_num
                        new_body = _json.dumps(body)
                        route.continue_(post_data=new_body)
                        return
                    except Exception:
                        pass
                route.continue_()

            route_handler = None
            try:
                route_handler = self.page.route(
                    '**/aurora-spu/merchant/search**',
                    handle_route
                )

                with self.page.expect_response(
                    lambda r: 'aurora-spu/merchant/search' in r.url,
                    timeout=20000
                ) as resp_info:
                    search_btn.click()

                resp = resp_info.value
                if resp.status != 200:
                    self.logger.error(f"Aurora API 실패: HTTP {resp.status}")
                    return None

                data = resp.json()
                d = data.get('data', {})
                total = d.get('total', 0)
                spu_list = d.get('merchantSpuDtoList', [])
                self.logger.info(f"[{brand_name}] p{page_num}: {len(spu_list)}개 상품, total {total}개")
                return data

            finally:
                if route_handler is not None:
                    self.page.unroute('**/aurora-spu/merchant/search**')

        except Exception as e:
            self.logger.error(f"Aurora API 오류: {e}")
            return None

    def _get_product_list(self, brand_name: str, max_pages: int = None, page_size: int = 20) -> list[dict]:
        """브랜드별 모든 상품 수집 (페이지네이션)"""
        all_products = []

        # 첫 페이지 수집
        result = self._fetch_aurora_api(brand_name, page_num=1, page_size=page_size)
        if not result:
            return all_products

        data = result.get('data', {})
        products = data.get('merchantSpuDtoList', [])
        all_products.extend(products)

        total = data.get('total', 0)
        total_pages = (total + page_size - 1) // page_size
        if max_pages and max_pages < total_pages:
            total_pages = max_pages

        if total_pages <= 1:
            return all_products

        self.logger.info(f"[{brand_name}] total={total}, page_size={page_size}, pages={total_pages}")

        # 나머지 페이지 수집
        for page_num in range(2, total_pages + 1):
            result = self._fetch_aurora_api(brand_name, page_num=page_num, page_size=page_size)
            if result:
                products = result.get('data', {}).get('merchantSpuDtoList', [])
                all_products.extend(products)
            time.sleep(1.5)

        return all_products

    # ── Export Center ────────────────────────────────

    EXPORT_CENTER_URL = 'https://seller.poizon.com/main/exportCenter'

    def _go_to_export_center(self) -> bool:
        """Export Center 페이지로 이동"""
        try:
            if 'exportCenter' in self.page.url:
                self.page.reload()
            else:
                self.page.goto(
                    self.EXPORT_CENTER_URL,
                    wait_until='domcontentloaded',
                    timeout=30000
                )
            self.page.wait_for_timeout(4000)
            self.logger.info(f"Export Center 진입: {self.page.url}")
            return True
        except Exception as e:
            self.logger.error(f"Export Center 이동 실패: {e}")
            return False

    def _check_recent_export(self, within_hours: int = 1) -> str | None:
        """Export Center에서 오늘 + within_hours 이내 Completed task 찾기 → task_no 반환"""
        try:
            if not self._go_to_export_center():
                return None

            tasks = self.page.evaluate('''() => {
                const rows = document.querySelectorAll('.ant-table-tbody tr');
                const tasks = [];
                for (const r of rows) {
                    if (r.offsetHeight === 0) continue;
                    const cells = r.querySelectorAll('td');
                    const no = cells[0]?.innerText?.trim() || '';
                    const status = cells[3]?.innerText?.trim() || '';
                    const end_time = cells[5]?.innerText?.trim() || '';
                    const has_file = !!cells[6]?.querySelector('a');
                    tasks.push({no, status, end_time, has_file});
                }
                return tasks;
            }''')

            now = datetime.now()
            today_str = now.strftime('%m/%d/%Y')

            for t in tasks:
                if t['status'] != 'Completed' or not t['has_file']:
                    continue
                if t['end_time'] == '-':
                    continue
                # End Time 파싱: "05/24/2026 11:53:33 AM"
                try:
                    end_dt = datetime.strptime(t['end_time'], '%m/%d/%Y %I:%M:%S %p')
                except ValueError:
                    continue
                # 같은 날짜 + within_hours 이내
                if end_dt.strftime('%m/%d/%Y') != today_str:
                    continue
                diff_seconds = (now - end_dt).total_seconds()
                if 0 <= diff_seconds <= within_hours * 3600:
                    self.logger.info(
                        f"최근 Export 발견: task_no={t['no']}, "
                        f"end_time={t['end_time']} ({diff_seconds:.0f}s 전)"
                    )
                    return t['no']

            self.logger.info("최근(1h 이내) Export 없음 — 새로 Export 필요")
            return None

        except Exception as e:
            self.logger.error(f"최근 Export 확인 실패: {e}")
            return None

    # ── Export / 다운로드 ────────────────────────────

    def _export_brand(self, brand: str) -> str | None:
        """Export All → Go → exportCenter로 이동, task_no 반환"""
        # Export All 클릭
        export_btn = self.page.locator('button:has-text("Export All")').first
        if export_btn.count() == 0:
            self.logger.error(f"[{brand}] Export All 버튼 없음")
            return None
        export_btn.click()
        self.page.wait_for_timeout(2000)

        # 모달 내 Go 버튼
        modal = self.page.locator('.ant-modal-content').first
        go_btn = modal.locator('button:has-text("Go")').first
        if go_btn.count() == 0:
            self.logger.error(f"[{brand}] 모달 내 Go 버튼 없음")
            return None
        go_btn.click(force=True)
        self.page.wait_for_timeout(5000)

        if 'exportCenter' not in self.page.url:
            self.logger.error(f"[{brand}] exportCenter 이동 실패: {self.page.url}")
            return None

        # 현재 최상단 task_no 기록 (이번 export의 task_no 식별용)
        task_no = self.page.evaluate('''() => {
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            for (const r of rows) {
                if (r.offsetHeight === 0) continue;
                const t = r.querySelector('td:first-child')?.innerText?.trim();
                if (t) return t;
            }
            return '';
        }''')

        self.logger.info(f"[{brand}] Export 요청 완료, task_no={task_no}")
        return task_no

    def _wait_for_export(self, task_no: str, timeout: int = 1200, interval: int = 10) -> bool:
        """exportCenter에서 task_no의 상태가 Completed 될 때까지 폴링"""
        elapsed = 0
        while elapsed < timeout:
            # 페이지 새로고침으로 최신 상태 반영
            self.page.reload()
            self.page.wait_for_timeout(2000)

            # 해당 task_no 행 찾아서 상태 확인
            status = self.page.evaluate(f'''(task_no) => {{
                const rows = document.querySelectorAll('.ant-table-tbody tr');
                for (const r of rows) {{
                    if (r.offsetHeight === 0) continue;
                    const cells = r.querySelectorAll('td');
                    const no = cells[0]?.innerText?.trim();
                    if (no === task_no) {{
                        return {{
                            status: cells[3]?.innerText?.trim() || '',
                            has_file: !!cells[6]?.querySelector('a')
                        }};
                    }}
                }}
                return {{ status: 'NOT_FOUND' }};
            }}''', task_no)

            self.logger.info(
                f"[{task_no}] {elapsed}s elapsed, status={status.get('status')}, "
                f"has_file={status.get('has_file')}"
            )

            if status.get('status') == 'Completed' and status.get('has_file'):
                self.logger.info(f"[{task_no}] Export 완료! (총 {elapsed}s)")
                return True

            time.sleep(interval)
            elapsed += interval

        self.logger.warning(f"[{task_no}] 타임아웃 ({timeout}s)")
        return False

    def _download_export(self, task_no: str, save_dir: str) -> Path | None:
        """Completed task의 File 링크 클릭하여 다운로드"""
        from pathlib import Path as _Path

        save_path = _Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)

        # 해당 task_no 행의 File 링크
        idx = self.page.evaluate(f'''(task_no) => {{
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            for (let i = 0; i < rows.length; i++) {{
                if (rows[i].offsetHeight === 0) continue;
                const no = rows[i].querySelector('td:first-child')?.innerText?.trim();
                if (no === task_no) return i;
            }}
            return -1;
        }}''', task_no)

        if idx < 0:
            self.logger.error(f"[{task_no}] 행 찾기 실패")
            return None

        file_link = self.page.locator(
            f'.ant-table-tbody tr:nth-child({idx + 1}) td:last-child a'
        ).first

        if file_link.count() == 0:
            self.logger.error(f"[{task_no}] File 링크 없음")
            return None

        with self.page.expect_download(timeout=30000) as dl_info:
            file_link.click()

        download = dl_info.value
        filename = download.suggested_filename
        filepath = save_path / filename
        download.save_as(str(filepath))

        self.logger.info(f"[{task_no}] 다운로드 완료: {filepath} ({filepath.stat().st_size:,} bytes)")
        return filepath

    # ── 정리 ─────────────────────────────────────────

    def close(self):
        try:
            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass

    # ── 메인 ─────────────────────────────────────────

    def run(self, output_dir: str | None = None):
        """로그인 → exportCenter 확인 → 최근 Export 없으면 전체 브랜드 선택 후 단일 Export"""
        try:
            if not self._init_browser():
                return

            if not self._login():
                return

            if not self.brand_list:
                print("브랜드 리스트가 비어있음 (config/poizon_config.ini [Brands] 확인)")
                return

            # 출력 디렉토리
            save_dir = Path(output_dir) if output_dir else PROJECT_ROOT / 'xls'
            save_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n대상 브랜드 ({len(self.brand_list)}개): {', '.join(self.brand_list)}")
            print(f"저장 디렉토리: {save_dir}\n")

            # 1. 먼저 exportCenter에서 최근(1h 이내) Export 확인
            recent_task = self._check_recent_export(within_hours=1)
            if recent_task:
                print(f"최근 Export 발견 (task_no={recent_task}) — 바로 다운로드")
                filepath = self._download_export(recent_task, str(save_dir))
                if filepath:
                    print(f"다운로드 완료: {filepath}")
                    return [{'task_no': recent_task, 'file': str(filepath)}]
                print("다운로드 실패 — 새로 Export 진행")

            print("최근 Export 없음 — 전체 브랜드 Export 시작\n")

            # 2. 전체 브랜드 선택 + 단일 Export
            if not self._go_to_item_search():
                print("Item Search 이동 실패")
                return

            if not self._select_all_brands():
                print("전체 브랜드 선택 실패")
                return

            self.page.wait_for_timeout(3000)

            task_no = self._export_brand("ALL")
            if not task_no:
                print("Export 요청 실패")
                return

            if self._wait_for_export(task_no):
                filepath = self._download_export(task_no, str(save_dir))
                if filepath:
                    print(f"\n{'='*50}")
                    print(f"완료: {filepath}")
                    return [{'task_no': task_no, 'file': str(filepath)}]
                print("다운로드 실패")
            else:
                print("Export 타임아웃")

        finally:
            self.close()


# ── Entry Point ───────────────────────────────────────

if __name__ == '__main__':
    crawler = PoizonCrawler()
    crawler.run()
