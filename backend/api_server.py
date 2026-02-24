"""
FastAPI 서버 - 웹 UI용 REST + WebSocket API
"""
API_VERSION = "1.1.0"  # Increment when API changes require webui rebuild

import asyncio
import mimetypes
import os
import subprocess
import sys

# Windows MIME type 문제 해결
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
from datetime import datetime, timedelta
from typing import Optional, List, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
from pathlib import Path
from collections import defaultdict
from urllib.parse import urlparse

from backend.database import DatabaseManager
from backend.focus_time import DEFAULT_BLOCK_START, DEFAULT_BLOCK_END, is_in_block_time


# === Runtime Engine References ===
# main_webview.py에서 설정, 룰/집중 설정 변경 시 reload 호출용
_rule_engine = None
_focus_blocker = None
_log_generator = None
_monitor_engine = None
_event_loop = None


def set_runtime_engines(rule_engine, focus_blocker, log_generator=None, monitor_engine=None, exit_callback=None):
    """런타임 엔진 인스턴스 설정 (main_webview.py에서 호출)"""
    global _rule_engine, _focus_blocker, _log_generator, _monitor_engine, _exit_callback
    _rule_engine = rule_engine
    _focus_blocker = focus_blocker
    _log_generator = log_generator
    _monitor_engine = monitor_engine
    if exit_callback:
        _exit_callback = exit_callback
        print(f"[API] Exit callback set via set_runtime_engines")


def _reload_rule_engine():
    """룰 엔진 새로고침"""
    if _rule_engine:
        _rule_engine.reload_rules()
        print("[API] RuleEngine 새로고침 완료")


def _reload_focus_blocker():
    """집중 모드 새로고침"""
    if _focus_blocker:
        _focus_blocker.reload()
        print("[API] FocusBlocker 새로고침 완료")


def _regenerate_logs():
    """로그 재생성 (설정 변경 시)"""
    if _log_generator:
        import threading
        def generate():
            try:
                from datetime import date
                _log_generator.generate_daily_log(date.today())
                _log_generator.generate_recent_log()
                print("[API] 로그 재생성 완료")
            except Exception as e:
                print(f"[API] 로그 재생성 오류: {e}")
            finally:
                _log_generator.db.close()
        threading.Thread(target=generate, daemon=True).start()


# === Pydantic Models ===

class TagCreate(BaseModel):
    name: str
    color: str
    category: Optional[str] = 'other'  # 'work', 'non_work', 'other'

class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    category: Optional[str] = None  # 'work', 'non_work', 'other'
    alert_enabled: Optional[bool] = None
    alert_message: Optional[str] = None
    alert_cooldown: Optional[int] = None
    block_enabled: Optional[bool] = None
    block_start_time: Optional[str] = None
    block_end_time: Optional[str] = None

class RuleCreate(BaseModel):
    name: str
    tag_id: int
    priority: int = 0
    enabled: bool = True
    process_pattern: Optional[str] = None
    url_pattern: Optional[str] = None
    window_title_pattern: Optional[str] = None
    chrome_profile: Optional[str] = None
    process_path_pattern: Optional[str] = None

class RuleUpdate(BaseModel):
    name: Optional[str] = None
    tag_id: Optional[int] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None
    process_pattern: Optional[str] = None
    url_pattern: Optional[str] = None
    window_title_pattern: Optional[str] = None
    chrome_profile: Optional[str] = None
    process_path_pattern: Optional[str] = None

class SettingsUpdate(BaseModel):
    settings: dict


# === WebSocket Manager ===

class ConnectionManager:
    """WebSocket 연결 관리"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """모든 연결에 메시지 전송"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


# === Global instances ===
ws_manager = ConnectionManager()
db: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    """DB 인스턴스 반환"""
    global db
    if db is None:
        db = DatabaseManager()
    return db


# === Lifespan ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - DB는 get_db()에서 lazy init (race condition 방지)
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    yield
    # Shutdown
    global db
    if db:
        db.close()
        db = None


def schedule_broadcast(message: dict):
    """WebSocket 브로드캐스트를 서버 이벤트 루프에서 안전하게 실행."""
    if _event_loop and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(message), _event_loop)
    else:
        asyncio.run(ws_manager.broadcast(message))


# === FastAPI App ===

app = FastAPI(
    title="Activity Tracker API",
    version="2.0.0",
    lifespan=lifespan
)

# CORS 설정 (개발용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Dashboard Endpoints ===

