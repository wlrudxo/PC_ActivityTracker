"""
Activity Tracker - PyWebView Edition

PyWebView + FastAPI + pystray 기반 앱
기존 PyQt6 UI를 웹 UI로 대체
"""
import sys
import os
import shutil
import sqlite3
import urllib.error
import threading
import time
import signal
import webbrowser
import socket
import ctypes
import logging
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

if getattr(sys, 'frozen', False) or not sys.stdout:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')


class _StreamFilter:
    """Filter noisy pywebview native introspection errors from output."""

    def __init__(self, stream, drop_substrings):
        self._stream = stream
        self._drop_substrings = drop_substrings
        self._buffer = ""

    def write(self, message):
        if not message:
            return 0
        self._buffer += message
        written = 0
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line += "\n"
            if any(sub in line for sub in self._drop_substrings):
                written += len(line)
                continue
            self._stream.write(line)
            written += len(line)
        return written

    def flush(self):
        if self._buffer:
            if not any(sub in self._buffer for sub in self._drop_substrings):
                self._stream.write(self._buffer)
            self._buffer = ""
        self._stream.flush()

    def isatty(self):
        return self._stream.isatty()

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", None)


class _LogFilter(logging.Filter):
    """Filter noisy pywebview native introspection errors from logs."""

    def __init__(self, drop_substrings):
        super().__init__()
        self._drop_substrings = drop_substrings

    def filter(self, record):
        message = record.getMessage()
        return not any(sub in message for sub in self._drop_substrings)

try:
    import webview
    WEBVIEW_AVAILABLE = True
    _WEBVIEW_IMPORT_ERROR = None
except ImportError as e:
    WEBVIEW_AVAILABLE = False
    _WEBVIEW_IMPORT_ERROR = str(e)
    print("[Warning] pywebview not available, using browser fallback")

import pystray
from PIL import Image

from backend.api_server import app as fastapi_app, schedule_broadcast
from backend.app_runtime import RuntimeCoordinator
from backend.config import AppConfig
from backend.focus_time import is_in_block_time

# Silence pywebview error spam (native object introspection).
logging.getLogger("pywebview").disabled = True
logging.getLogger("webview").disabled = True
_pywebview_noise = [
    "[pywebview] Error while processing app.window.native.",
    "maximum recursion depth exceeded while calling a Python object",
    "AccessibilityObject.Bounds",
    "__abstractmethods__",
    "CoreWebView2 members can only be accessed",
    "AllowExternalDrop",
    "ICoreWebView2Controller",
    "System.__ComObject",
]
sys.stdout = _StreamFilter(sys.stdout, _pywebview_noise)
sys.stderr = _StreamFilter(sys.stderr, _pywebview_noise)
from backend.import_export import ImportExportManager


class PyWebViewApi:
    """PyWebView JavaScript API - 네이티브 다이얼로그 제공"""

    def __init__(self, app: 'ActivityTrackerApp'):
        self.app = app

    def save_backup(self, include_media: bool = True) -> dict:
        """DB 백업 - 저장 다이얼로그로 경로 선택"""
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            default_name = (
                f"activity_tracker_backup_{timestamp}.zip"
                if include_media
                else f"activity_tracker_backup_{timestamp}.db"
            )

            result = self.app.window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=default_name,
                file_types=(
                    'Backup Files (*.zip)'
                    if include_media
                    else 'Database Files (*.db)',
                    'All files (*.*)'
                )
            )

            if not result:
                return {"success": False, "message": "취소됨"}

            save_path = result if isinstance(result, str) else result[0]

            ie_manager = ImportExportManager(self.app.db_manager)
            if include_media:
                success = ie_manager.export_full_backup(save_path)
            else:
                success = ie_manager.export_database(save_path)

            if success:
                return {"success": True, "message": f"백업 완료: {save_path}"}
            else:
                return {"success": False, "message": "백업 실패"}

        except Exception as e:
            return {"success": False, "message": f"오류: {str(e)}"}

    def save_rules_export(self) -> dict:
        """룰 내보내기 - 저장 다이얼로그로 경로 선택"""
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            default_name = f"rules_export_{timestamp}.json"

            result = self.app.window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=default_name,
                file_types=('JSON Files (*.json)', 'All files (*.*)')
            )

            if not result:
                return {"success": False, "message": "취소됨"}

            save_path = result if isinstance(result, str) else result[0]

            ie_manager = ImportExportManager(self.app.db_manager)
            success = ie_manager.export_rules(save_path)

            if success:
                tags = self.app.db_manager.get_all_tags()
                rules = self.app.db_manager.get_all_rules()
                return {
                    "success": True,
                    "message": f"내보내기 완료: {save_path}",
                    "stats": {"tags": len(tags), "rules": len(rules)}
                }
            else:
                return {"success": False, "message": "내보내기 실패"}

        except Exception as e:
            return {"success": False, "message": f"오류: {str(e)}"}

    def exit_app(self) -> dict:
        """앱 종료"""
        print("[PyWebViewApi] exit_app called")
        try:
            self.app.quit_app()
            return {"success": True}
        except Exception as e:
            print(f"[PyWebViewApi] exit_app error: {e}")
            return {"success": False, "message": str(e)}


