"""MariaDB 연결 관리"""
import pymysql


class Database:
    def __init__(self, host="localhost", user="naver", password="naver1234",
                 database="poizon_research", charset="utf8mb4"):
        self.config = {
            "host": host,
            "user": user,
            "password": password,
            "database": database,
            "charset": charset,
            "cursorclass": pymysql.cursors.DictCursor,
        }
        self.conn = None

    def connect(self):
        self.conn = pymysql.connect(**self.config)
        return self.conn

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        self.connect()
        return self.conn

    def __exit__(self, *args):
        self.close()