@app.get("/api/dashboard/daily")
async def get_dashboard_daily(date: str = Query(..., description="YYYY-MM-DD format")):
    """일간 대시보드 통계"""
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")

    start = datetime.combine(target_date.date(), datetime.min.time())
    end = start + timedelta(days=1)

    db = get_db()

    # 태그별 통계
    tag_stats = db.get_stats_by_tag(start, end)
    all_tags = {t['id']: t for t in db.get_all_tags()}

    # 프로세스별 통계
    process_stats = db.get_stats_by_process(start, end, limit=10)

    # 활동 목록 (요약용)
    activities = db.get_activities(start, end)

    # 총 활동 시간 계산 (자리비움 제외)
    total_seconds = sum(
        s.get('total_seconds', 0) or 0
        for s in tag_stats
        if s.get('tag_name') != '자리비움'
    )

    # 태그 통계에서 자리비움 제외 + category 추가
    tag_stats_filtered = []
    for s in tag_stats:
        if s.get('tag_name') == '자리비움':
            continue
        tag_info = all_tags.get(s.get('tag_id'), {})
        s['category'] = tag_info.get('category', 'other')
        tag_stats_filtered.append(s)
    tag_stats = tag_stats_filtered

    # 첫/마지막 활동 시간 + 태그 전환 횟수 계산
    first_activity = None
    last_activity = None
    tag_switches = 0
    prev_tag = None

    if activities:
        sorted_activities = sorted(activities, key=lambda x: x['start_time'])
        first_activity = sorted_activities[0]['start_time']
        last_activity = sorted_activities[-1]['start_time']

        for act in sorted_activities:
            if prev_tag is not None and act.get('tag_id') != prev_tag:
                tag_switches += 1
            prev_tag = act.get('tag_id')

    return {
        "date": date,
        "tagStats": tag_stats,
        "processStats": process_stats,
        "summary": {
            "totalSeconds": total_seconds,
            "activityCount": len(activities),
            "firstActivity": first_activity,
            "lastActivity": last_activity,
            "tagSwitches": tag_switches
        }
    }


