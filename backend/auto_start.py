"""
Windows 시작 프로그램 등록/해제
"""
import os
import sys
import winreg


class AutoStartManager:
    r"""
    Windows 시작 프로그램 관리

    HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run에
    레지스트리 키를 추가/삭제하여 자동 시작 설정
    """

    APP_NAME = "ActivityTracker"
    REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def get_executable_path():
        """
        실행 파일 경로 반환

        Returns:
            str: 실행 파일 절대 경로
        """
        if getattr(sys, 'frozen', False):
            # PyInstaller로 빌드된 경우
            return sys.executable
        else:
            # 개발 모드: BAT 파일 실행 (venv 활성화 포함)
            project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            bat_path = os.path.join(project_dir, 'ActivityTracker.bat')
            return f'"{bat_path}"'

    @staticmethod
    def is_enabled():
        """
        자동 시작 활성화 여부 확인

        Returns:
            bool: 활성화 여부
        """
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                AutoStartManager.REGISTRY_PATH,
                0,
                winreg.KEY_READ
            )

            try:
                value, _ = winreg.QueryValueEx(key, AutoStartManager.APP_NAME)
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False

        except Exception as e:
            print(f"[AutoStartManager] 레지스트리 읽기 오류: {e}")
            return False

    @staticmethod
    def enable():
        """
        자동 시작 활성화

        Returns:
            bool: 성공 여부
        """
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                AutoStartManager.REGISTRY_PATH,
                0,
                winreg.KEY_WRITE
            )

            executable_path = AutoStartManager.get_executable_path()
            winreg.SetValueEx(key, AutoStartManager.APP_NAME, 0, winreg.REG_SZ, executable_path)
            winreg.CloseKey(key)

            print(f"[AutoStartManager] 자동 시작 활성화: {executable_path}")
            return True

        except Exception as e:
            print(f"[AutoStartManager] 레지스트리 쓰기 오류: {e}")
            return False

    @staticmethod
    def disable():
        """
        자동 시작 비활성화

        Returns:
            bool: 성공 여부
        """
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                AutoStartManager.REGISTRY_PATH,
                0,
                winreg.KEY_WRITE
            )

            try:
                winreg.DeleteValue(key, AutoStartManager.APP_NAME)
                print(f"[AutoStartManager] 자동 시작 비활성화")
                result = True
            except FileNotFoundError:
                # 이미 없으면 성공으로 간주
                result = True

            winreg.CloseKey(key)
            return result

        except Exception as e:
            print(f"[AutoStartManager] 레지스트리 삭제 오류: {e}")
            return False
