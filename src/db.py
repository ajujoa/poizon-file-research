# 데이터베이스 연결 및 관리

import pymysql
from typing import Optional


class Database:
    """MariaDB 연결 관리"""

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.config = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "charset": "utf8mb4",
        }
        self.conn: Optional[pymysql.Connection] = None

    def connect(self):
        self.conn = pymysql.connect(**self.config)

    def close(self):
        if self.conn:
            self.conn.close()
