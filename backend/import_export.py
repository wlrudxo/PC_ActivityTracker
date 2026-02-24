"""
Import/Export 유틸리티

데이터베이스 전체 백업/복원 및 룰 Import/Export 기능
"""
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from backend.config import AppConfig


class ImportExportManager:
    """
    Import/Export 관리 클래스

    기능:
    1. DB 전체 백업 (SQLite 파일 복사)
    2. DB 복원 (백업 파일로 교체)
    3. 룰 Export (JSON)
    4. 룰 Import (JSON)
    """

    def __init__(self, db_manager):
        """
        Args:
            db_manager: DatabaseManager 인스턴스
        """
        self.db_manager = db_manager
        self.db_path = Path(db_manager.db_path)

    # === DB 전체 백업/복원 ===

    def export_database(self, backup_path: str) -> bool:
        """
        데이터베이스 전체를 백업 파일로 Export (SQLite backup API 사용)

        Args:
            backup_path: 백업 파일 경로 (.db 확장자)

        Returns:
            성공 여부
        """
        import sqlite3

        try:
            backup_path = Path(backup_path)

            # 확장자 체크
            if backup_path.suffix.lower() != '.db':
                backup_path = backup_path.with_suffix('.db')

            # SQLite backup API를 사용하여 일관성 있는 스냅샷 생성
            # 다른 스레드가 쓰기 중이어도 안전하게 백업 가능
            backup_conn = sqlite3.connect(str(backup_path))
            try:
                self.db_manager.conn.backup(backup_conn)
            finally:
                backup_conn.close()

            print(f"[ImportExport] DB 백업 완료: {backup_path}")
            return True

        except Exception as e:
            print(f"[ImportExport] DB 백업 실패: {e}")
            return False

    def _add_dir_to_zip(self, source_dir: Path, zip_file: zipfile.ZipFile, arc_prefix: str):
        if not source_dir.exists():
            return
        for path in source_dir.rglob("*"):
            if path.is_file():
                rel_path = path.relative_to(source_dir)
                arcname = f"{arc_prefix}/{rel_path.as_posix()}"
                zip_file.write(path, arcname)

    def export_full_backup(self, backup_path: str) -> bool:
        """
        데이터베이스 + 알림 이미지/사운드를 zip으로 백업

        Args:
            backup_path: 백업 파일 경로 (.zip 확장자)

        Returns:
            성공 여부
        """
        import sqlite3

        try:
            backup_path = Path(backup_path)
            if backup_path.suffix.lower() != '.zip':
                backup_path = backup_path.with_suffix('.zip')

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_dir = Path(temp_dir)
                temp_db = temp_dir / "activity_tracker.db"

                backup_conn = sqlite3.connect(str(temp_db))
                try:
                    self.db_manager.conn.backup(backup_conn)
                finally:
                    backup_conn.close()

                with zipfile.ZipFile(backup_path, 'w', compression=zipfile.ZIP_DEFLATED) as zip_file:
                    zip_file.write(temp_db, "activity_tracker.db")
                    self._add_dir_to_zip(AppConfig.get_images_dir(), zip_file, "images")
                    self._add_dir_to_zip(AppConfig.get_sounds_dir(), zip_file, "sounds")

            print(f"[ImportExport] 전체 백업 완료: {backup_path}")
            return True

        except Exception as e:
            print(f"[ImportExport] 전체 백업 실패: {e}")
            return False

    # === 룰 Import/Export (JSON) ===

    def export_rules(self, json_path: str) -> bool:
        """
        태그와 룰을 JSON 파일로 Export

        JSON 구조:
        {
            "export_date": "2024-01-01 12:00:00",
            "version": "1.0",
            "tags": [...],
            "rules": [...]
        }

        Args:
            json_path: JSON 파일 경로

        Returns:
            성공 여부
        """
        try:
            json_path = Path(json_path)

            # 확장자 체크
            if json_path.suffix.lower() != '.json':
                json_path = json_path.with_suffix('.json')

            # 태그와 룰 조회
            tags = self.db_manager.get_all_tags()
            rules = self.db_manager.get_all_rules(order_by='priority DESC')

            # JSON 데이터 구성
            export_data = {
                "export_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "version": "1.0",
                "tags": tags,
                "rules": rules
            }

            # JSON 파일로 저장
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)

            print(f"[ImportExport] 룰 Export 완료: {json_path}")
            print(f"  - 태그: {len(tags)}개")
            print(f"  - 룰: {len(rules)}개")
            return True

        except Exception as e:
            print(f"[ImportExport] 룰 Export 실패: {e}")
            return False

    def import_rules(self, json_path: str, merge_mode: bool = True) -> Tuple[bool, str, Dict[str, int]]:
        """
        JSON 파일에서 태그와 룰을 Import

        동작:
        1. 태그: 같은 이름이 있으면 기존 것 사용, 없으면 새로 생성
        2. 룰: merge_mode에 따라 처리
           - merge_mode=True: 동일 (name + priority + tag_id)면 필터 합집합으로 업데이트, 없으면 추가
           - merge_mode=False: 기존 룰 삭제 + 새 룰만 추가

        Args:
            json_path: JSON 파일 경로
            merge_mode: True=기존 룰 유지, False=기존 룰 삭제

        Returns:
            (성공 여부, 메시지, 통계 딕셔너리)
        """
        try:
            json_path = Path(json_path)

            # JSON 파일 존재 확인
            if not json_path.exists():
                return False, "JSON 파일이 존재하지 않습니다.", {}

            # JSON 파일 읽기
            with open(json_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)

            # 버전 체크 (미래에 확장 가능)
            version = import_data.get('version', '1.0')
            if version != '1.0':
                return False, f"지원하지 않는 버전입니다: {version}", {}

            tags_data = import_data.get('tags', [])
            rules_data = import_data.get('rules', [])

            # 통계
            stats = {
                'tags_imported': 0,
                'tags_existed': 0,
                'rules_imported': 0,
                'rules_deleted': 0,
                'rules_merged': 0
            }

            # 태그 ID 매핑 (JSON의 tag_id -> DB의 tag_id)
            tag_id_mapping = {}

            # 1. 태그 Import
            for tag in tags_data:
                tag_name = tag['name']
                tag_color = tag['color']
                tag_category = tag.get('category', 'other')

                # 같은 이름의 태그가 있는지 확인
                existing_tag = self.db_manager.get_tag_by_name(tag_name)

                if existing_tag:
                    # 기존 태그 사용
                    tag_id_mapping[tag['id']] = existing_tag['id']
                    stats['tags_existed'] += 1
                else:
                    # 새 태그 생성
                    new_tag_id = self.db_manager.create_tag(tag_name, tag_color, tag_category)
                    tag_id_mapping[tag['id']] = new_tag_id
                    stats['tags_imported'] += 1

            # 2. 룰 Import
            if not merge_mode:
                # 기존 룰 모두 삭제
                existing_rules = self.db_manager.get_all_rules()
                for rule in existing_rules:
                    self.db_manager.delete_rule(rule['id'])
                    stats['rules_deleted'] += 1
                existing_rule_map = {}
            else:
                existing_rule_map = {}
                existing_rules = self.db_manager.get_all_rules()
                for rule in existing_rules:
                    key = (rule['name'], rule.get('priority', 0), rule['tag_id'])
                    existing_rule_map[key] = rule

            def _split_patterns(value: Optional[str]) -> List[str]:
                if not value:
                    return []
                return [v.strip() for v in value.split(',') if v.strip()]

            def _merge_patterns(existing: Optional[str], incoming: Optional[str]) -> Optional[str]:
                combined = []
                seen = set()
                for item in _split_patterns(existing) + _split_patterns(incoming):
                    if item not in seen:
                        combined.append(item)
                        seen.add(item)
                return ",".join(combined) if combined else None

            # 새 룰 추가
            for rule in rules_data:
                # 태그 ID 매핑
                old_tag_id = rule['tag_id']
                if old_tag_id not in tag_id_mapping:
                    print(f"[ImportExport] 경고: 룰 '{rule['name']}'의 태그 ID {old_tag_id}를 찾을 수 없습니다. 건너뜁니다.")
                    continue

                new_tag_id = tag_id_mapping[old_tag_id]

                name = rule['name']
                priority = rule.get('priority', 0)
                key = (name, priority, new_tag_id)

                if merge_mode and key in existing_rule_map:
                    existing = existing_rule_map[key]

                    merged_process = _merge_patterns(existing.get('process_pattern'), rule.get('process_pattern'))
                    merged_url = _merge_patterns(existing.get('url_pattern'), rule.get('url_pattern'))
                    merged_title = _merge_patterns(existing.get('window_title_pattern'), rule.get('window_title_pattern'))
                    merged_path = _merge_patterns(existing.get('process_path_pattern'), rule.get('process_path_pattern'))

                    chrome_profile = rule.get('chrome_profile') or existing.get('chrome_profile')
                    enabled = rule.get('enabled', existing.get('enabled', True))

                    self.db_manager.update_rule(
                        existing['id'],
                        enabled=enabled,
                        process_pattern=merged_process,
                        url_pattern=merged_url,
                        window_title_pattern=merged_title,
                        chrome_profile=chrome_profile,
                        process_path_pattern=merged_path
                    )
                    stats['rules_merged'] += 1
                else:
                    # 룰 생성
                    self.db_manager.create_rule(
                        name=name,
                        tag_id=new_tag_id,
                        priority=priority,
                        enabled=rule.get('enabled', True),
                        process_pattern=rule.get('process_pattern'),
                        url_pattern=rule.get('url_pattern'),
                        window_title_pattern=rule.get('window_title_pattern'),
                        chrome_profile=rule.get('chrome_profile'),
                        process_path_pattern=rule.get('process_path_pattern')
                    )
                    stats['rules_imported'] += 1

            # 결과 메시지
            message_parts = []
            message_parts.append("Import 완료!")
            message_parts.append("")
            message_parts.append(f"태그:")
            message_parts.append(f"  - 새로 추가: {stats['tags_imported']}개")
            message_parts.append(f"  - 기존 사용: {stats['tags_existed']}개")
            message_parts.append("")
            message_parts.append(f"룰:")
            if stats['rules_deleted'] > 0:
                message_parts.append(f"  - 기존 삭제: {stats['rules_deleted']}개")
            message_parts.append(f"  - 새로 추가: {stats['rules_imported']}개")
            if stats['rules_merged'] > 0:
                message_parts.append(f"  - 병합 업데이트: {stats['rules_merged']}개")

            message = '\n'.join(message_parts)

            print(f"[ImportExport] 룰 Import 완료")
            print(f"  - 태그: 추가 {stats['tags_imported']}개, 기존 {stats['tags_existed']}개")
            print(f"  - 룰: 추가 {stats['rules_imported']}개, 삭제 {stats['rules_deleted']}개, 병합 {stats['rules_merged']}개")

            return True, message, stats

        except Exception as e:
            print(f"[ImportExport] 룰 Import 실패: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Import 중 오류 발생:\n{str(e)}", {}

    def validate_rules_json(self, json_path: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        룰 JSON 파일의 유효성 검증

        Args:
            json_path: JSON 파일 경로

        Returns:
            (유효 여부, 메시지, 데이터 미리보기)
        """
        try:
            json_path = Path(json_path)

            if not json_path.exists():
                return False, "파일이 존재하지 않습니다.", None

            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 필수 필드 체크
            if 'version' not in data:
                return False, "version 필드가 없습니다.", None

            if 'tags' not in data or 'rules' not in data:
                return False, "tags 또는 rules 필드가 없습니다.", None

            # 미리보기 정보
            preview = {
                'export_date': data.get('export_date', '알 수 없음'),
                'version': data.get('version'),
                'tags_count': len(data.get('tags', [])),
                'rules_count': len(data.get('rules', []))
            }

            return True, "유효한 룰 파일입니다.", preview

        except json.JSONDecodeError as e:
            return False, f"JSON 파싱 오류: {str(e)}", None
        except Exception as e:
            return False, f"파일 읽기 오류: {str(e)}", None
