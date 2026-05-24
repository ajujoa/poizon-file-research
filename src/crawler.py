# Poizon API 크롤러
# 데이터 수집 및 페이지 크롤링 담당

import requests
from typing import Optional


class PoizonClient:
    """Poizon 플랫폼 API 클라이언트"""

    def __init__(self, base_url: str = "https://www.poizon.com", delay: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