@app.get("/api/dashboard/period")
async def get_dashboard_period(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD")
):
    """기간별 대시보드 통계 (분석 페이지용)"""
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date_parsed = datetime.strptime(end, "%Y-%m-%d")
        end_date = end_date_parsed + timedelta(days=1)
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")

    db = get_db()

    # 기본 통계
    tag_stats = db.get_stats_by_tag(start_date, end_date)
    process_stats = db.get_stats_by_process(start_date, end_date, limit=10)

    # 전체 활동 가져오기 (dailyTrend, websiteStats 계산용)
    activities = db.get_activities(start_date, end_date)
    all_tags = {t['id']: t for t in db.get_all_tags()}

    # tagStats에 category 정보 추가 및 자리비움 제외
    tag_stats_filtered = []
    for s in tag_stats:
        if s.get('tag_name') == '자리비움':
            continue
        tag_info = all_tags.get(s.get('tag_id'), {})
        s['category'] = tag_info.get('category', 'other')
        tag_stats_filtered.append(s)

    # === dailyTrend + websiteStats: 한 번의 순회로 계산 ===
    daily_data = defaultdict(lambda: defaultdict(float))
    domain_stats = defaultdict(float)

    for act in activities:
        act_start = act.get('start_time')
        act_end = act.get('end_time')
        tag_id = act.get('tag_id')

        if not act_start:
            continue

        if isinstance(act_start, str):
            act_start = datetime.fromisoformat(act_start)
        if isinstance(act_end, str):
            act_end = datetime.fromisoformat(act_end) if act_end else datetime.now()
        elif act_end is None:
            act_end = datetime.now()

        duration = (act_end - act_start).total_seconds()
        date_key = act_start.strftime("%Y-%m-%d")

        # dailyTrend 집계
        if tag_id:
            daily_data[date_key][tag_id] += duration

        # websiteStats 집계
        chrome_url = act.get('chrome_url')
        if chrome_url:
            try:
                parsed = urlparse(chrome_url)
                domain = parsed.netloc or parsed.path.split('/')[0]
                if domain:
                    domain_stats[domain] += duration
            except Exception:
                pass

    # dailyTrend 형식으로 변환 (category 포함)
    daily_trend = []
    current = start_date
    while current <= end_date_parsed:
        date_key = current.strftime("%Y-%m-%d")
        tags_for_day = []
        for tag_id, seconds in daily_data.get(date_key, {}).items():
            tag_info = all_tags.get(tag_id, {})
            if tag_info.get('name') == '자리비움':
                continue
            tags_for_day.append({
                "tag_id": tag_id,
                "tag_name": tag_info.get('name', '미분류'),
                "tag_color": tag_info.get('color', '#607D8B'),
                "category": tag_info.get('category', 'other'),
                "seconds": round(seconds)
            })
        daily_trend.append({
            "date": date_key,
            "tags": sorted(tags_for_day, key=lambda x: x['seconds'], reverse=True)
        })
        current += timedelta(days=1)

    # websiteStats 형식으로 변환
    website_stats = [
        {"domain": domain, "total_seconds": round(seconds)}
        for domain, seconds in sorted(domain_stats.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    # === summary: 총 활동 시간, 목표 달성 일수 ===
    # 설정에서 목표값 로드 (기본값: 7시간, 20%)
    target_hours = float(db.get_setting('target_daily_hours', '7'))
    target_ratio = float(db.get_setting('target_distraction_ratio', '20')) / 100
    TARGET_DAILY_SECONDS = target_hours * 3600
    TARGET_NON_WORK_RATIO = target_ratio

    total_seconds = sum(s.get('total_seconds', 0) for s in tag_stats_filtered)
    days_count = (end_date_parsed - start_date).days + 1

    # 목표 달성 일수 및 활동일 계산 (category='non_work' 기준)
    goal_achieved_days = 0
    active_days = 0
    for day in daily_trend:
        day_total = sum(t['seconds'] for t in day['tags'])

        if day_total > 0:
            active_days += 1

        # 비업무 시간 = category가 'non_work'인 태그들의 합
        day_non_work = sum(t['seconds'] for t in day['tags'] if t.get('category') == 'non_work')

        if day_total >= TARGET_DAILY_SECONDS:
            non_work_ratio = day_non_work / day_total if day_total > 0 else 0
            if non_work_ratio < TARGET_NON_WORK_RATIO:
                goal_achieved_days += 1

    return {
        "start": start,
        "end": end,
        "tagStats": tag_stats_filtered,
        "processStats": process_stats,
        "dailyTrend": daily_trend,
        "websiteStats": website_stats,
        "summary": {
            "totalSeconds": round(total_seconds),
            "daysCount": days_count,
            "activeDays": active_days,
            "goalAchievedDays": goal_achieved_days
        }
    }


@app.get("/api/dashboard/hourly")
async def get_dashboard_hourly(date: str = Query(..., description="YYYY-MM-DD format")):
    """시간대별 태그 통계 (0시~23시) - SQL 집계로 최적화"""
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")

    db = get_db()
    start = datetime.combine(target_date.date(), datetime.min.time())
    end = start + timedelta(days=1)

    # SQL 집계로 시간대별 통계 조회 (Python 루프 제거)
    raw_stats = db.get_hourly_stats(start, end)

    # 시간대별로 그룹핑
    hourly_data = {h: [] for h in range(24)}
    for row in raw_stats:
        hour = row['hour']
        tag_name = row.get('tag_name', 'Unknown')
        # 자리비움 제외
        if tag_name == '자리비움':
            continue
        seconds = row.get('total_seconds', 0) or 0
        hourly_data[hour].append({
            "tag_id": row['tag_id'],
            "tag_name": tag_name,
            "tag_color": row.get('tag_color', '#888888'),
            "seconds": int(seconds),
            "minutes": round(seconds / 60, 1)
        })

    # 결과 포맷팅
    result = [{"hour": h, "tags": hourly_data[h]} for h in range(24)]

    return {
        "date": date,
        "hourlyStats": result
    }


# === Timeline Endpoints ===

@app.get("/api/timeline")
async def get_timeline(
    date: str = Query(..., description="YYYY-MM-DD format"),
    tag_id: Optional[int] = Query(None, description="Filter by tag ID")
):
    """타임라인 조회"""
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")

    start = datetime.combine(target_date.date(), datetime.min.time())
    end = start + timedelta(days=1)

    db = get_db()
    activities = db.get_activities(start, end, tag_id=tag_id)

    return {
        "date": date,
        "activities": activities
    }


# === Tags Endpoints ===

@app.get("/api/tags")
async def get_tags():
    """모든 태그 조회"""
    db = get_db()
    tags = db.get_all_tags()

    # 각 태그별 룰 개수 추가
    rules = db.get_all_rules()
    rule_counts = {}
    for rule in rules:
        tag_id = rule.get('tag_id')
        rule_counts[tag_id] = rule_counts.get(tag_id, 0) + 1

    for tag in tags:
        tag['rule_count'] = rule_counts.get(tag['id'], 0)

    return {"tags": tags}


@app.post("/api/tags")
async def create_tag(tag: TagCreate):
    """태그 생성"""
    db = get_db()
    tag_id = db.create_tag(tag.name, tag.color, tag.category or 'other')
    _reload_rule_engine()
    return {"id": tag_id, "message": "Tag created"}


@app.put("/api/tags/{tag_id}")
async def update_tag(tag_id: int, tag: TagUpdate):
    """태그 수정"""
    db = get_db()

    existing = db.get_tag_by_id(tag_id)
    if not existing:
        raise HTTPException(404, "Tag not found")

    update_data = tag.model_dump(exclude_unset=True)
    if update_data:
        db.update_tag(tag_id, **update_data)
        _reload_rule_engine()

    return {"message": "Tag updated"}


@app.delete("/api/tags/{tag_id}")
async def delete_tag(tag_id: int):
    """태그 삭제"""
    db = get_db()

    existing = db.get_tag_by_id(tag_id)
    if not existing:
        raise HTTPException(404, "Tag not found")

    db.delete_tag(tag_id)
    _reload_rule_engine()
    return {"message": "Tag deleted"}


# === Rules Endpoints ===

@app.get("/api/rules")
async def get_rules():
    """모든 룰 조회"""
    db = get_db()
    rules = db.get_all_rules()
    return {"rules": rules}


@app.post("/api/rules")
async def create_rule(rule: RuleCreate):
    """룰 생성"""
    db = get_db()
    rule_id = db.create_rule(**rule.model_dump())
    _reload_rule_engine()
    return {"id": rule_id, "message": "Rule created"}


@app.put("/api/rules/{rule_id}")
async def update_rule(rule_id: int, rule: RuleUpdate):
    """룰 수정"""
    db = get_db()

    existing = db.get_rule_by_id(rule_id)
    if not existing:
        raise HTTPException(404, "Rule not found")

    update_data = rule.model_dump(exclude_unset=True)
    if update_data:
        db.update_rule(rule_id, **update_data)
        _reload_rule_engine()

    return {"message": "Rule updated"}


@app.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: int):
    """룰 삭제"""
    db = get_db()

    existing = db.get_rule_by_id(rule_id)
    if not existing:
        raise HTTPException(404, "Rule not found")

    db.delete_rule(rule_id)
    _reload_rule_engine()
    return {"message": "Rule deleted"}


# === Reclassify Endpoints ===

@app.post("/api/reclassify/untagged")
async def reclassify_untagged():
    """미분류 항목 재분류"""
    from backend.rule_engine import RuleEngine

    db = get_db()
    rule_engine = RuleEngine(db)

    # 미분류 활동 가져오기
    unclassified = db.get_unclassified_activities()
    if not unclassified:
        return {"reclassified": 0, "remaining": 0, "message": "No unclassified activities"}

    # 미분류 태그 ID
    unclassified_tag = db.get_tag_by_name('미분류')
    unclassified_tag_id = unclassified_tag['id'] if unclassified_tag else None

    reclassified_count = 0
    for activity in unclassified:
        activity_info = {
            'process_name': activity.get('process_name'),
            'window_title': activity.get('window_title'),
            'process_path': activity.get('process_path'),
            'chrome_url': activity.get('chrome_url'),
            'chrome_profile': activity.get('chrome_profile')
        }

        tag_id, rule_id = rule_engine.match(activity_info)

        # 미분류가 아닌 경우만 업데이트
        if tag_id != unclassified_tag_id:
            db.update_activity_classification(activity['id'], tag_id, rule_id)
            reclassified_count += 1

    return {
        "reclassified": reclassified_count,
        "remaining": len(unclassified) - reclassified_count,
        "message": f"Reclassified {reclassified_count} activities"
    }


@app.post("/api/reclassify/all")
async def reclassify_all():
    """모든 활동 재분류"""
    from backend.rule_engine import RuleEngine

    db = get_db()
    rule_engine = RuleEngine(db)

    # 모든 활동 가져오기
    all_activities = db.get_all_activities_for_reclassify()
    if not all_activities:
        return {"reclassified": 0, "message": "No activities to reclassify"}

    reclassified_count = 0
    for activity in all_activities:
        activity_info = {
            'process_name': activity.get('process_name'),
            'window_title': activity.get('window_title'),
            'process_path': activity.get('process_path'),
            'chrome_url': activity.get('chrome_url'),
            'chrome_profile': activity.get('chrome_profile')
        }

        tag_id, rule_id = rule_engine.match(activity_info)
        db.update_activity_classification(activity['id'], tag_id, rule_id)
        reclassified_count += 1

    return {
        "reclassified": reclassified_count,
        "message": f"Reclassified {reclassified_count} activities"
    }


@app.get("/api/activities/unclassified")
async def get_unclassified_activities():
    """미분류 활동 목록 (그룹화)"""
    db = get_db()
    activities = db.get_unclassified_activities()

    # 프로세스+제목+URL로 그룹화
    grouped = {}
    for act in activities:
        key = (
            act.get('process_name') or '',
            act.get('window_title') or '',
            act.get('chrome_url') or ''
        )
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(act['id'])

    # 정렬 (개수 내림차순)
    result = [
        {
            "process_name": k[0],
            "window_title": k[1],
            "chrome_url": k[2],
            "ids": v,
            "count": len(v)
        }
        for k, v in sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)
    ]

    return {"groups": result, "total": len(activities)}