class ActivityTrackerApp:
    """PyWebView 기반 Activity Tracker 앱"""

    def __init__(self):
        self.window = None
        self.tray_icon = None
        self._api_pid_path = AppConfig.get_api_pid_path()
        self.running = True
        self._webview_loaded = threading.Event()

        # 포트 설정
        self.api_port = 8000
        self.webui_url = self._get_webui_url()
        self._webview_profile_dir = AppConfig.get_app_dir() / "webview_profile"
        self.runtime = RuntimeCoordinator(
            fastapi_app=fastapi_app,
            api_port=self.api_port,
            exit_callback=self.quit_app,
            on_activity_detected=self._on_activity_detected,
            on_toast_requested=self._on_toast_requested,
        )

    @property
    def api_server_thread(self):
        return self.runtime.api_server_thread

    @property
    def monitor_engine(self):
        return self.runtime.monitor_engine

    @property
    def db_manager(self):
        return self.runtime.db_manager

    @property
    def log_generator(self):
        return self.runtime.log_generator

    def _get_webui_url(self) -> str:
        """웹 UI URL 결정"""
        # 개발 모드: Vite dev server
        if os.environ.get('DEV_MODE') == '1':
            return 'http://localhost:5173'

        # 프로덕션: FastAPI가 dist를 서빙
        return f'http://127.0.0.1:{self.api_port}'

    def start_api_server(self):
        """FastAPI 서버를 스레드로 실행"""
        self.runtime.start_api_server()

    def start_monitor_engine(self):
        """모니터링 엔진 시작"""
        self.runtime.start_monitoring()

    def _check_dist_timestamp(self) -> tuple[str, str]:
        """dist 폴더 타임스탬프 확인"""
        dist_dir = Path(__file__).parent / "webui" / "dist"
        index_file = dist_dir / "index.html"

        if not dist_dir.exists():
            return "NOT_FOUND", ""

        if index_file.exists():
            mtime = index_file.stat().st_mtime
            build_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            return "OK", build_time

        return "NO_INDEX", ""

    def _wait_for_api_ready(self, timeout: float = 10.0) -> bool:
        """API 서버 준비 대기"""
        return self.runtime.wait_for_api_ready(self._check_dist_timestamp, timeout=timeout)

    def _on_activity_detected(self, activity_info: dict):
        """활동 감지 시 WebSocket으로 브로드캐스트"""
        try:
            schedule_broadcast({
                "type": "activity_update",
                "data": activity_info
            })
        except Exception as e:
            print(f"[WebSocket] Broadcast error: {e}")

    def _on_toast_requested(self, tag_id: int, message: str, cooldown: int):
        """토스트 알림 요청 처리"""
        try:
            # NotificationManager는 MonitorEngine 내부에 있음
            self.monitor_engine.notification_manager.show(
                tag_id=tag_id,
                title="Activity Tracker",
                message=message,
                cooldown=cooldown
            )
        except Exception as e:
            print(f"[Notification] Error: {e}")

    def create_tray_icon(self):
        """시스템 트레이 아이콘 생성"""
        # 아이콘 이미지 생성 (간단한 녹색 원)
        icon_path = Path(__file__).parent / 'resources' / 'icon.png'
        if icon_path.exists():
            image = Image.open(icon_path)
        else:
            # 기본 아이콘 생성
            image = Image.new('RGB', (64, 64), color='#4CAF50')

        menu = pystray.Menu(
            pystray.MenuItem("열기", self.show_window, default=True),
            pystray.MenuItem("종료", self.quit_app)
        )

        self.tray_icon = pystray.Icon(
            "ActivityTracker",
            image,
            "Activity Tracker",
            menu
        )

    def show_window(self, icon=None, item=None):
        """윈도우 표시"""
        if self.window:
            self.window.show()
            self.window.restore()

    def hide_window(self):
        """윈도우 숨기기 (트레이로)"""
        if self.window:
            self.window.hide()

    def _get_active_focus_blocks(self) -> list:
        """현재 활성화된 집중 모드 차단 목록 조회"""
        if not self.db_manager:
            return []

        try:
            tags = self.db_manager.get_all_tags()
            active_blocks = []

            for tag in tags:
                if not tag.get('block_enabled'):
                    continue
                if tag['name'] in ('자리비움', '미분류'):
                    continue

                start_time = tag.get('block_start_time')
                end_time = tag.get('block_end_time')

                if not start_time or not end_time:
                    continue

                if is_in_block_time(start_time, end_time):
                    active_blocks.append(tag['name'])

            return active_blocks
        except Exception as e:
            print(f"[App] Error checking focus blocks: {e}")
            return []

    def _confirm_and_quit_from_tray(self, active_blocks: list):
        """트레이에서 종료 시 별도 스레드에서 확인 후 종료"""
        MB_YESNO = 0x04
        MB_ICONWARNING = 0x30
        MB_SYSTEMMODAL = 0x1000
        MB_SETFOREGROUND = 0x10000
        IDYES = 6

        message = (
            f"현재 집중 모드가 활성화되어 있습니다!\n\n"
            f"차단 중인 태그: {', '.join(active_blocks)}\n\n"
            f"앱을 종료하면 집중 모드가 해제됩니다.\n"
            f"정말로 종료하시겠습니까?"
        )

        result = ctypes.windll.user32.MessageBoxW(
            0, message, "Activity Tracker 종료",
            MB_YESNO | MB_ICONWARNING | MB_SYSTEMMODAL | MB_SETFOREGROUND
        )

        if result == IDYES:
            self._do_quit()

    def _do_quit(self):
        """실제 종료 수행"""
        self.running = False

        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except Exception as e:
            print(f"[App] Tray stop error: {e}")

        try:
            if self.window:
                self.window.destroy()
        except Exception as e:
            print(f"[App] Window destroy error: {e}")

        self.runtime.stop(self._api_pid_path)

        print("[App] Shutting down...")
        os._exit(0)

    def quit_app(self, icon=None, item=None):
        """앱 종료"""
        # 트레이에서 호출된 경우 집중 모드 체크
        if icon is not None:
            active_blocks = self._get_active_focus_blocks()
            if active_blocks:
                # 별도 스레드에서 확인창 띄우기 (트레이 메뉴가 먼저 닫히도록)
                threading.Thread(
                    target=self._confirm_and_quit_from_tray,
                    args=(active_blocks,),
                    daemon=True
                ).start()
                return  # 트레이 콜백 즉시 반환

        self._do_quit()

    def on_closing(self):
        """창 닫기 이벤트 핸들러"""
        # 창을 닫으면 트레이로 최소화
        self.hide_window()
        return False  # 창 닫기 방지

    def run_tray(self):
        """트레이 아이콘 실행 (별도 스레드)"""
        self.create_tray_icon()
        self.tray_icon.run()

    def run(self):
        """앱 실행"""
        print("[App] Starting Activity Tracker (PyWebView Edition)")
        start_ts = time.perf_counter()

        def _log_step(label: str, step_start: float, step_end: float = None):
            end_ts = step_end if step_end is not None else time.perf_counter()
            elapsed = end_ts - step_start
            total_elapsed = end_ts - start_ts
            msg = f"[Startup] {label} took {elapsed:.3f}s (total {total_elapsed:.3f}s)"
            print(msg)
            logging.info(msg)

        # Reduce noisy pywebview native introspection logs.
        logging.getLogger("pywebview").setLevel(logging.ERROR)
        logging.getLogger("webview").setLevel(logging.ERROR)

        # API 서버 시작
        step_ts = time.perf_counter()
        self.start_api_server()
        time.sleep(1)  # 서버 시작 대기
        _log_step("API server start + initial sleep", step_ts)

        step_ts = time.perf_counter()
        if not self._wait_for_api_ready(timeout=12.0):
            _log_step("API health check (failed)", step_ts)
            logging.error("[API Server] Health check failed")
            self.runtime.stop(self._api_pid_path)
            ctypes.windll.user32.MessageBoxW(
                0,
                "API server did not respond. Please restart the app.",
                "Activity Tracker",
                0x10 | 0x1000
            )
            return
        _log_step("API health check (ok)", step_ts)

        # 모니터링 엔진 시작
        step_ts = time.perf_counter()
        self.start_monitor_engine()
        _log_step("Monitor engine start", step_ts)

        # 트레이 아이콘 시작 (별도 스레드)
        step_ts = time.perf_counter()
        tray_thread = threading.Thread(target=self.run_tray, daemon=True)
        tray_thread.start()
        _log_step("Tray thread start", step_ts)

        # JS API 인스턴스 생성
        step_ts = time.perf_counter()
        self.js_api = PyWebViewApi(self)
        _log_step("JS API init", step_ts)

        # PyWebView 창 생성
        step_ts = time.perf_counter()
        self.window = webview.create_window(
            title="Activity Tracker",
            url=self.webui_url,
            width=1200,
            height=800,
            min_size=(800, 600),
            resizable=True,
            confirm_close=True,
            js_api=self.js_api
        )
        _log_step("WebView window created", step_ts)

        # 창 닫기 이벤트
        self.window.events.closing += self.on_closing
        # WebView 이벤트 로그
        def _log_webview_event(name: str):
            msg = f"[WebView] event: {name}"
            print(msg)
            logging.info(msg)

        if getattr(self.window, "events", None):
            if getattr(self.window.events, "shown", None):
                self.window.events.shown += lambda: _log_webview_event("shown")
            if getattr(self.window.events, "loaded", None):
                def _on_loaded():
                    self._webview_loaded.set()
                    _log_webview_event("loaded")
                self.window.events.loaded += _on_loaded
            if getattr(self.window.events, "closed", None):
                self.window.events.closed += lambda: _log_webview_event("closed")
            if getattr(self.window.events, "minimized", None):
                self.window.events.minimized += lambda: _log_webview_event("minimized")
            if getattr(self.window.events, "restored", None):
                self.window.events.restored += lambda: _log_webview_event("restored")

        def _webview_watchdog():
            checkpoints = [2, 5, 10, 15, 20]
            last = 0.0
            for checkpoint in checkpoints:
                if self._webview_loaded.wait(timeout=checkpoint - last):
                    return
                last = checkpoint
                try:
                    current_url = self.window.get_current_url()
                except Exception as e:
                    current_url = f"unavailable ({e})"
                msg = f"[WebView] still loading after {checkpoint}s (url={current_url})"
                print(msg)
                logging.info(msg)

        threading.Thread(target=_webview_watchdog, daemon=True).start()

        # WebView 시작 (메인 스레드에서 실행)
        # EdgeChromium 백엔드 사용 (Windows 10/11 기본 탑재)
        step_ts = time.perf_counter()
        print("[Startup] Entering webview.start (UI loop)")
        logging.info("[Startup] Entering webview.start (UI loop)")
        webview.start(
            debug=(
                os.environ.get('DEV_MODE') == '1'
                or os.environ.get('WEBVIEW_DEBUG') == '1'
            ),
            gui='edgechromium',
            storage_path=str(self._webview_profile_dir)
        )
        _log_step("webview.start returned", step_ts)


