"""
SQLite 데이터베이스 관리
"""
import sqlite3
import threading
import shutil
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, Dict, List, Any
from backend.config import AppConfig


class DatabaseManager:
    """
    SQLite 데이터베이스 관리 클래스

    스레드 안전성: 각 스레드마다 별도 connection을 사용
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        DB 매니저 초기화

        Args:
            db_path: DB 파일 경로 (None이면 AppConfig에서 자동 설정)
        """
        if db_path is None:
            db_path = AppConfig.get_db_path()

        self.db_path = str(db_path)
        self._local = threading.local()  # 스레드별 connection 저장
        self.init_database()

    @property
    def conn(self):
        """
        스레드별 connection 반환
        각 스레드가 처음 접근할 때 자동으로 connection 생성
        """
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            # WAL 모드로 동시성 향상
            self._local.conn.execute('PRAGMA journal_mode=WAL')
        return self._local.conn

    def init_database(self):
        """테이블 생성 및 기본 데이터 삽입"""
        cursor = self.conn.cursor()
        self._create_core_tables(cursor)
        self._apply_schema_migrations(cursor)
        self._mark_existing_installations(cursor)
        self._create_supporting_tables(cursor)
        self._seed_system_tags_and_rules(cursor)
        self._seed_default_rules(cursor)
        self._reconcile_alert_assets()
        self._seed_alert_assets()
        self.conn.commit()

    def _fetch_all_dicts(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """조회 결과 전체를 dict 리스트로 반환."""
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def _fetch_one_dict(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """조회 결과 단건을 dict로 반환."""
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def _execute_commit(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """변경 쿼리를 실행하고 commit."""
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        self.conn.commit()
        return cursor

    def _normalize_tag_category(self, category: Optional[str]) -> str:
        """유효하지 않은 태그 카테고리는 other로 보정."""
        return category if category in ('work', 'non_work', 'other') else 'other'

    def _get_named_assets(self, table: str) -> List[Dict[str, Any]]:
        """이름순 자산 목록 조회."""
        return self._fetch_all_dicts(f"SELECT * FROM {table} ORDER BY name")

    def _get_asset_by_id(self, table: str, asset_id: int) -> Optional[Dict[str, Any]]:
        """ID로 자산 단건 조회."""
        return self._fetch_one_dict(f"SELECT * FROM {table} WHERE id = ?", (asset_id,))

    def _insert_named_asset(self, table: str, name: str, file_path: str) -> int:
        """이름/경로 기반 자산 추가."""
        cursor = self._execute_commit(
            f"INSERT INTO {table} (name, file_path) VALUES (?, ?)",
            (name, file_path)
        )
        return cursor.lastrowid

    def _delete_by_id(self, table: str, row_id: int):
        """테이블에서 ID 기준 삭제."""
        self._execute_commit(f"DELETE FROM {table} WHERE id = ?", (row_id,))

    def _create_core_tables(self, cursor):
        """핵심 테이블과 인덱스 생성"""
        # tags 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                color TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # activities 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP,

                process_name TEXT,
                window_title TEXT,
                process_path TEXT,
                chrome_profile TEXT,
                chrome_url TEXT,

                tag_id INTEGER,
                rule_id INTEGER,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE SET NULL,
                FOREIGN KEY (rule_id) REFERENCES rules(id) ON DELETE SET NULL
            )
        """)

        # activities 인덱스
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_activities_time
            ON activities(start_time, end_time)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_activities_tag
            ON activities(tag_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_activities_process
            ON activities(process_name)
        """)

        # rules 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                priority INTEGER DEFAULT 0,
                enabled BOOLEAN DEFAULT 1,

                process_pattern TEXT,
                url_pattern TEXT,
                window_title_pattern TEXT,
                chrome_profile TEXT,
                process_path_pattern TEXT,

                tag_id INTEGER NOT NULL,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
        """)

        # settings 테이블 (전역 설정)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

    def _apply_migration(self, cursor, sql: str):
        """단일 ALTER TABLE 마이그레이션 적용."""
        try:
            cursor.execute(sql)
            self.conn.commit()
        except Exception:
            pass

    def _apply_schema_migrations(self, cursor):
        """기존 설치본을 최신 스키마로 맞춤."""
        self._apply_migration(cursor, "ALTER TABLE activities ADD COLUMN process_path TEXT")
        self._apply_migration(cursor, "ALTER TABLE rules ADD COLUMN process_path_pattern TEXT")
        self._apply_migration(cursor, "ALTER TABLE tags ADD COLUMN alert_enabled BOOLEAN DEFAULT 0")
        self._apply_migration(cursor, "ALTER TABLE tags ADD COLUMN alert_message TEXT")
        self._apply_migration(cursor, "ALTER TABLE tags ADD COLUMN alert_cooldown INTEGER DEFAULT 30")
        self._apply_migration(cursor, "ALTER TABLE tags ADD COLUMN block_enabled BOOLEAN DEFAULT 0")
        self._apply_migration(cursor, "ALTER TABLE tags ADD COLUMN block_start_time TEXT")
        self._apply_migration(cursor, "ALTER TABLE tags ADD COLUMN block_end_time TEXT")
        self._apply_migration(cursor, "ALTER TABLE tags ADD COLUMN category TEXT DEFAULT 'other'")

    def _mark_existing_installations(self, cursor):
        """기존 사용자 DB는 기본 시드를 다시 넣지 않도록 표시."""
        cursor.execute("SELECT value FROM settings WHERE key='default_tags_seeded'")
        if not cursor.fetchone():
            # 시스템 태그 외에 다른 태그가 있으면 기존 사용자로 간주
            cursor.execute("SELECT COUNT(*) FROM tags WHERE name NOT IN ('자리비움', '미분류')")
            if cursor.fetchone()[0] > 0:
                cursor.execute("INSERT INTO settings (key, value) VALUES ('default_tags_seeded', '1')")

        cursor.execute("SELECT value FROM settings WHERE key='default_rules_seeded'")
        if not cursor.fetchone():
            # 화면 잠금 외의 룰이 있으면 기존 사용자로 간주
            cursor.execute("SELECT COUNT(*) FROM rules WHERE name != '화면 잠금'")
            if cursor.fetchone()[0] > 0:
                cursor.execute("INSERT INTO settings (key, value) VALUES ('default_rules_seeded', '1')")

    def _create_supporting_tables(self, cursor):
        """부가 기능용 테이블 생성."""
        # alert_sounds 테이블 (알림음 목록)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_sounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # alert_images 테이블 (알림 이미지 목록)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # focus_events 테이블 (집중 모드 관련 이벤트: 긴급해제, 앱 종료 등)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS focus_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def _seed_system_tags_and_rules(self, cursor):
        """항상 필요한 시스템 태그와 잠금 룰 보장."""
        # 시스템 필수 태그 (항상 존재해야 함)
        system_tags = [
            ('자리비움', '#9E9E9E', 'other'),
            ('미분류', '#607D8B', 'other'),
        ]
        for name, color, category in system_tags:
            cursor.execute("""
                INSERT OR IGNORE INTO tags (name, color, category) VALUES (?, ?, ?)
            """, (name, color, category))

        # 화면 잠금 룰 삽입 (이미 존재하면 무시)
        cursor.execute("SELECT id FROM tags WHERE name='자리비움'")
        away_tag_id = cursor.fetchone()
        if away_tag_id:
            away_tag_id = away_tag_id[0]
            cursor.execute("SELECT COUNT(*) FROM rules WHERE name='화면 잠금'")
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO rules (name, priority, process_pattern, tag_id)
                    VALUES ('화면 잠금', 100, '__LOCKED__,lockapp.exe,*__IDLE__*', ?)
                """, (away_tag_id,))

    def _get_resource_base_path(self) -> Path:
        """리소스 기준 경로 반환."""
        import sys
        if getattr(sys, 'frozen', False):
            return Path(sys._MEIPASS)
        return Path(__file__).parent.parent

    def _seed_default_rules(self, cursor):
        """최초 실행 시 기본 규칙 JSON 가져오기."""
        # 기본 태그/규칙 삽입 (최초 1회만) - JSON에서 import
        cursor.execute("SELECT value FROM settings WHERE key='default_rules_seeded'")
        if not cursor.fetchone():
            base_path = self._get_resource_base_path()
            default_json = base_path / "resources" / "default_rules.json"

            if default_json.exists():
                from backend.import_export import ImportExportManager
                mgr = ImportExportManager(self)
                success, msg, stats = mgr.import_rules(str(default_json), merge_mode=True)
                if success:
                    print(f"[DB] 기본 규칙 import 완료: 태그 {stats.get('tags_imported', 0)}개, 규칙 {stats.get('rules_imported', 0)}개")

            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('default_rules_seeded', '1')")

    def _reconcile_alert_assets(self):
        """알림 이미지/사운드 경로 정리 및 누락 항목 제거"""
        cursor = self.conn.cursor()

        images_dir = AppConfig.get_images_dir()
        sounds_dir = AppConfig.get_sounds_dir()

        cursor.execute("SELECT id, file_path FROM alert_images")
        for row in cursor.fetchall():
            file_path = Path(row["file_path"])
            if file_path.exists():
                continue
            candidate = images_dir / file_path.name
            if candidate.exists():
                cursor.execute(
                    "UPDATE alert_images SET file_path = ? WHERE id = ?",
                    (str(candidate), row["id"])
                )
            else:
                cursor.execute("DELETE FROM alert_images WHERE id = ?", (row["id"],))

        cursor.execute("SELECT id, file_path FROM alert_sounds")
        for row in cursor.fetchall():
            file_path = Path(row["file_path"])
            if file_path.exists():
                continue
            candidate = sounds_dir / file_path.name
            if candidate.exists():
                cursor.execute(
                    "UPDATE alert_sounds SET file_path = ? WHERE id = ?",
                    (str(candidate), row["id"])
                )
            else:
                cursor.execute("DELETE FROM alert_sounds WHERE id = ?", (row["id"],))

        self.conn.commit()

    def _seed_alert_assets(self):
        """기본 알림 이미지/사운드 시드"""
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM alert_images")
        image_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM alert_sounds")
        sound_count = cursor.fetchone()[0]

        # PyInstaller 빌드 환경에서는 _MEIPASS 사용
        base_path = self._get_resource_base_path()
        resource_dir = base_path / "resources"

        if image_count == 0:
            images_dir = AppConfig.get_images_dir()
            candidates = [
                resource_dir / "default_01.png",
                resource_dir / "default_02.png",
                base_path / "default_01.png",
                base_path / "default_02.png",
            ]
            seeded = 0
            for candidate in candidates:
                if not candidate.exists():
                    continue
                dest_path = images_dir / candidate.name
                if not dest_path.exists():
                    shutil.copy2(candidate, dest_path)
                cursor.execute(
                    "INSERT INTO alert_images (name, file_path) VALUES (?, ?)",
                    (candidate.stem, str(dest_path))
                )
                seeded += 1
            if seeded:
                self.conn.commit()

        if sound_count == 0:
            sounds_dir = AppConfig.get_sounds_dir()
            sound_candidates = [
                resource_dir / "default_sound.wav",
                resource_dir / "default_sound.mp3",
                base_path / "default_sound.wav",
                base_path / "default_sound.mp3",
            ]
            for candidate in sound_candidates:
                if not candidate.exists():
                    continue
                dest_path = sounds_dir / candidate.name
                if not dest_path.exists():
                    shutil.copy2(candidate, dest_path)
                cursor.execute(
                    "INSERT INTO alert_sounds (name, file_path) VALUES (?, ?)",
                    (candidate.stem, str(dest_path))
                )
                break

    # === 태그 관리 ===
    def get_all_tags(self) -> List[Dict[str, Any]]:
        """모든 태그 조회"""
        return self._fetch_all_dicts("SELECT * FROM tags ORDER BY name")

    def get_tag_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """이름으로 태그 조회"""
        return self._fetch_one_dict("SELECT * FROM tags WHERE name = ?", (name,))

    def get_tag_by_id(self, tag_id: int) -> Optional[Dict[str, Any]]:
        """ID로 태그 조회"""
        return self._fetch_one_dict("SELECT * FROM tags WHERE id = ?", (tag_id,))

    def create_tag(self, name: str, color: str, category: str = 'other') -> int:
        """태그 생성"""
        cursor = self._execute_commit(
            "INSERT INTO tags (name, color, category) VALUES (?, ?, ?)",
            (name, color, self._normalize_tag_category(category))
        )
        return cursor.lastrowid

    def update_tag(self, tag_id: int, name: Optional[str] = None,
                   color: Optional[str] = None,
                   category: Optional[str] = None,
                   alert_enabled: Optional[bool] = None,
                   alert_message: Optional[str] = None,
                   alert_cooldown: Optional[int] = None,
                   block_enabled: Optional[bool] = None,
                   block_start_time: Optional[str] = None,
                   block_end_time: Optional[str] = None):
        """태그 수정"""
        cursor = self.conn.cursor()
        updates = []
        values = []

        if name:
            updates.append("name = ?")
            values.append(name)
        if color:
            updates.append("color = ?")
            values.append(color)
        if category is not None:
            updates.append("category = ?")
            values.append(self._normalize_tag_category(category))
        if alert_enabled is not None:
            updates.append("alert_enabled = ?")
            values.append(1 if alert_enabled else 0)
        if alert_message is not None:
            updates.append("alert_message = ?")
            values.append(alert_message if alert_message else None)
        if alert_cooldown is not None:
            updates.append("alert_cooldown = ?")
            values.append(max(1, alert_cooldown))  # 최소 1초
        if block_enabled is not None:
            updates.append("block_enabled = ?")
            values.append(1 if block_enabled else 0)
        if block_start_time is not None:
            updates.append("block_start_time = ?")
            values.append(block_start_time if block_start_time else None)
        if block_end_time is not None:
            updates.append("block_end_time = ?")
            values.append(block_end_time if block_end_time else None)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            query = f"UPDATE tags SET {', '.join(updates)} WHERE id = ?"
            values.append(tag_id)
            cursor.execute(query, values)
            self.conn.commit()

    def delete_tag(self, tag_id: int):
        """태그 삭제 (activities.tag_id는 NULL로)"""
        self._delete_by_id("tags", tag_id)

    # === 활동 기록 ===
    def create_activity(self, process_name: Optional[str] = None,
                       window_title: Optional[str] = None,
                       process_path: Optional[str] = None,
                       chrome_url: Optional[str] = None,
                       chrome_profile: Optional[str] = None,
                       tag_id: Optional[int] = None,
                       rule_id: Optional[int] = None) -> int:
        """새 활동 시작 (start_time=now, end_time=NULL)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO activities
            (start_time, process_name, window_title, process_path, chrome_url,
             chrome_profile, tag_id, rule_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now(), process_name, window_title, process_path, chrome_url,
              chrome_profile, tag_id, rule_id))
        self.conn.commit()
        return cursor.lastrowid

    def end_activity(self, activity_id: int):
        """활동 종료 (end_time=now)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE activities SET end_time = ? WHERE id = ?
        """, (datetime.now(), activity_id))
        self.conn.commit()

    def cleanup_unfinished_activities(self):
        """
        종료되지 않은 활동들을 정리 (프로그램 시작 시 호출)

        end_time이 NULL인 활동들을 start_time으로부터 1분 후로 종료 처리
        (프로그램이 비정상 종료된 경우를 대비)
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE activities
            SET end_time = datetime(start_time, '+1 minute')
            WHERE end_time IS NULL
        """)
        affected_rows = cursor.rowcount
        self.conn.commit()

        if affected_rows > 0:
            print(f"[DatabaseManager] {affected_rows}개의 종료되지 않은 활동 정리 완료")

        return affected_rows

    def get_activities(self, start_date: datetime, end_date: datetime,
                       tag_id: Optional[int] = None,
                       limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """기간별 활동 조회"""
        cursor = self.conn.cursor()

        if tag_id:
            query = """
                SELECT a.*, t.name as tag_name, t.color as tag_color
                FROM activities a
                LEFT JOIN tags t ON a.tag_id = t.id
                WHERE a.start_time >= ? AND a.start_time < ? AND a.tag_id = ?
                ORDER BY a.start_time DESC
            """
            params = [start_date, end_date, tag_id]
        else:
            query = """
                SELECT a.*, t.name as tag_name, t.color as tag_color
                FROM activities a
                LEFT JOIN tags t ON a.tag_id = t.id
                WHERE a.start_time >= ? AND a.start_time < ?
                ORDER BY a.start_time DESC
            """
            params = [start_date, end_date]

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor.execute(query, params)

        return [dict(row) for row in cursor.fetchall()]

    # === 통계 ===
    def get_stats_by_tag(self, start_date: datetime,
                        end_date: datetime) -> List[Dict[str, Any]]:
        """태그별 사용 시간 통계"""
        return self._fetch_all_dicts("""
            SELECT
                t.id AS tag_id,
                t.name AS tag_name,
                t.color AS tag_color,
                SUM((julianday(COALESCE(a.end_time, datetime('now', 'localtime'))) -
                     julianday(a.start_time)) * 86400) AS total_seconds
            FROM activities a
            JOIN tags t ON a.tag_id = t.id
            WHERE a.start_time >= ? AND a.start_time < ?
            GROUP BY t.id
            ORDER BY total_seconds DESC
        """, (start_date, end_date))

    def get_hourly_stats(self, start_date: datetime,
                         end_date: datetime) -> List[Dict[str, Any]]:
        """시간대별 태그 통계 (SQL 집계)"""
        return self._fetch_all_dicts("""
            SELECT
                CAST(strftime('%H', a.start_time) AS INTEGER) AS hour,
                t.id AS tag_id,
                t.name AS tag_name,
                t.color AS tag_color,
                SUM((julianday(COALESCE(a.end_time, datetime('now', 'localtime'))) -
                     julianday(a.start_time)) * 86400) AS total_seconds
            FROM activities a
            JOIN tags t ON a.tag_id = t.id
            WHERE a.start_time >= ? AND a.start_time < ?
            GROUP BY hour, t.id
            ORDER BY hour, total_seconds DESC
        """, (start_date, end_date))

    def get_stats_by_process(self, start_date: datetime,
                            end_date: datetime, limit: int = 10) -> List[Dict[str, Any]]:
        """프로세스별 사용 시간 통계 (__IDLE__, __LOCKED__, LockApp.exe 제외)"""
        return self._fetch_all_dicts("""
            SELECT
                process_name,
                SUM((julianday(COALESCE(end_time, datetime('now', 'localtime'))) -
                     julianday(start_time)) * 86400) AS total_seconds,
                COUNT(*) AS activity_count
            FROM activities
            WHERE start_time >= ? AND start_time < ?
                  AND process_name IS NOT NULL
                  AND process_name NOT IN ('__IDLE__', '__LOCKED__', 'LockApp.exe')
            GROUP BY process_name
            ORDER BY total_seconds DESC
            LIMIT ?
        """, (start_date, end_date, limit))

    # === 룰 관리 ===
    def get_all_rules(self, enabled_only: bool = False,
                     order_by: str = 'priority DESC') -> List[Dict[str, Any]]:
        """모든 룰 조회"""
        cursor = self.conn.cursor()

        query = "SELECT r.*, t.name as tag_name FROM rules r JOIN tags t ON r.tag_id = t.id"
        if enabled_only:
            query += " WHERE r.enabled = 1"
        query += f" ORDER BY {order_by}"

        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]

    def get_rule_by_id(self, rule_id: int) -> Optional[Dict[str, Any]]:
        """ID로 룰 조회"""
        return self._fetch_one_dict("""
            SELECT r.*, t.name as tag_name
            FROM rules r
            JOIN tags t ON r.tag_id = t.id
            WHERE r.id = ?
        """, (rule_id,))

    def create_rule(self, name: str, tag_id: int, priority: int = 0,
                   enabled: bool = True, process_pattern: Optional[str] = None,
                   url_pattern: Optional[str] = None,
                   window_title_pattern: Optional[str] = None,
                   chrome_profile: Optional[str] = None,
                   process_path_pattern: Optional[str] = None) -> int:
        """룰 생성"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO rules
            (name, priority, enabled, process_pattern, url_pattern,
             window_title_pattern, chrome_profile, process_path_pattern, tag_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, priority, enabled, process_pattern, url_pattern,
              window_title_pattern, chrome_profile, process_path_pattern, tag_id))
        self.conn.commit()
        return cursor.lastrowid

    def update_rule(self, rule_id: int, **kwargs):
        """룰 수정"""
        allowed_fields = ['name', 'priority', 'enabled', 'process_pattern',
                         'url_pattern', 'window_title_pattern',
                         'chrome_profile', 'process_path_pattern', 'tag_id']

        updates = []
        values = []
        for field, value in kwargs.items():
            if field in allowed_fields:
                updates.append(f"{field} = ?")
                values.append(value)

        if updates:
            cursor = self.conn.cursor()
            query = f"UPDATE rules SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
            values.append(rule_id)
            cursor.execute(query, values)
            self.conn.commit()

    def delete_rule(self, rule_id: int):
        """룰 삭제"""
        self._delete_by_id("rules", rule_id)

    # === 미분류 재분류 ===
    def get_all_activities_for_reclassify(self) -> List[Dict[str, Any]]:
        """모든 활동 조회 (전체 재분류용)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, process_name, window_title, process_path, chrome_url, chrome_profile
            FROM activities
            ORDER BY start_time DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_unclassified_activities(self) -> List[Dict[str, Any]]:
        """미분류 태그를 가진 모든 활동 조회"""
        cursor = self.conn.cursor()

        # 미분류 태그 ID 조회
        unclassified_tag = self.get_tag_by_name('미분류')
        if not unclassified_tag:
            return []

        cursor.execute("""
            SELECT id, process_name, window_title, process_path, chrome_url, chrome_profile
            FROM activities
            WHERE tag_id = ?
            ORDER BY start_time DESC
        """, (unclassified_tag['id'],))
        return [dict(row) for row in cursor.fetchall()]

    def update_activity_classification(self, activity_id: int, tag_id: int, rule_id: Optional[int] = None):
        """활동의 분류 정보 업데이트"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE activities
            SET tag_id = ?, rule_id = ?
            WHERE id = ?
        """, (tag_id, rule_id, activity_id))
        self.conn.commit()

    def delete_activities(self, activity_ids: List[int]):
        """활동 기록 삭제"""
        if not activity_ids:
            return
        cursor = self.conn.cursor()
        placeholders = ','.join('?' * len(activity_ids))
        cursor.execute(f"DELETE FROM activities WHERE id IN ({placeholders})", activity_ids)
        self.conn.commit()

    # === 전역 설정 ===
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """설정 값 조회"""
        row = self._fetch_one_dict("SELECT value FROM settings WHERE key = ?", (key,))
        return row['value'] if row else default

    def set_setting(self, key: str, value: str):
        """설정 값 저장"""
        self._execute_commit(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )

    # === 알림음 관리 ===
    def get_all_alert_sounds(self) -> List[Dict[str, Any]]:
        """모든 알림음 조회"""
        return self._get_named_assets("alert_sounds")

    def get_alert_sound_by_id(self, sound_id: int) -> Optional[Dict[str, Any]]:
        """ID로 알림음 조회"""
        return self._get_asset_by_id("alert_sounds", sound_id)

    def add_alert_sound(self, name: str, file_path: str) -> int:
        """알림음 추가"""
        return self._insert_named_asset("alert_sounds", name, file_path)

    def delete_alert_sound(self, sound_id: int):
        """알림음 삭제"""
        self._delete_by_id("alert_sounds", sound_id)

    # === 알림 이미지 관리 ===
    def get_all_alert_images(self) -> List[Dict[str, Any]]:
        """모든 알림 이미지 조회"""
        return self._get_named_assets("alert_images")

    def get_alert_image_by_id(self, image_id: int) -> Optional[Dict[str, Any]]:
        """ID로 알림 이미지 조회"""
        return self._get_asset_by_id("alert_images", image_id)

    def add_alert_image(self, name: str, file_path: str) -> int:
        """알림 이미지 추가"""
        return self._insert_named_asset("alert_images", name, file_path)

    def delete_alert_image(self, image_id: int):
        """알림 이미지 삭제"""
        self._delete_by_id("alert_images", image_id)

    # === 집중 모드 이벤트 ===
    def add_focus_event(self, event_type: str, details: Optional[str] = None) -> int:
        """
        집중 모드 이벤트 추가

        Args:
            event_type: 이벤트 유형 ('emergency_reset', 'app_exit_during_focus', etc.)
            details: JSON 문자열 (태그 목록, 사유 등)

        Returns:
            생성된 이벤트 ID
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO focus_events (timestamp, event_type, details)
            VALUES (?, ?, ?)
        """, (datetime.now().isoformat(), event_type, details))
        self.conn.commit()
        return cursor.lastrowid

    def get_focus_events_by_date(self, target_date: date) -> List[Dict[str, Any]]:
        """특정 날짜의 집중 모드 이벤트 조회"""
        cursor = self.conn.cursor()
        date_str = target_date.isoformat()
        cursor.execute("""
            SELECT * FROM focus_events
            WHERE date(timestamp) = ?
            ORDER BY timestamp ASC
        """, (date_str,))
        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """DB 연결 종료"""
        if hasattr(self._local, 'conn'):
            try:
                self._local.conn.close()
            finally:
                del self._local.conn

    def __del__(self):
        """소멸자"""
        if hasattr(self, '_local') and hasattr(self._local, 'conn'):
            self._local.conn.close()