class ActivityDeleteRequest(BaseModel):
    ids: List[int]


@app.post("/api/activities/delete")
async def delete_activities(data: ActivityDeleteRequest):
    """활동 삭제"""
    db = get_db()
    db.delete_activities(data.ids)
    return {"deleted": len(data.ids), "message": f"Deleted {len(data.ids)} activities"}


# === Settings Endpoints ===

@app.get("/api/settings")
async def get_settings():
    """모든 설정 조회"""
    db = get_db()

    settings_keys = [
        'alert_toast_enabled',
        'alert_sound_enabled',
        'alert_sound_mode',
        'alert_image_enabled',
        'alert_image_mode',
        'log_retention_days',
        'polling_interval',
        'idle_threshold',
        'target_daily_hours',
        'target_distraction_ratio'
    ]

    settings = {}
    for key in settings_keys:
        value = db.get_setting(key)
        settings[key] = value

    return {"settings": settings}


@app.put("/api/settings")
async def update_settings(data: SettingsUpdate):
    """설정 업데이트"""
    db = get_db()

    # 기존 log_retention_days 값 확인
    old_retention = db.get_setting('log_retention_days')

    for key, value in data.settings.items():
        db.set_setting(key, str(value) if value is not None else None)

    # log_retention_days가 변경되면 로그 재생성
    new_retention = data.settings.get('log_retention_days')
    if new_retention and str(new_retention) != str(old_retention):
        _regenerate_logs()

    return {"message": "Settings updated"}


# === Focus Endpoints ===

@app.get("/api/focus")
async def get_focus_settings():
    """집중 모드 설정 조회 (태그별)"""
    db = get_db()
    tags = db.get_all_tags()

    focus_settings = []
    for tag in tags:
        # 자리비움, 미분류 태그는 차단 대상에서 제외
        if tag['name'] in ('자리비움', '미분류'):
            continue

        focus_settings.append({
            "id": tag['id'],
            "name": tag['name'],
            "color": tag['color'],
            "block_enabled": bool(tag.get('block_enabled', 0)),
            "block_start_time": tag.get('block_start_time') or None,
            "block_end_time": tag.get('block_end_time') or None
        })

    return {"focusSettings": focus_settings}


