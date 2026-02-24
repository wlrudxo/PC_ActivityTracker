"""
애플리케이션 설정 및 경로 관리
"""
import os
import sys
from pathlib import Path


class AppConfig:
    """
    애플리케이션 설정 및 경로 관리

    개발 모드 vs 빌드 모드 자동 구분:
    - 개발 중: 프로젝트 폴더에 DB/설정 저장 (디버깅 편함)
    - 빌드 후: AppData에 저장 (Windows 표준)
    """

    @staticmethod
    def is_dev_mode():
        """
        개발 모드 체크
        PyInstaller로 빌드되면 sys.frozen = True
        """
        return not getattr(sys, 'frozen', False)

    @staticmethod
    def get_app_dir():
        """
        애플리케이션 데이터 디렉토리

        개발 모드:
            H:\\GitProject\\PC_ScreenCapture\\

        빌드 모드:
            C:\\Users\\User\\AppData\\Roaming\\ActivityTracker\\
        """
        if AppConfig.is_dev_mode():
            # 개발 중: 프로젝트 폴더
            return Path(__file__).parent.parent
        else:
            # 빌드 후: AppData
            if os.name == 'nt':  # Windows
                app_dir = Path(os.getenv('APPDATA')) / "ActivityTracker"
            else:  # macOS, Linux
                app_dir = Path.home() / ".activitytracker"

            app_dir.mkdir(parents=True, exist_ok=True)
            return app_dir

    @staticmethod
    def get_db_path():
        """SQLite DB 파일 경로"""
        return AppConfig.get_app_dir() / "activity_tracker.db"

    @staticmethod
    def get_config_path():
        """설정 파일 경로 (JSON)"""
        return AppConfig.get_app_dir() / "config.json"

    @staticmethod
    def get_log_dir():
        """로그 디렉토리"""
        log_dir = AppConfig.get_app_dir() / "logs"
        log_dir.mkdir(exist_ok=True)
        return log_dir

    @staticmethod
    def get_log_path():
        """로그 파일 경로"""
        return AppConfig.get_log_dir() / "app.log"

    @staticmethod
    def get_sounds_dir():
        """알림음 저장 디렉토리"""
        sounds_dir = AppConfig.get_app_dir() / "sounds"
        sounds_dir.mkdir(exist_ok=True)
        return sounds_dir

    @staticmethod
    def get_images_dir():
        """알림 이미지 저장 디렉토리"""
        images_dir = AppConfig.get_app_dir() / "images"
        images_dir.mkdir(exist_ok=True)
        return images_dir

    @staticmethod
    def get_activity_logs_dir():
        """활동 로그 디렉토리 (LLM 분석용)"""
        logs_dir = AppConfig.get_app_dir() / "activity_logs"
        logs_dir.mkdir(exist_ok=True)
        return logs_dir

    @staticmethod
    def get_daily_logs_dir():
        """일별 로그 디렉토리"""
        daily_dir = AppConfig.get_activity_logs_dir() / "daily"
        daily_dir.mkdir(exist_ok=True)
        return daily_dir

    @staticmethod
    def get_monthly_logs_dir():
        """월별 아카이브 디렉토리"""
        monthly_dir = AppConfig.get_activity_logs_dir() / "monthly"
        monthly_dir.mkdir(exist_ok=True)
        return monthly_dir

    @staticmethod
    def get_recent_log_path():
        """최근 N일 통합 로그 경로"""
        return AppConfig.get_activity_logs_dir() / "recent.log"

    @staticmethod
    def get_restore_pending_path():
        """복원 예약 메타 파일 경로"""
        return AppConfig.get_app_dir() / "restore_pending.json"

    @staticmethod
    def get_restore_pending_db_path():
        """복원 예약 DB 파일 경로"""
        return AppConfig.get_app_dir() / "restore_pending.db"

    @staticmethod
    def get_restore_pending_media_path():
        """복원 예약 미디어 백업 파일 경로 (zip)"""
        return AppConfig.get_app_dir() / "restore_pending.zip"

    @staticmethod
    def get_api_pid_path():
        """API 프로세스 PID 파일 경로"""
        return AppConfig.get_app_dir() / "api.pid"