def is_port_in_use(port: int) -> bool:
    """포트가 사용 중인지 확인"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return False
        except OSError:
            return True


def ensure_single_instance() -> bool:
    """중복 실행 방지 (Windows mutex)"""
    mutex_name = "Global\\ActivityTracker_SingleInstance"
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    if not handle:
        return True  # 실패 시 앱 실행 허용

    ERROR_ALREADY_EXISTS = 183
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False

    return True


def activate_existing_window() -> bool:
    """이미 실행 중인 창을 활성화"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "Activity Tracker")
        if not hwnd:
            return False

        SW_SHOW = 5
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_SHOW)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def main():
    """메인 함수"""
    from logging.handlers import RotatingFileHandler

    log_path = AppConfig.get_log_path()
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    file_handler = RotatingFileHandler(
        str(log_path),
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    logging.getLogger("pywebview").setLevel(logging.CRITICAL)
    logging.getLogger("webview").setLevel(logging.CRITICAL)
    log_filter = _LogFilter(_pywebview_noise)
    root_logger.addFilter(log_filter)
    for handler in root_logger.handlers:
        handler.addFilter(log_filter)
    logging.getLogger("pywebview").addFilter(log_filter)
    logging.getLogger("webview").addFilter(log_filter)

    if not WEBVIEW_AVAILABLE and _WEBVIEW_IMPORT_ERROR:
        logging.error("[App] pywebview import failed: %s", _WEBVIEW_IMPORT_ERROR)

    # 이전 API 프로세스의 PID 파일이 남아있으면 정리
    api_pid_path = AppConfig.get_api_pid_path()
    if api_pid_path.exists():
        try:
            api_pid_path.unlink()
        except Exception:
            pass

    # 중복 실행 방지 (포트 열기 전 mutex 체크)
    if not ensure_single_instance():
        logging.warning("[App] Already running (mutex exists). Exiting.")
        activate_existing_window()
        print("[App] Already running (mutex exists). Exiting.")
        sys.exit(0)

    # 중복 실행 방지 (포트 8000 체크)
    if is_port_in_use(8000):
        logging.warning("[App] Port 8000 in use. Exiting.")
        print("[App] Already running (port 8000 in use). Exiting.")
        sys.exit(0)

    # 복원 예약이 있으면 앱 시작 전에 적용
    pending_meta_path = AppConfig.get_restore_pending_path()
    pending_db_path = AppConfig.get_restore_pending_db_path()
    pending_zip_path = AppConfig.get_restore_pending_media_path()
    if pending_meta_path.exists():
        applied = False
        if pending_zip_path.exists():
            try:
                with zipfile.ZipFile(pending_zip_path, 'r') as zip_file:
                    if "activity_tracker.db" not in zip_file.namelist():
                        raise RuntimeError("Missing activity_tracker.db in pending zip")
                    with tempfile.TemporaryDirectory() as temp_dir:
                        zip_file.extract("activity_tracker.db", temp_dir)
                        for name in zip_file.namelist():
                            if name.startswith("images/") or name.startswith("sounds/"):
                                zip_file.extract(name, temp_dir)

                        temp_dir_path = Path(temp_dir)
                        temp_db_path = temp_dir_path / "activity_tracker.db"
                        conn = sqlite3.connect(str(temp_db_path))
                        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                        conn.close()
                        if result != "ok":
                            print(f"[Restore] Pending ZIP DB integrity failed: {result}")
                            logging.warning("[Restore] Pending ZIP DB integrity failed: %s", result)
                        else:
                            db_path = AppConfig.get_db_path()
                            wal_path = db_path.with_suffix(".db-wal")
                            shm_path = db_path.with_suffix(".db-shm")
                            if wal_path.exists():
                                wal_path.unlink()
                            if shm_path.exists():
                                shm_path.unlink()
                            shutil.copy2(temp_db_path, db_path)

                            images_src = temp_dir_path / "images"
                            sounds_src = temp_dir_path / "sounds"
                            images_dest = AppConfig.get_images_dir()
                            sounds_dest = AppConfig.get_sounds_dir()
                            if images_src.exists():
                                for image in images_src.rglob("*"):
                                    if image.is_file():
                                        rel_path = image.relative_to(images_src)
                                        target_path = images_dest / rel_path
                                        target_path.parent.mkdir(parents=True, exist_ok=True)
                                        shutil.copy2(image, target_path)
                            if sounds_src.exists():
                                for sound in sounds_src.rglob("*"):
                                    if sound.is_file():
                                        rel_path = sound.relative_to(sounds_src)
                                        target_path = sounds_dest / rel_path
                                        target_path.parent.mkdir(parents=True, exist_ok=True)
                                        shutil.copy2(sound, target_path)

                            applied = True
                            print("[Restore] Pending ZIP applied successfully")
            except Exception as e:
                print(f"[Restore] Pending ZIP apply failed: {e}")
                logging.warning("[Restore] Pending ZIP apply failed: %s", e)
        elif pending_db_path.exists():
            try:
                conn = sqlite3.connect(str(pending_db_path))
                result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                conn.close()
                if result != "ok":
                    print(f"[Restore] Pending DB integrity failed: {result}")
                    logging.warning("[Restore] Pending DB integrity failed: %s", result)
                else:
                    db_path = AppConfig.get_db_path()
                    wal_path = db_path.with_suffix(".db-wal")
                    shm_path = db_path.with_suffix(".db-shm")
                    if wal_path.exists():
                        wal_path.unlink()
                    if shm_path.exists():
                        shm_path.unlink()
                    shutil.copy2(pending_db_path, db_path)
                    applied = True
                    print("[Restore] Pending DB applied successfully")
            except Exception as e:
                print(f"[Restore] Pending DB apply failed: {e}")
                logging.warning("[Restore] Pending DB apply failed: %s", e)
        else:
            logging.warning("[Restore] Pending metadata exists, but no pending backup found.")

        if applied:
            try:
                if pending_zip_path.exists():
                    pending_zip_path.unlink()
                if pending_db_path.exists():
                    pending_db_path.unlink()
                pending_meta_path.unlink()
            except Exception as e:
                print(f"[Restore] Pending cleanup failed: {e}")
                logging.warning("[Restore] Pending cleanup failed: %s", e)

    # 개발 모드 설정
    if '--dev' in sys.argv:
        os.environ['DEV_MODE'] = '1'
        print("[Mode] Development mode enabled")

    app = ActivityTrackerApp()

    # Ctrl+C 핸들러
    def signal_handler(signum, frame):
        print("\n[App] Ctrl+C received, shutting down...")
        app.quit_app()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app.run()


if __name__ == "__main__":
    main()