@app.get("/api/focus/status")
async def get_focus_status():
    """현재 활성화된 집중 모드 상태 조회"""
    db = get_db()
    tags = db.get_all_tags()

    active_blocks = []
    for tag in tags:
        if not tag.get('block_enabled'):
            continue
        if tag['name'] in ('자리비움', '미분류'):
            continue

        start_time = tag.get('block_start_time')
        end_time = tag.get('block_end_time')

        if is_in_block_time(start_time, end_time):
            active_blocks.append({
                "id": tag['id'],
                "name": tag['name'],
                "start_time": start_time,
                "end_time": end_time
            })

    return {
        "hasActiveBlocks": len(active_blocks) > 0,
        "activeBlocks": active_blocks
    }


class EmergencyResetRequest(BaseModel):
    reason: str


@app.post("/api/focus/emergency-reset")
async def emergency_reset_focus(data: EmergencyResetRequest):
    """
    집중 모드 긴급 해제

    모든 태그의 block_enabled를 false로 설정하고 로그 기록
    """
    if not data.reason or len(data.reason.strip()) < 10:
        raise HTTPException(400, "사유는 최소 10자 이상 입력해야 합니다.")

    db = get_db()
    tags = db.get_all_tags()

    # block_enabled=true인 태그들 찾아서 해제
    reset_tags = []
    for tag in tags:
        if tag.get('block_enabled'):
            db.update_tag(tag['id'], block_enabled=False)
            reset_tags.append(tag['name'])

    # FocusBlocker 새로고침
    _reload_focus_blocker()

    # 로그 기록
    if _log_generator and reset_tags:
        try:
            _log_generator.log_emergency_reset(reset_tags, data.reason.strip())
        except Exception as e:
            print(f"[API] 긴급해제 로그 기록 오류: {e}")

    return {
        "success": True,
        "reset_count": len(reset_tags),
        "reset_tags": reset_tags
    }


@app.put("/api/focus/{tag_id}")
async def update_focus_settings(tag_id: int, data: TagUpdate):
    """집중 모드 설정 수정"""
    db = get_db()

    existing = db.get_tag_by_id(tag_id)
    if not existing:
        raise HTTPException(404, "Tag not found")

    # 차단 활성 시간대에는 수정 불가 체크
    if existing.get('block_enabled'):
        start_time = existing.get('block_start_time')
        end_time = existing.get('block_end_time')

        if is_in_block_time(start_time, end_time):
            raise HTTPException(403, "Cannot modify during active block period")

    update_data = data.model_dump(exclude_unset=True)
    if update_data.get("block_enabled") is True:
        start_time = update_data.get("block_start_time") or existing.get("block_start_time")
        end_time = update_data.get("block_end_time") or existing.get("block_end_time")
        if not start_time:
            start_time = DEFAULT_BLOCK_START
        if not end_time:
            end_time = DEFAULT_BLOCK_END
        update_data.setdefault("block_start_time", start_time)
        update_data.setdefault("block_end_time", end_time)
    if update_data:
        db.update_tag(tag_id, **update_data)
        _reload_focus_blocker()

    return {"message": "Focus settings updated"}


# === Alert/Notification Endpoints ===

class AlertSettingsUpdate(BaseModel):
    toast_enabled: Optional[bool] = None
    sound_enabled: Optional[bool] = None
    sound_mode: Optional[str] = None  # 'single' | 'random'
    sound_selected: Optional[int] = None
    image_enabled: Optional[bool] = None
    image_mode: Optional[str] = None
    image_selected: Optional[int] = None


class TagAlertUpdate(BaseModel):
    alert_enabled: Optional[bool] = None
    alert_message: Optional[str] = None
    alert_cooldown: Optional[int] = None


# === Alert Endpoints ===

@app.get("/api/alerts/settings")
async def get_alert_settings():
    """전역 알림 설정 조회"""
    db = get_db()
    return {
        "toast_enabled": db.get_setting('alert_toast_enabled', '1') == '1',
        "sound_enabled": db.get_setting('alert_sound_enabled', '0') == '1',
        "sound_mode": db.get_setting('alert_sound_mode', 'single'),
        "sound_selected": int(db.get_setting('alert_sound_selected', '0') or 0),
        "image_enabled": db.get_setting('alert_image_enabled', '0') == '1',
        "image_mode": db.get_setting('alert_image_mode', 'single'),
        "image_selected": int(db.get_setting('alert_image_selected', '0') or 0)
    }


@app.put("/api/alerts/settings")
async def update_alert_settings(data: AlertSettingsUpdate):
    """전역 알림 설정 수정"""
    db = get_db()
    update_data = data.model_dump(exclude_unset=True)

    if 'toast_enabled' in update_data:
        db.set_setting('alert_toast_enabled', '1' if update_data['toast_enabled'] else '0')
    if 'sound_enabled' in update_data:
        db.set_setting('alert_sound_enabled', '1' if update_data['sound_enabled'] else '0')
    if 'sound_mode' in update_data:
        db.set_setting('alert_sound_mode', update_data['sound_mode'])
    if 'sound_selected' in update_data:
        db.set_setting('alert_sound_selected', str(update_data['sound_selected']))
    if 'image_enabled' in update_data:
        db.set_setting('alert_image_enabled', '1' if update_data['image_enabled'] else '0')
    if 'image_mode' in update_data:
        db.set_setting('alert_image_mode', update_data['image_mode'])
    if 'image_selected' in update_data:
        db.set_setting('alert_image_selected', str(update_data['image_selected']))

    return {"message": "Alert settings updated"}


