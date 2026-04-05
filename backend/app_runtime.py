"""
앱 런타임 부트스트랩/종료 조정기.
"""
import json
import logging
import threading
import time
import urllib.request

import uvicorn

from backend.api_server import set_runtime_engines
from backend.database import DatabaseManager
from backend.log_generator import ActivityLogGenerator
from backend.monitor_engine_thread import MonitorEngineThread
from backend.rule_engine import RuleEngine


class ApiServerThread(threading.Thread):
    """FastAPI 서버를 스레드로 실행 (메인 프로세스 공유)."""

    def __init__(self, app, port: int):
        super().__init__(daemon=True)
        self._app = app
        self._port = port
        self._server = None

    def run(self):
        from logging.handlers import RotatingFileHandler
        from backend.config import AppConfig

        log_path = AppConfig.get_log_path().with_name("api.log")
        handler = RotatingFileHandler(
            str(log_path),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        for logger_name in ("uvicorn.error", "uvicorn.access", "fastapi"):
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.INFO)
            if not any(
                isinstance(existing, RotatingFileHandler) and existing.baseFilename == handler.baseFilename
                for existing in logger.handlers
            ):
                logger.addHandler(handler)

        config = uvicorn.Config(
            self._app,
            host="127.0.0.1",
            port=self._port,
            log_level="warning",
            access_log=False
        )
        if hasattr(config, "handle_signals"):
            config.handle_signals = False
        self._server = uvicorn.Server(config)
        self._server.run()

    def stop(self):
        if self._server:
            self._server.should_exit = True


class RuntimeCoordinator:
    """API 서버, DB, 모니터링 엔진, 로그 생성기를 조합/종료."""

    def __init__(
        self,
        *,
        fastapi_app,
        api_port: int,
        exit_callback,
        on_activity_detected,
        on_toast_requested,
    ):
        self.fastapi_app = fastapi_app
        self.api_port = api_port
        self.exit_callback = exit_callback
        self.on_activity_detected = on_activity_detected
        self.on_toast_requested = on_toast_requested

        self.api_server_thread = None
        self.db_manager = None
        self.rule_engine = None
        self.log_generator = None
        self.monitor_engine = None

    def start_api_server(self):
        """FastAPI 서버 시작."""
        logging.info("[API Server] Starting...")
        self.api_server_thread = ApiServerThread(self.fastapi_app, self.api_port)
        self.api_server_thread.start()
        print(f"[API Server] Started on port {self.api_port}")

    def wait_for_api_ready(self, dist_status_provider, timeout: float = 10.0) -> bool:
        """API 서버 헬스체크 대기."""
        deadline = time.time() + timeout
        url = f"http://127.0.0.1:{self.api_port}/api/health"
        last_error = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode())
                        api_version = data.get("api_version", "unknown")
                        dist_status, build_time = dist_status_provider()

                        print(f"[Version Check] API: v{api_version}, dist: {dist_status}")
                        if build_time:
                            print(f"[Version Check] WebUI build time: {build_time}")

                        if dist_status == "NOT_FOUND":
                            print("[Warning] webui/dist not found! Run 'npm run build' in webui folder.")
                            logging.warning("[WebUI] dist not found. Run 'npm run build' in webui folder.")
                        elif dist_status == "NO_INDEX":
                            print("[Warning] webui/dist/index.html not found!")
                            logging.warning("[WebUI] dist/index.html not found.")

                        logging.info("[API Server] Health check OK - API v%s, dist %s", api_version, dist_status)
                        return True
            except Exception as exc:
                last_error = exc
                time.sleep(0.5)

        if last_error:
            logging.error("[API Server] Health check failed: %s", last_error)
        return False

    def start_monitoring(self):
        """DB/룰/로그/모니터링 엔진 시작."""
        self.db_manager = DatabaseManager()
        self.db_manager.cleanup_unfinished_activities()
        self.rule_engine = RuleEngine(self.db_manager)
        self.log_generator = ActivityLogGenerator(self.db_manager)
        self.monitor_engine = MonitorEngineThread(
            db_manager=self.db_manager,
            rule_engine=self.rule_engine,
            on_activity_detected=self.on_activity_detected,
            on_toast_requested=self.on_toast_requested,
            log_generator=self.log_generator
        )
        self.monitor_engine.start()
        print("[Monitor Engine] Started (threading-based)")

        set_runtime_engines(
            self.rule_engine,
            self.monitor_engine.focus_blocker,
            self.log_generator,
            self.monitor_engine,
            self.exit_callback
        )
        self._start_log_generator()
        self.db_manager.close()

    def stop(self, api_pid_path):
        """런타임 종료."""
        try:
            if self.monitor_engine and self.monitor_engine.is_alive():
                print("[App] Stopping monitor engine...")
                self.monitor_engine.stop(timeout=3.0)
        except Exception as exc:
            print(f"[App] Monitor engine stop error: {exc}")

        try:
            if self.api_server_thread and self.api_server_thread.is_alive():
                self.api_server_thread.stop()
                if threading.current_thread() is not self.api_server_thread:
                    self.api_server_thread.join(timeout=3.0)
        except Exception as exc:
            print(f"[App] API server stop error: {exc}")

        try:
            if api_pid_path.exists():
                api_pid_path.unlink()
        except Exception as exc:
            print(f"[App] API pid cleanup error: {exc}")

    def _start_log_generator(self):
        """활동 로그 생성 (백그라운드)."""
        def generate_logs():
            try:
                self.log_generator.update_all_logs()
                print("[Log Generator] Logs generated successfully")
            except Exception as exc:
                print(f"[Log Generator] Error: {exc}")

        threading.Thread(target=generate_logs, daemon=True).start()
