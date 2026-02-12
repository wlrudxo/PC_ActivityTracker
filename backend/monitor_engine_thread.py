"""
모니터링 엔진 - threading 기반 (PyWebView용)

PyQt6의 QThread 대신 표준 라이브러리 threading 사용.
pyqtSignal 대신 콜백 함수 방식으로 이벤트 전달.
"""
import time
import random
import threading
from datetime import date, timedelta
from typing import Dict, Any, Optional, Callable

from backend.window_tracker import WindowTracker
from backend.screen_detector import ScreenDetector
from backend.chrome_receiver import ChromeURLReceiver
from backend.notification_manager import NotificationManager
from backend.focus_blocker import FocusBlocker


class MonitorEngineThread(threading.Thread):
    """
    백그라운드 스레드로 실행되는 모니터링 엔진

    - 활성 창 감지 (설정 가능한 폴링 간격)
    - 화면 잠금/idle 감지
    - Chrome URL 수신
    - 룰 엔진으로 분류 → DB 저장
    - 콜백으로 UI 및 알림 이벤트 전달
    """

    # 기본값 (DB 설정이 없을 때 사용)
    DEFAULT_POLLING_INTERVAL = 2
    DEFAULT_IDLE_THRESHOLD = 300

    def __init__(
        self,
        db_manager,
        rule_engine,
        on_activity_detected: Optional[Callable[[dict], None]] = None,
        on_toast_requested: Optional[Callable[[int, str, int], None]] = None,
        log_generator=None
    ):
        """
        모니터링 엔진 초기화

        Args:
            db_manager: DatabaseManager 인스턴스
            rule_engine: RuleEngine 인스턴스
            on_activity_detected: 활동 감지 시 호출될 콜백 (activity_info)
            on_toast_requested: 토스트 알림 요청 시 호출될 콜백 (tag_id, message, cooldown)
            log_generator: ActivityLogGenerator 인스턴스 (날짜 변경 시 로그 생성용)
        """
        super().__init__(daemon=True)

        self.db_manager = db_manager
        self.rule_engine = rule_engine
        self.log_generator = log_generator

        # 콜백 함수
        self._on_activity_detected = on_activity_detected
        self._on_toast_requested = on_toast_requested

        # 날짜 변경 감지용
        self._current_date = date.today()
        self._last_date_check_time = 0.0
        self._DATE_CHECK_INTERVAL = 60  # 1분마다 체크

        # 모듈 초기화
        self.window_tracker = WindowTracker()
        self.screen_detector = ScreenDetector()
        self.chrome_receiver = ChromeURLReceiver(port=8766)
        self.notification_manager = NotificationManager(
            get_sound_settings=self._get_sound_settings,
            get_toast_enabled=self._get_toast_enabled,
            get_image_settings=self._get_image_settings
        )
        self.focus_blocker = FocusBlocker(db_manager)

        # 상태 변수
        self.current_activity_id: Optional[int] = None
        self.current_tag_id: Optional[int] = None
        self.current_hwnd: Optional[int] = None
        self.last_activity_info: Optional[Dict[str, Any]] = None
        self._running = False
        self._stop_event = threading.Event()
        self._last_played_sound_id: Optional[int] = None
        self._last_shown_image_id: Optional[int] = None

        # 프로그램 시작 시 종료되지 않은 활동 정리
        self.db_manager.cleanup_unfinished_activities()

    def _get_polling_interval(self) -> int:
        """폴링 간격 설정 조회 (초)"""
        try:
            value = self.db_manager.get_setting('polling_interval')
            return int(value) if value else self.DEFAULT_POLLING_INTERVAL
        except Exception:
            return self.DEFAULT_POLLING_INTERVAL

    def _get_idle_threshold(self) -> int:
        """유휴 상태 임계값 설정 조회 (초)"""
        try:
            value = self.db_manager.get_setting('idle_threshold')
            return int(value) if value else self.DEFAULT_IDLE_THRESHOLD
        except Exception:
            return self.DEFAULT_IDLE_THRESHOLD

    def run(self):
        """스레드 메인 루프"""
        self._running = True
        self._stop_event.clear()
        print("[MonitorEngine] 모니터링 시작")

        while not self._stop_event.is_set():
            try:

                # 설정값 조회 (매 루프마다 최신값 반영)
                polling_interval = self._get_polling_interval()

                # 날짜 변경 체크 (1분마다)
                self._check_date_change()

                # 현재 활동 정보 수집
                activity_info = self.collect_activity_info()

                # 활동이 변경되었으면 이전 활동 종료 + 새 활동 시작
                if self._is_activity_changed(activity_info):
                    self.end_current_activity()
                    self.start_new_activity(activity_info)
                    self.last_activity_info = activity_info
                elif self.current_tag_id is not None:
                    # 동일 활동이어도 알림 체크 (쿨다운이 중복 알림 방지)
                    self._check_tag_alert(self.current_tag_id)
                    # 차단 체크 (사용자가 최소화된 창을 다시 열었을 경우)
                    hwnd = activity_info.get('hwnd')
                    if hwnd:
                        process_name = activity_info.get('process_name', '')
                        self.focus_blocker.check_and_block(self.current_tag_id, hwnd, process_name)

                # 설정된 폴링 간격만큼 대기
                self._stop_event.wait(timeout=polling_interval)

            except Exception as e:
                print(f"[MonitorEngine] 오류 발생: {e}")
                self._stop_event.wait(timeout=self.DEFAULT_POLLING_INTERVAL)

        self._running = False
        try:
            self.db_manager.close()
        except Exception as e:
            print(f"[MonitorEngine] DB close warning: {e}")
        print("[MonitorEngine] 루프 종료")

    def _check_date_change(self):
        """날짜 변경 감지 및 로그 생성"""
        now = time.time()
        if now - self._last_date_check_time < self._DATE_CHECK_INTERVAL:
            return

        self._last_date_check_time = now
        today = date.today()

        if today != self._current_date:
            yesterday = self._current_date
            self._current_date = today
            print(f"[MonitorEngine] 날짜 변경 감지: {yesterday} → {today}")

            # 어제 로그 생성 (백그라운드)
            if self.log_generator:
                def generate_logs():
                    try:
                        self.log_generator.save_daily_log(yesterday)
                        self.log_generator.generate_recent_log()
                        print(f"[MonitorEngine] {yesterday} 로그 생성 완료")
                    except Exception as e:
                        print(f"[MonitorEngine] 로그 생성 오류: {e}")

                threading.Thread(target=generate_logs, daemon=True).start()

    def stop(self, timeout: float = 5.0):
        """
        모니터링 종료

        Args:
            timeout: 스레드 종료 대기 시간 (초)
        """
        print("[MonitorEngine] 종료 요청됨")
        self._stop_event.set()

        # 스레드가 종료될 때까지 대기
        if self.is_alive():
            self.join(timeout=timeout)

        if self.is_alive():
            print("[MonitorEngine] 경고: 스레드가 시간 내에 종료되지 않음")

        # WebSocket 서버 종료
        self.chrome_receiver.stop()

        self.end_current_activity()
        print("[MonitorEngine] 모니터링 종료 완료")

    @property
    def running(self) -> bool:
        """모니터링 실행 중 여부"""
        return self._running

    def collect_activity_info(self) -> Dict[str, Any]:
        """
        현재 활동 정보 수집

        Returns:
            dict: {
                'process_name': str,
                'window_title': str,
                'chrome_url': Optional[str],
                'chrome_profile': Optional[str],
                'process_path': Optional[str],
                'hwnd': Optional[int]
            }
        """
        # 1. 최우선: 화면 잠금 상태
        if self.screen_detector.is_locked():
            return {
                'process_name': '__LOCKED__',
                'window_title': 'Screen Locked',
                'chrome_url': None,
                'chrome_profile': None,
                'hwnd': None,
            }

        # 2. 유휴(idle) 상태 체크
        idle_seconds = self.screen_detector.get_idle_duration()
        idle_threshold = self._get_idle_threshold()
        if idle_seconds > idle_threshold:
            return {
                'process_name': '__IDLE__',
                'window_title': 'Idle',
                'chrome_url': None,
                'chrome_profile': None,
                'hwnd': None,
            }

        # 3. 일반 활동
        window_info = self.window_tracker.get_active_window()
        if not window_info:
            return {
                'process_name': '__UNKNOWN__',
                'window_title': 'Unknown',
                'chrome_url': None,
                'chrome_profile': None,
                'hwnd': None,
            }

        # Chrome URL 데이터 가져오기 (Chrome 프로세스일 때만)
        chrome_data = None
        process_name_lower = window_info['process_name'].lower()
        if 'chrome' in process_name_lower:
            chrome_data = self.chrome_receiver.get_latest_url()
            if chrome_data:
                # 검증: Extension에서 온 title이 현재 window title에 포함되는지 확인
                ext_title = chrome_data.get('title', '')
                window_title = window_info['window_title']

                if ext_title and ext_title not in window_title:
                    print(f"[MonitorEngine] Chrome URL 무시 (title 불일치)")
                    chrome_data = None
                else:
                    profile = chrome_data.get('profile', 'N/A')
                    url = chrome_data.get('url', 'N/A')
                    print(f"[MonitorEngine] Chrome 감지 - 프로필: [{profile}] URL: {url}")

        return {
            'process_name': window_info['process_name'],
            'window_title': window_info['window_title'],
            'chrome_url': chrome_data.get('url') if chrome_data else None,
            'chrome_profile': chrome_data.get('profile') if chrome_data else None,
            'process_path': window_info.get('process_path'),
            'hwnd': window_info.get('hwnd'),
        }

    def _is_activity_changed(self, new_info: Dict[str, Any]) -> bool:
        """활동이 변경되었는지 체크"""
        if self.last_activity_info is None:
            return True

        if new_info['process_name'] != self.last_activity_info['process_name']:
            return True

        # 특수 상태는 process_name만 비교
        if new_info['process_name'] in ('__IDLE__', '__LOCKED__'):
            return False

        # 일반 활동은 window_title과 chrome_url도 비교
        return (
            new_info['window_title'] != self.last_activity_info['window_title'] or
            new_info['chrome_url'] != self.last_activity_info['chrome_url']
        )

    def start_new_activity(self, info: Dict[str, Any]):
        """새 활동 시작 → DB 저장 → 알림 체크"""
        try:
            # 룰 엔진으로 태그 분류
            tag_id, rule_id = self.rule_engine.match(info)
            self.current_tag_id = tag_id

            # DB에 새 활동 저장
            self.current_activity_id = self.db_manager.create_activity(
                process_name=info['process_name'],
                window_title=info['window_title'],
                process_path=info.get('process_path'),
                chrome_url=info['chrome_url'],
                chrome_profile=info['chrome_profile'],
                tag_id=tag_id,
                rule_id=rule_id
            )

            # 콜백으로 활동 감지 알림
            if self._on_activity_detected:
                self._on_activity_detected(info)

            print(f"[MonitorEngine] 새 활동 시작: {info['process_name']} - {info['window_title'][:50]}")

            # 태그 알림 체크
            self._check_tag_alert(tag_id)

            # 태그 차단 체크
            hwnd = info.get('hwnd')
            if hwnd:
                process_name = info.get('process_name', '')
                self.focus_blocker.check_and_block(tag_id, hwnd, process_name)

        except Exception as e:
            print(f"[MonitorEngine] 활동 저장 오류: {e}")

    def _check_tag_alert(self, tag_id: int):
        """태그 알림 설정 확인 및 콜백 호출"""
        try:
            tag = self.db_manager.get_tag_by_id(tag_id)
            if tag and tag.get('alert_enabled'):
                message = tag.get('alert_message') or f"'{tag['name']}' 활동이 감지되었습니다!"
                cooldown = tag.get('alert_cooldown') or 30

                # 콜백으로 알림 요청
                if self._on_toast_requested:
                    self._on_toast_requested(tag_id, message, cooldown)
        except Exception as e:
            print(f"[MonitorEngine] 알림 체크 오류: {e}")

    def _get_toast_enabled(self) -> bool:
        """윈도우 토스트 활성화 여부 조회"""
        try:
            return self.db_manager.get_setting('alert_toast_enabled', '1') == '1'
        except Exception as e:
            print(f"[MonitorEngine] 토스트 설정 조회 오류: {e}")
            return True

    def _get_sound_settings(self) -> tuple:
        """알림음 설정 조회"""
        try:
            enabled = self.db_manager.get_setting('alert_sound_enabled', '0') == '1'
            if not enabled:
                return (False, None)

            play_mode = self.db_manager.get_setting('alert_sound_mode', 'single')
            sounds = self.db_manager.get_all_alert_sounds()

            if not sounds:
                return (True, None)

            if play_mode == 'random':
                if len(sounds) >= 2 and self._last_played_sound_id is not None:
                    candidates = [s for s in sounds if s['id'] != self._last_played_sound_id]
                    selected = random.choice(candidates) if candidates else random.choice(sounds)
                else:
                    selected = random.choice(sounds)
                self._last_played_sound_id = selected['id']
                return (True, selected['file_path'])
            else:
                selected_id = self.db_manager.get_setting('alert_sound_selected', None)
                if selected_id:
                    sound = self.db_manager.get_alert_sound_by_id(int(selected_id))
                    if sound:
                        return (True, sound['file_path'])
                return (True, sounds[0]['file_path'])

        except Exception as e:
            print(f"[MonitorEngine] 사운드 설정 조회 오류: {e}")
            return (False, None)

    def _get_image_settings(self) -> tuple:
        """알림 이미지 설정 조회"""
        try:
            enabled = self.db_manager.get_setting('alert_image_enabled', '0') == '1'
            if not enabled:
                return (False, None)

            display_mode = self.db_manager.get_setting('alert_image_mode', 'single')
            images = self.db_manager.get_all_alert_images()

            if not images:
                return (True, None)

            if display_mode == 'random':
                if len(images) >= 2 and self._last_shown_image_id is not None:
                    candidates = [i for i in images if i['id'] != self._last_shown_image_id]
                    selected = random.choice(candidates) if candidates else random.choice(images)
                else:
                    selected = random.choice(images)
                self._last_shown_image_id = selected['id']
                return (True, selected['file_path'])
            else:
                selected_id = self.db_manager.get_setting('alert_image_selected', None)
                if selected_id:
                    selected = self.db_manager.get_alert_image_by_id(int(selected_id))
                    if selected:
                        return (True, selected['file_path'])
                return (True, images[0]['file_path'])

        except Exception as e:
            print(f"[MonitorEngine] 이미지 설정 조회 오류: {e}")
            return (False, None)

    def end_current_activity(self):
        """현재 활동 종료"""
        if self.current_activity_id is not None:
            try:
                self.db_manager.end_activity(self.current_activity_id)
                print(f"[MonitorEngine] 활동 종료: ID {self.current_activity_id}")
                self.current_activity_id = None
                self.current_tag_id = None
            except Exception as e:
                print(f"[MonitorEngine] 활동 종료 오류: {e}")