@app.get("/api/alerts/sounds")
async def get_alert_sounds():
    """알림음 목록 조회"""
    db = get_db()
    sounds = db.get_all_alert_sounds()
    selected_id = int(db.get_setting('alert_sound_selected', '0') or 0)
    return {"sounds": sounds, "selected_id": selected_id}


@app.post("/api/alerts/sounds/upload")
async def upload_alert_sound(
    file: UploadFile = File(...),
    name: str = Form(...)
):
    """알림음 업로드"""
    from backend.config import AppConfig

    # 확장자 검증
    allowed_ext = {'.wav'}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_ext:
        raise HTTPException(400, f"Unsupported file type. Allowed: {allowed_ext}")

    sounds_dir = AppConfig.get_sounds_dir()

    # WAV만 지원 (재생 엔진 제약)
    output_name = f"{uuid.uuid4().hex}{file_ext}"
    output_path = sounds_dir / output_name

    content = await file.read()
    with open(output_path, 'wb') as f:
        f.write(content)

    db = get_db()
    sound_id = db.add_alert_sound(name, str(output_path))

    return {"id": sound_id, "name": name, "file_path": str(output_path)}


@app.delete("/api/alerts/sounds/{sound_id}")
async def delete_alert_sound(sound_id: int):
    """알림음 삭제"""
    db = get_db()
    sound = db.get_alert_sound_by_id(sound_id)
    if not sound:
        raise HTTPException(404, "Sound not found")

    # 파일도 삭제
    file_path = Path(sound['file_path'])
    if file_path.exists():
        file_path.unlink()

    db.delete_alert_sound(sound_id)
    return {"message": "Sound deleted"}


@app.get("/api/alerts/images")
async def get_alert_images():
    """알림 이미지 목록 조회"""
    db = get_db()
    images = db.get_all_alert_images()
    selected_id = int(db.get_setting('alert_image_selected', '0') or 0)
    return {"images": images, "selected_id": selected_id}


@app.post("/api/alerts/images/upload")
async def upload_alert_image(
    file: UploadFile = File(...),
    name: str = Form(...)
):
    """알림 이미지 업로드"""
    from backend.config import AppConfig

    # 확장자 검증
    allowed_ext = {'.png', '.jpg', '.jpeg'}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_ext:
        raise HTTPException(400, f"Unsupported file type. Allowed: {allowed_ext}")

    images_dir = AppConfig.get_app_dir() / "images"
    images_dir.mkdir(exist_ok=True)

    output_name = f"{uuid.uuid4().hex}.png"
    output_path = images_dir / output_name

    content = await file.read()

    # 이미지 처리 (PIL로 2:1 비율 리사이즈)
    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(content))

        # 2:1 비율로 크롭 (364x182 권장, hero image 규격)
        target_ratio = 2.0
        current_ratio = img.width / img.height

        if current_ratio > target_ratio:
            # 너무 넓음 - 좌우 자르기
            new_width = int(img.height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img.height))
        elif current_ratio < target_ratio:
            # 너무 높음 - 상하 자르기
            new_height = int(img.width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, img.width, top + new_height))

        # 리사이즈
        img = img.resize((364, 182), Image.Resampling.LANCZOS)

        # PNG로 저장
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        img.save(str(output_path), 'PNG')

    except ImportError:
        # PIL 없으면 그냥 저장
        with open(output_path, 'wb') as f:
            f.write(content)

    db = get_db()
    image_id = db.add_alert_image(name, str(output_path))

    return {"id": image_id, "name": name, "file_path": str(output_path)}


@app.delete("/api/alerts/images/{image_id}")
async def delete_alert_image(image_id: int):
    """알림 이미지 삭제"""
    db = get_db()
    image = db.get_alert_image_by_id(image_id)
    if not image:
        raise HTTPException(404, "Image not found")

    # 파일도 삭제
    file_path = Path(image['file_path'])
    if file_path.exists():
        file_path.unlink()

    db.delete_alert_image(image_id)
    return {"message": "Image deleted"}


@app.get("/api/alerts/images/file/{image_id}")
async def get_alert_image_file(image_id: int):
    """알림 이미지 파일 서빙"""
    db = get_db()
    image = db.get_alert_image_by_id(image_id)
    if not image:
        raise HTTPException(404, "Image not found")

    file_path = Path(image['file_path'])
    if not file_path.exists():
        raise HTTPException(404, "Image file not found")

    return FileResponse(file_path, media_type="image/png")


@app.post("/api/open/appdata")
async def open_appdata_folder():
    """앱 데이터 폴더 열기"""
    from backend.config import AppConfig

    app_dir = AppConfig.get_app_dir()
    try:
        if os.name == 'nt':
            os.startfile(app_dir)  # type: ignore[attr-defined]
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(app_dir)])
        else:
            subprocess.Popen(['xdg-open', str(app_dir)])
    except Exception as e:
        raise HTTPException(500, f"Failed to open app data folder: {e}")

    return {"message": "App data folder opened"}


