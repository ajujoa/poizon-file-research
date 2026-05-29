#!/usr/bin/env python3
"""
Poizon Pipeline Orchestrator
- 매일 지정 시간에 전체 파이프라인 실행
- 장애 복구: 크래시 시 자동 재시작 (Docker restart: unless-stopped)
- GitHub 업데이트 감지 → pull → 재시작

파이프라인:
  main.py (크롤링 → DB적재 → 사이즈추출 → 무신사검색)
  → 10초 sleep
  → musinsa_pick.py (가격 경쟁력 Pick)
"""

import configparser
import logging
import os
import signal
import subprocess
import sys
import time
import threading
from pathlib import Path

import schedule

# ── 설정 ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
CONFIG_PATH = PROJECT_ROOT / "config" / "poizon_config.ini"
LOG_DIR = PROJECT_ROOT / "logs"

LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ORCH] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(str(LOG_DIR / "orchestrator.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("orchestrator")


def load_schedule_config() -> tuple[int, int, int]:
    cfg = configparser.ConfigParser()
    cfg.read(str(CONFIG_PATH), encoding="utf-8")
    hour = cfg.getint("Schedule", "crawl_hour", fallback=7)
    minute = cfg.getint("Schedule", "crawl_minute", fallback=0)
    poll_interval = cfg.getint("Schedule", "github_poll_interval", fallback=300)
    return hour, minute, poll_interval


def run_script(script_name: str, timeout: int = 7200) -> bool:
    """서브프로세스로 Python 스크립트 실행."""
    script_path = SRC_DIR / script_name
    if not script_path.exists():
        log.error(f"스크립트 없음: {script_path}")
        return False

    log.info(f"[{script_name}] 시작")
    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start
        output = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if output:
            for line in output.splitlines()[-30:]:
                log.info(f"[{script_name}] {line}")

        if result.returncode == 0:
            log.info(f"[{script_name}] 완료 ({elapsed:.0f}s)")
            return True
        else:
            log.error(f"[{script_name}] 실패 (exit={result.returncode}, {elapsed:.0f}s)")
            if stderr:
                for line in stderr.splitlines()[-10:]:
                    log.error(f"[{script_name}] {line}")
            return False

    except subprocess.TimeoutExpired:
        log.error(f"[{script_name}] 타임아웃 ({timeout}s 초과)")
        return False
    except Exception as e:
        log.error(f"[{script_name}] 예외: {e}")
        return False


def run_daily_job():
    """하루 1회 실행: main.py → 10초 → musinsa_pick.py"""
    log.info("=" * 50)
    log.info("데일리 파이프라인 시작")
    log.info("=" * 50)

    # Step 1-4: main.py (crawler → load_db → size → musinsa)
    ok = run_script("main.py", timeout=7200)

    if not ok:
        log.warning("main.py 실패 — musinsa_pick 건너뜀")
        log.info("파이프라인 종료: 실패")
        return

    # 10초 sleep 후 musinsa_pick
    log.info("10초 대기 후 musinsa_pick 실행...")
    time.sleep(10)

    run_script("musinsa_pick.py", timeout=600)
    log.info("데일리 파이프라인 종료")


# ── GitHub 폴링 ──────────────────────────────────────────────────────

def check_github_update(poll_interval: int):
    """백그라운드 스레드: 주기적 git fetch → 변경 감지 → pull → 종료."""
    repo_dir = PROJECT_ROOT
    if not (repo_dir / ".git").exists():
        log.warning("Git 저장소 아님 — GitHub 폴링 비활성화")
        return

    log.info(f"GitHub 폴링 시작 (간격: {poll_interval}s)")

    while True:
        try:
            time.sleep(poll_interval)

            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(repo_dir),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                continue
            local_hash = result.stdout.strip()

            subprocess.run(
                ["git", "fetch", "origin"],
                cwd=str(repo_dir),
                capture_output=True, timeout=30,
            )

            result = subprocess.run(
                ["git", "rev-parse", "origin/main"],
                cwd=str(repo_dir),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                continue
            remote_hash = result.stdout.strip()

            if local_hash != remote_hash:
                log.info("GitHub 업데이트 감지! git pull → 재시작")
                subprocess.run(
                    ["git", "pull", "origin", "main"],
                    cwd=str(repo_dir),
                    capture_output=True, timeout=30,
                )
                log.info("Git pull 완료 — 종료하여 Docker 재시작")
                os._exit(0)

        except Exception as e:
            log.error(f"GitHub 폴링 오류: {e}")


# ── 메인 ─────────────────────────────────────────────────────────────

def main():
    log.info("Poizon Pipeline Orchestrator 시작")
    log.info(f"PID: {os.getpid()}")

    hour, minute, poll_interval = load_schedule_config()
    log.info(f"스케줄: 매일 {hour:02d}:{minute:02d}")
    log.info(f"GitHub 폴링: {poll_interval}s 간격")

    # GitHub 폴링 스레드
    threading.Thread(
        target=check_github_update,
        args=(poll_interval,),
        daemon=True,
        name="github-poller",
    ).start()

    # 스케줄 등록
    schedule.every().day.at(f"{hour:02d}:{minute:02d}", "Asia/Seoul").do(run_daily_job)
    log.info(f"다음 실행: {schedule.next_run()}")

    # 시그널 핸들러
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    # 메인 루프
    while True:
        try:
            schedule.run_pending()
            time.sleep(30)
        except Exception as e:
            log.error(f"스케줄러 오류: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
