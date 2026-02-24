"""
활동 로그 생성기 - LLM 분석용 텍스트 로그 생성
"""
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from collections import defaultdict
import calendar

import json

from backend.config import AppConfig
from backend.database import DatabaseManager


class ActivityLogGenerator:
    """
    일별/월별 활동 로그 생성기

    - daily/*.log: 날짜별 상세 로그
    - recent.log: 최근 N일 통합 (LLM 복붙용)
    - monthly/*.log: 월별 아카이브
    """

    WEEKDAYS_KR = ['월', '화', '수', '목', '금', '토', '일']
    DEFAULT_RETENTION_DAYS = 30

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def get_retention_days(self) -> int:
        """설정에서 로그 보관 일수 조회"""
        value = self.db.get_setting('log_retention_days')
        return int(value) if value else self.DEFAULT_RETENTION_DAYS

    def generate_daily_log(self, target_date: date) -> str:
        """특정 날짜의 로그 생성"""
        start = datetime.combine(target_date, datetime.min.time())
        end = start + timedelta(days=1)

        activities = self.db.get_activities(start, end)

        if not activities:
            weekday = self.WEEKDAYS_KR[target_date.weekday()]
            return f"{target_date.isoformat()} ({weekday}) - 활동 없음\n"

        return self._format_daily_log(target_date, activities)

    def _format_daily_log(self, target_date: date, activities: List[Dict]) -> str:
        """일별 로그 포맷팅 (압축 형식)"""
        weekday = self.WEEKDAYS_KR[target_date.weekday()]
        start_dt = datetime.combine(target_date, datetime.min.time())
        end_dt = start_dt + timedelta(days=1)

        lines = []
        lines.append(f"--- {target_date.isoformat()} ({weekday}) ---")

        # 요약
        summary = self._get_summary(activities)
        lines.append(f"[요약] 첫활동:{summary['first_time']} 마지막:{summary['last_time']} 활동:{summary['total_active']} 전환:{summary['tag_switches']}회")

        # 태그별 시간 (자리비움 제외)
        tag_stats = self.db.get_stats_by_tag(start_dt, end_dt)
        if tag_stats:
            filtered_stats = [t for t in tag_stats if t['tag_name'] != '자리비움']
            if filtered_stats:
                total_secs = sum(t['total_seconds'] or 0 for t in filtered_stats)
                tag_parts = []
                for ts in filtered_stats:
                    secs = ts['total_seconds'] or 0
                    pct = (secs / total_secs * 100) if total_secs > 0 else 0
                    tag_parts.append(f"{ts['tag_name']}:{self._format_duration(secs)}({pct:.0f}%)")
                lines.append(f"[태그별] {' '.join(tag_parts)}")

        # 프로세스 TOP 10
        proc_stats = self.db.get_stats_by_process(start_dt, end_dt, limit=10)
        if proc_stats:
            proc_parts = [f"{ps['process_name']}:{self._format_duration(ps['total_seconds'])}" for ps in proc_stats]
            lines.append(f"[프로세스] {' '.join(proc_parts)}")

        # 주요 웹사이트
        url_stats = self._get_url_stats(activities)
        if url_stats:
            url_parts = [f"{domain}:{self._format_duration(secs)}" for domain, secs in url_stats[:7]]
            lines.append(f"[웹사이트] {' '.join(url_parts)}")

        # 주요 활동 상세 (자리비움 제외)
        activity_details = self._get_activity_details(activities)
        filtered_details = [(t, tag, s) for t, tag, s in activity_details if tag != '자리비움']
        if filtered_details:
            detail_parts = []
            for title, tag, secs in filtered_details[:10]:
                short_title = title[:40] + "..." if len(title) > 40 else title
                detail_parts.append(f'"{short_title}"({tag}):{self._format_duration(secs)}')
            lines.append(f"[활동상세] {' '.join(detail_parts)}")

        # 시간대별 분포
        hourly = self._get_hourly_distribution(activities)
        if hourly:
            hourly_parts = []
            for period, stats in hourly.items():
                if stats:
                    stat_str = ",".join(f"{tag}{self._format_duration(secs)}" for tag, secs in stats.items())
                    hourly_parts.append(f"{period}:{stat_str}")
            lines.append(f"[시간대] {' '.join(hourly_parts)}")

        # 자리비움 기록
        away_records = self._get_away_records(activities)
        if away_records:
            total_away = sum(r['seconds'] for r in away_records)
            away_parts = [f"{r['start']}-{r['end']}({r['duration']})" for r in away_records[:5]]
            if len(away_records) > 5:
                away_parts.append(f"외{len(away_records)-5}건")
            away_parts.append(f"총:{self._format_duration(total_away)}")
            lines.append(f"[자리비움] {' '.join(away_parts)}")

        # 집중 모드 이벤트
        focus_events = self.db.get_focus_events_by_date(target_date)
        if focus_events:
            event_parts = []
            for evt in focus_events:
                ts = datetime.fromisoformat(evt['timestamp']).strftime('%H:%M')
                evt_type = evt['event_type']
                details = json.loads(evt['details']) if evt['details'] else {}

                if evt_type == 'emergency_reset':
                    tags = details.get('reset_tags', [])
                    reason = details.get('reason', '')
                    tag_str = ','.join(tags) if tags else '없음'
                    event_parts.append(f"{ts}긴급해제({tag_str}):{reason}")
                elif evt_type == 'app_exit_during_focus':
                    tags = details.get('active_tags', [])
                    tag_str = ','.join(tags) if tags else ''
                    event_parts.append(f"{ts}집중중종료({tag_str})")
                else:
                    event_parts.append(f"{ts}{evt_type}")

            lines.append(f"[집중모드] {' '.join(event_parts)}")

        return "\n".join(lines)

    def _get_summary(self, activities: List[Dict]) -> Dict[str, Any]:
        """요약 정보 계산"""
        if not activities:
            return {
                'first_time': '-',
                'last_time': '-',
                'total_active': '0분',
                'tag_switches': 0
            }

        # activities는 DESC 정렬, 뒤집어서 시간순
        sorted_acts = sorted(activities, key=lambda x: x['start_time'])

        first = sorted_acts[0]['start_time']
        # 마지막 활동은 start_time 기준 (end_time이 다음 날일 수 있음)
        last = sorted_acts[-1]['start_time']

        if isinstance(first, str):
            first = datetime.fromisoformat(first)
        if isinstance(last, str):
            last = datetime.fromisoformat(last)

        # 자리비움 제외 총 시간
        total_secs = 0
        for act in sorted_acts:
            if act['process_name'] not in ('__LOCKED__', '__IDLE__'):
                start = act['start_time']
                end = act['end_time'] or datetime.now()
                if isinstance(start, str):
                    start = datetime.fromisoformat(start)
                if isinstance(end, str):
                    end = datetime.fromisoformat(end)
                total_secs += (end - start).total_seconds()

        # 태그 전환 횟수
        tag_switches = 0
        prev_tag = None
        for act in sorted_acts:
            if act['tag_id'] != prev_tag:
                if prev_tag is not None:
                    tag_switches += 1
                prev_tag = act['tag_id']

        return {
            'first_time': first.strftime('%H:%M'),
            'last_time': last.strftime('%H:%M'),
            'total_active': self._format_duration(total_secs),
            'tag_switches': tag_switches
        }

    def _get_url_stats(self, activities: List[Dict]) -> List[Tuple[str, float]]:
        """URL 도메인별 사용 시간"""
        domain_secs = defaultdict(float)

        for act in activities:
            url = act.get('chrome_url')
            if not url:
                continue

            # 도메인 추출
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                if domain.startswith('www.'):
                    domain = domain[4:]
            except:
                continue

            if not domain:
                continue

            start = act['start_time']
            end = act['end_time'] or datetime.now()
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            if isinstance(end, str):
                end = datetime.fromisoformat(end)

            domain_secs[domain] += (end - start).total_seconds()

        sorted_domains = sorted(domain_secs.items(), key=lambda x: x[1], reverse=True)
        return sorted_domains

    def _get_activity_details(self, activities: List[Dict]) -> List[Tuple[str, str, float]]:
        """창 제목 기준 주요 활동"""
        title_stats = defaultdict(lambda: {'seconds': 0, 'tag': '미분류'})

        for act in activities:
            title = act.get('window_title') or act.get('process_name') or 'Unknown'
            tag = act.get('tag_name') or '미분류'

            start = act['start_time']
            end = act['end_time'] or datetime.now()
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            if isinstance(end, str):
                end = datetime.fromisoformat(end)

            secs = (end - start).total_seconds()
            key = (title, tag)
            title_stats[key]['seconds'] += secs
            title_stats[key]['tag'] = tag

        result = [(k[0], k[1], v['seconds']) for k, v in title_stats.items()]
        result.sort(key=lambda x: x[2], reverse=True)
        return result

    def _get_hourly_distribution(self, activities: List[Dict]) -> Dict[str, Dict[str, float]]:
        """시간대별 태그 분포"""
        periods = {
            '오전 (06-12)': (6, 12),
            '오후 (12-18)': (12, 18),
            '야간 (18-24)': (18, 24),
            '새벽 (00-06)': (0, 6)
        }

        result = {p: defaultdict(float) for p in periods}

        for act in activities:
            tag = act.get('tag_name') or '미분류'
            if tag == '자리비움':
                continue

            start = act['start_time']
            end = act['end_time'] or datetime.now()
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            if isinstance(end, str):
                end = datetime.fromisoformat(end)

            # 시간대별 할당 (간단히 시작 시간 기준)
            hour = start.hour
            for period_name, (start_h, end_h) in periods.items():
                if start_h <= hour < end_h:
                    secs = (end - start).total_seconds()
                    result[period_name][tag] += secs
                    break

        # 빈 시간대 제거, dict로 변환
        return {k: dict(v) for k, v in result.items() if v}

    def _get_away_records(self, activities: List[Dict]) -> List[Dict]:
        """자리비움 기록 (5분 이상만)"""
        records = []
        MIN_AWAY_SECONDS = 300  # 5분

        for act in activities:
            if act.get('process_name') not in ('__LOCKED__', '__IDLE__'):
                continue

            start = act['start_time']
            end = act['end_time'] or datetime.now()
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            if isinstance(end, str):
                end = datetime.fromisoformat(end)

            secs = (end - start).total_seconds()
            # 5분 미만은 무시
            if secs < MIN_AWAY_SECONDS:
                continue

            records.append({
                'start': start.strftime('%H:%M'),
                'end': end.strftime('%H:%M'),
                'seconds': secs,
                'duration': self._format_duration(secs)
            })

        records.sort(key=lambda x: x['start'])
        return records

    def _format_duration(self, seconds: float) -> str:
        """초를 시:분 형식으로 (공백 없이)"""
        if seconds is None or seconds < 0:
            seconds = 0

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)

        if hours > 0:
            return f"{hours}시간{minutes}분"
        return f"{minutes}분"

    def save_daily_log(self, target_date: date) -> Path:
        """일별 로그 파일 저장"""
        log_content = self.generate_daily_log(target_date)
        file_path = AppConfig.get_daily_logs_dir() / f"{target_date.isoformat()}.log"
        file_path.write_text(log_content, encoding='utf-8')
        return file_path

    def generate_recent_log(self) -> Path:
        """최근 N일 통합 로그 생성 (오늘-1 ~ 오늘-N)"""
        retention = self.get_retention_days()
        today = date.today()

        lines = []
        lines.append(f"=== 최근 {retention}일 활동로그 (생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}) ===")

        for i in range(1, retention + 1):
            target = today - timedelta(days=i)
            log_content = self.generate_daily_log(target)
            lines.append(log_content)

        file_path = AppConfig.get_recent_log_path()
        file_path.write_text("\n".join(lines), encoding='utf-8')
        return file_path

    def generate_monthly_log(self, year: int, month: int) -> Path:
        """월별 로그 생성"""
        _, last_day = calendar.monthrange(year, month)

        lines = []
        lines.append(f"=== {year}-{month:02d} 월간 활동로그 ===")

        for day in range(1, last_day + 1):
            target = date(year, month, day)
            if target >= date.today():
                break
            log_content = self.generate_daily_log(target)
            lines.append(log_content)

        file_path = AppConfig.get_monthly_logs_dir() / f"{year}-{month:02d}.log"
        file_path.write_text("\n".join(lines), encoding='utf-8')
        return file_path

    def update_all_logs(self):
        """
        모든 로그 갱신 (앱 시작시 호출)

        1. 누락된 일별 로그 생성
        2. recent.log 갱신
        3. 현재 월 아카이브 갱신
        """
        today = date.today()
        retention = self.get_retention_days()

        # 1. 누락된 일별 로그 생성 (최근 retention일)
        daily_dir = AppConfig.get_daily_logs_dir()
        for i in range(1, retention + 1):
            target = today - timedelta(days=i)
            file_path = daily_dir / f"{target.isoformat()}.log"
            if not file_path.exists():
                self.save_daily_log(target)

        # 2. recent.log 갱신
        self.generate_recent_log()

        # 3. 현재 월 아카이브 갱신
        self.generate_monthly_log(today.year, today.month)

        # 4. 지난 달 아카이브도 갱신 (월초인 경우)
        if today.day <= 3:
            prev_month = today.replace(day=1) - timedelta(days=1)
            self.generate_monthly_log(prev_month.year, prev_month.month)
        # 로그 생성 스레드에서 열린 DB 연결 정리
        self.db.close()

    def log_focus_event(self, event_type: str, details: Dict[str, Any]):
        """
        집중 모드 이벤트 DB 기록

        Args:
            event_type: 이벤트 유형 ('emergency_reset', 'app_exit_during_focus', etc.)
            details: 이벤트 상세 정보 dict
        """
        try:
            self.db.add_focus_event(event_type, json.dumps(details, ensure_ascii=False))
        except Exception as e:
            print(f"[LogGenerator] 집중 모드 이벤트 기록 오류: {e}")

    def log_emergency_reset(self, reset_tags: List[str], reason: str):
        """
        긴급 해제 로그 기록 (DB 저장)

        Args:
            reset_tags: 해제된 태그 이름 목록
            reason: 해제 사유
        """
        details = {
            'reset_tags': reset_tags,
            'reason': reason
        }
        self.log_focus_event('emergency_reset', details)