@app.get("/api/alerts/tags")
async def get_tag_alert_settings():
    """태그별 알림 설정 조회"""
    db = get_db()
    tags = db.get_all_tags()

    result = []
    for tag in tags:
        # 자리비움, 미분류는 알림 대상에서 제외
        if tag['name'] in ('자리비움', '미분류'):
            continue

        result.append({
            "id": tag['id'],
            "name": tag['name'],
            "color": tag['color'],
            "alert_enabled": bool(tag.get('alert_enabled', 0)),
            "alert_message": tag.get('alert_message') or '',
            "alert_cooldown": tag.get('alert_cooldown') or 30
        })

    return {"tags": result}


@app.put("/api/alerts/tags/{tag_id}")
async def update_tag_alert_settings(tag_id: int, data: TagAlertUpdate):
    """태그별 알림 설정 수정"""
    db = get_db()

    existing = db.get_tag_by_id(tag_id)
    if not existing:
        raise HTTPException(404, "Tag not found")

    update_data = data.model_dump(exclude_unset=True)
    if update_data:
        db.update_tag(tag_id, **update_data)

    return {"message": "Tag alert settings updated"}


# === Auto Start & Data Management Endpoints ===

@app.get("/api/settings/autostart")
async def get_autostart_status():
    """자동 시작 설정 상태 조회"""
    from backend.auto_start import AutoStartManager
    return {"enabled": AutoStartManager.is_enabled()}


@app.put("/api/settings/autostart")
async def set_autostart_status(data: dict):
    """자동 시작 설정 변경"""
    from backend.auto_start import AutoStartManager

    enabled = data.get('enabled', False)

    if enabled:
        success = AutoStartManager.enable()
    else:
        success = AutoStartManager.disable()

    if not success:
        raise HTTPException(500, "Failed to update auto-start setting")

    return {"enabled": AutoStartManager.is_enabled()}


@app.get("/api/settings/theme")
async def get_theme():
    """테마 설정 조회"""
    db = get_db()
    theme = db.get_setting('theme', 'dark')
    return {"theme": theme}


@app.put("/api/settings/theme")
async def set_theme(data: dict):
    """테마 설정 변경"""
    db = get_db()
    theme = data.get('theme', 'dark')
    if theme not in ('dark', 'light'):
        raise HTTPException(400, "Invalid theme value")
    db.set_setting('theme', theme)
    return {"theme": theme}


@app.get("/api/data/db/backup")
async def backup_database(include_media: bool = Query(True)):
    """데이터베이스 + 알림 파일 백업 (zip 다운로드)"""
    from fastapi.responses import FileResponse
    from backend.import_export import ImportExportManager
    import tempfile

    db = get_db()
    ie_manager = ImportExportManager(db)

    # 임시 파일에 백업
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"activity_tracker_backup_{timestamp}.zip" if include_media else f"activity_tracker_backup_{timestamp}.db"
    backup_path = Path(tempfile.gettempdir()) / backup_name

    if include_media:
        success = ie_manager.export_full_backup(str(backup_path))
    else:
        success = ie_manager.export_database(str(backup_path))

    if not success:
        raise HTTPException(500, "Failed to create backup")

    return FileResponse(
        path=str(backup_path),
        filename=backup_name,
        media_type="application/octet-stream"
    )


@app.post("/api/data/db/restore")
async def restore_database(file: UploadFile = File(...)):
    """데이터베이스 복원 (앱 재시작 필요)"""
    import json
    import sqlite3
    import tempfile
    import zipfile
    from backend.config import AppConfig

    # 확장자 검증
    filename = file.filename or ""
    is_db = filename.lower().endswith('.db')
    is_zip = filename.lower().endswith('.zip')
    if not is_db and not is_zip:
        raise HTTPException(400, "Invalid file type. Only .db or .zip files are allowed.")

    content = await file.read()
    if is_db:
        # 복원 예약 파일로 저장
        pending_db_path = AppConfig.get_restore_pending_db_path()
        with open(pending_db_path, 'wb') as f:
            f.write(content)

        try:
            conn = sqlite3.connect(str(pending_db_path))
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            conn.close()
        except Exception as e:
            if pending_db_path.exists():
                pending_db_path.unlink()
            raise HTTPException(400, f"복원 파일이 유효하지 않습니다: {e}")

        if result != "ok":
            pending_db_path.unlink()
            raise HTTPException(400, f"복원 파일이 유효하지 않습니다: {result}")
    else:
        pending_zip_path = AppConfig.get_restore_pending_media_path()
        with open(pending_zip_path, 'wb') as f:
            f.write(content)

        try:
            with zipfile.ZipFile(pending_zip_path, 'r') as zip_file:
                if "activity_tracker.db" not in zip_file.namelist():
                    raise HTTPException(400, "복원 zip에 activity_tracker.db가 없습니다.")
                with tempfile.TemporaryDirectory() as temp_dir:
                    zip_file.extract("activity_tracker.db", temp_dir)
                    temp_db_path = Path(temp_dir) / "activity_tracker.db"
                    conn = sqlite3.connect(str(temp_db_path))
                    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                    conn.close()
        except HTTPException:
            if pending_zip_path.exists():
                pending_zip_path.unlink()
            raise
        except Exception as e:
            if pending_zip_path.exists():
                pending_zip_path.unlink()
            raise HTTPException(400, f"복원 파일이 유효하지 않습니다: {e}")

        if result != "ok":
            if pending_zip_path.exists():
                pending_zip_path.unlink()
            raise HTTPException(400, f"복원 파일이 유효하지 않습니다: {result}")

    meta = {
        "original_name": file.filename,
        "created_at": datetime.now().isoformat(),
        "backup_type": "zip" if is_zip else "db"
    }
    AppConfig.get_restore_pending_path().write_text(json.dumps(meta), encoding="utf-8")

    if _exit_callback:
        asyncio.get_event_loop().call_later(0.5, _exit_callback)

    return {"message": "복원이 예약되었습니다. 앱을 재시작하면 적용됩니다.", "restart_required": True}


