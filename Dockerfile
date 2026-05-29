FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

# 시스템 의존성 (mysql-client는 healthcheck용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-mysql-client \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성
RUN pip install --no-cache-dir \
    pymysql>=1.0.0 \
    requests>=2.28.0 \
    pandas>=2.0.0 \
    numpy>=1.24.0 \
    openpyxl>=3.1.0 \
    schedule>=1.2.0

# 프로젝트 코드
COPY src/ /app/src/
COPY config/ /app/config/
COPY xls/ /app/xls/

# DB host를 Docker 서비스명으로 변경
RUN sed -i 's/^host = .*/host = mariadb/' /app/config/dbconfig.ini
RUN sed -i 's/host="localhost"/host="mariadb"/' /app/src/db.py

# orchestrator
COPY orchestrator.py /app/

CMD ["python", "/app/orchestrator.py"]