@app.get("/api/data/rules/export")
async def export_rules():
    """분류 룰 내보내기 (JSON)"""
    from backend.import_export import ImportExportManager

    db = get_db()
    ie_manager = ImportExportManager(db)

    tags = db.get_all_tags()
    rules = db.get_all_rules(order_by='priority DESC')

    export_data = {
        "export_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "tags": tags,
        "rules": rules
    }

    return export_data


@app.post("/api/data/rules/import")
async def import_rules(
    file: UploadFile = File(...),
    merge_mode: bool = Form(True)
):
    """분류 룰 가져오기 (JSON)"""
    from backend.import_export import ImportExportManager
    import tempfile

    # 확장자 검증
    if not file.filename.endswith('.json'):
        raise HTTPException(400, "Invalid file type. Only .json files are allowed.")

    # 임시 파일로 저장
    temp_path = Path(tempfile.gettempdir()) / f"rules_{uuid.uuid4().hex}.json"

    content = await file.read()
    with open(temp_path, 'wb') as f:
        f.write(content)

    db = get_db()
    ie_manager = ImportExportManager(db)

    # 유효성 검증
    valid, message, preview = ie_manager.validate_rules_json(str(temp_path))

    if not valid:
        temp_path.unlink()
        raise HTTPException(400, message)

    # Import 실행
    success, result_message, stats = ie_manager.import_rules(str(temp_path), merge_mode)

    # 임시 파일 삭제
    if temp_path.exists():
        temp_path.unlink()

    if not success:
        raise HTTPException(500, result_message)

    _reload_rule_engine()

    return {
        "message": result_message,
        "stats": stats,
        "preview": preview
    }


# === WebSocket Endpoint ===

@app.websocket("/ws/activity")
async def websocket_activity(websocket: WebSocket):
    """실시간 활동 업데이트 WebSocket"""
    await ws_manager.connect(websocket)
    try:
        while True:
            # 클라이언트 메시지 대기 (ping/pong)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# === Health Check ===

@app.get("/api/health")
async def health_check():
    """헬스 체크"""
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "api_version": API_VERSION}


# === System ===

# 종료 콜백 (main_webview.py에서 설정)
_exit_callback = None


def set_exit_callback(callback):
    """종료 콜백 설정"""
    global _exit_callback
    _exit_callback = callback
    print(f"[API] Exit callback set: {callback}")




@app.post("/api/system/exit")
async def system_exit():
    """앱 종료"""
    import threading

    def do_exit():
        import time
        time.sleep(0.5)
        if _exit_callback:
            _exit_callback()
        else:
            import os
            os._exit(0)

    threading.Thread(target=do_exit, daemon=True).start()
    return {"message": "Shutting down..."}


# === Static Files (Web UI) ===

# dist 폴더 경로 (PyInstaller/개발환경 모두 대응)
def _resolve_dist_path() -> Path:
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "webui" / "dist")
    # PyInstaller 6.x: _internal 폴더 구조
    candidates.append(Path(sys.executable).parent / "_internal" / "webui" / "dist")
    candidates.append(Path(sys.executable).parent / "webui" / "dist")
    candidates.append(Path(__file__).parent.parent / "webui" / "dist")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]

_dist_path = _resolve_dist_path()

if _dist_path.exists():
    # 정적 파일 서빙 (CSS, JS, assets)
    app.mount("/assets", StaticFiles(directory=_dist_path / "assets"), name="assets")

    # 루트 및 SPA 폴백
    @app.get("/")
    async def serve_root():
        return HTMLResponse((_dist_path / "index.html").read_text(encoding="utf-8"))


def _resolve_resources_path() -> Path:
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "resources")
    candidates.append(Path(sys.executable).parent / "_internal" / "resources")
    candidates.append(Path(sys.executable).parent / "resources")
    candidates.append(Path(__file__).parent.parent / "resources")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


_resources_path = _resolve_resources_path()
if _resources_path.exists():
    app.mount("/resources", StaticFiles(directory=_resources_path), name="resources")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """SPA 폴백 - 모든 경로를 index.html로"""
        # API나 WebSocket 경로는 제외
        if path.startswith("api/") or path.startswith("ws/"):
            raise HTTPException(404)
        return HTMLResponse((_dist_path / "index.html").read_text(encoding="utf-8"))


# === Run Server (for development) ===

def run_server(host: str = "127.0.0.1", port: int = 8000):
    """개발용 서버 실행"""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
