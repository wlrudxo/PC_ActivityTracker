# Activity Tracker - Architecture

## Overview

Activity Tracker는 Windows 데스크톱에서 사용자의 활동을 추적하고 태그 기반으로 분류해 통계와 알림을 제공하는 PyWebView 앱이다. 백엔드는 FastAPI + SQLite로 구성되고, 모니터링 엔진이 활성 창/잠금/유휴/Chrome URL을 감지하여 활동 로그와 통계를 만든다. 웹 UI는 Svelte SPA로 구성되며 PyWebView에서 로드된다.

핵심 특징:
- 활성 창 + Chrome URL + 잠금/유휴 상태 감지
- 룰 기반 자동 태그 분류 (우선순위, 패턴 매칭)
- 태그별 알림 (토스트/사운드/이미지)
- 집중 모드 (태그 + 시간대 기반 창 최소화)
- 일별/최근/월별 활동 로그 생성
- DB/룰 백업/복원, 룰 가져오기/내보내기

---

## System Architecture

```
+------------------------------------------------------------------+
|                       PyWebView App (main_webview.pyw)            |
|  - PyWebView window + JS API (backup/export/exit)                 |
|  - pystray tray icon                                               |
|  - starts FastAPI server + monitor engine                          |
+-------------------------------+----------------------------------+
                                |
                                | HTTP + WebSocket
+-------------------------------v----------------------------------+
|                          FastAPI API Server                        |
|  - REST: /api/*                                                     |
|  - WS:   /ws/activity                                               |
|  - Static: webui/dist (SPA)                                         |
+-------------------------------+----------------------------------+
                                | runtime engines
+-------------------------------v----------------------------------+
|                        Backend Runtime (threading)                |
|  MonitorEngineThread                                               |
|   + WindowTracker (ctypes + psutil)                                |
|   + ScreenDetector (lock/idle)                                     |
|   + ChromeURLReceiver (WebSocket server :8766)                     |
|   + NotificationManager (windows-toasts + winsound)                |
|   + FocusBlocker (window minimize)                                 |
|  RuleEngine (priority-based matching)                              |
|  ActivityLogGenerator (daily/recent/monthly logs)                  |
|  ImportExportManager (DB + rule backup/restore)                    |
|  DatabaseManager (thread-local SQLite, WAL)                        |
+-------------------------------+----------------------------------+
                                |
+-------------------------------v----------------------------------+
|                         SQLite Database (WAL)                      |
|  tags, activities, rules, settings, alert_sounds, alert_images      |
+------------------------------------------------------------------+

+-----------------------------------------------------------+
|                Chrome Extension (Manifest V3)             |
|  WebSocket client (ws://localhost:8766)                   |
|  Active tab URL/profile push + auto-reconnect             |
+-----------------------------------------------------------+
```

---

## Runtime Components

### main_webview.pyw
- FastAPI 서버를 별도 스레드로 기동하고 모니터링 엔진을 실행.
- PyWebView JS API 제공: DB 백업/룰 내보내기 저장 다이얼로그, 앱 종료.
- 트레이 아이콘(열기/종료)과 단일 인스턴스 보장(Windows mutex + 포트 체크).
- DB 복원 예약이 있으면 앱 시작 전에 교체 적용.

### FastAPI (backend/api_server.py)
- REST + WebSocket API 제공.
- 룰/집중 모드 변경 시 런타임 엔진에 reload 요청.
- 로그 보관 설정 변경 시 최근 로그 재생성.
- 빌드/개발 환경 모두에서 `webui/dist` 정적 파일 서빙 (SPA fallback).

### MonitorEngineThread (backend/monitor_engine_thread.py)
- 폴링 간격/idle 임계값은 settings 테이블에서 매 루프 갱신.
- 활동 변경 시 기존 활동 종료, 새 활동 생성, 알림 및 차단 처리.
- 날짜 변경 감지 시 로그 생성(일별 + recent).
- DB 복원을 위한 일시정지/DB 연결 닫기 요청 지원.

### RuleEngine (backend/rule_engine.py)
- enabled 룰을 우선순위 내림차순으로 적용.
- process/url/title/profile/path 중 하나라도 일치하면 매칭(OR).
- 패턴은 콤마 분리 + fnmatch 와일드카드(`*`, `?`).

### DatabaseManager (backend/database.py)
- 스레드별 SQLite 연결 + WAL 모드.
- 기본 태그 시드: 업무, 휴식, 자리비움, 미분류.
- 알림 이미지/사운드 기본 리소스 시드.
- settings, tags, rules, activities, alert_sounds, alert_images 관리.

### NotificationManager (backend/notification_manager.py)
- windows-toasts 기반 토스트 표시(히어로 이미지 지원).
- 사운드는 별도 스레드에서 재생, 태그별 쿨다운 적용.

### FocusBlocker (backend/focus_blocker.py)
- 태그별 차단 시간대를 확인하고 해당 창을 최소화.
- 자정 넘김 시간대 지원(예: 22:00~02:00).

### ActivityLogGenerator (backend/log_generator.py)
- `activity_logs/daily/*.log`, `recent.log`, `monthly/*.log` 생성.
- 보관 일수는 `log_retention_days` 설정 사용.

### ImportExportManager (backend/import_export.py)
- SQLite backup API로 DB 백업.
- 복원 시 무결성 검사 + WAL 정리 + 롤백 지원.
- 룰 JSON 내보내기/가져오기(병합/교체 모드).

---

## Web UI (Svelte SPA)

- 라우팅: `/`(Dashboard), `/timeline`, `/analysis`, `/tags`, `/notification`, `/focus`, `/settings`
- API 베이스:
  - `file://` 로딩 시 `http://127.0.0.1:8000/api`
  - 개발 서버/프로덕션 HTTP에서는 상대 경로 `/api`
- WebSocket 연결:
  - `file://` → `ws://127.0.0.1:8000/ws/activity`
  - HTTP(S) → 동일 호스트의 `/ws/activity`

페이지 기능 요약:
- Dashboard: 일간 통계 + 시간대별 차트(Chart.js)
- Timeline: 날짜/태그 필터, 타임라인 바 + 테이블
- Analysis: 기간 분석, 목표 달성 지표, 태그/프로세스/웹사이트 TOP
- Tag Management: 태그/룰 CRUD, 미분류 재분류, 미분류 삭제
- Notification: 알림 설정, 사운드/이미지 업로드, 태그별 알림 설정
- Focus: 태그별 차단 시간 설정 및 활성화 상태 표시
- Settings: 앱 설정, 자동 시작, 백업/복원, 룰 가져오기/내보내기

---

## Data Flow

### 1) Activity Tracking Loop
```
MonitorEngineThread.run() [polling_interval]
  -> collect_activity_info()
      1) screen locked -> __LOCKED__
      2) idle > threshold -> __IDLE__
      3) active window + optional Chrome URL
  -> _is_activity_changed() ?
      YES: end_current_activity() + start_new_activity()
           -> RuleEngine.match() -> tag_id, rule_id
           -> DatabaseManager.create_activity()
           -> NotificationManager + FocusBlocker
           -> WebSocket broadcast
      NO:  -> alert + focus re-check
```

### 2) Chrome URL Tracking
```
Chrome Extension
  -> ws://localhost:8766
  -> ChromeURLReceiver.latest_data 갱신
  -> MonitorEngineThread에서 최신 URL 조회
```

### 3) Web UI Updates
```
Svelte UI
  -> REST /api/* 조회/수정
  -> WS /ws/activity 로 실시간 업데이트
```

### 4) Alerts + Focus
```
MonitorEngineThread
  -> NotificationManager.show(tag_id, message)
  -> FocusBlocker.check_and_block(tag_id, hwnd)
```

### 5) Backup/Restore
```
Settings UI
  -> DB backup/export: REST or PyWebView JS API
  -> DB restore: 업로드 후 복원 예약 (앱 재시작 시 적용)
```

---

## Database Schema (요약)

### tags
- `name`(unique), `color`, `category`(work/non_work/other)
- 알림: `alert_enabled`, `alert_message`, `alert_cooldown`
- 집중 모드: `block_enabled`, `block_start_time`, `block_end_time`

### activities
- `start_time`, `end_time`, `process_name`, `window_title`
- `chrome_url`, `chrome_profile`, `tag_id`, `rule_id`

### rules
- `priority`, `enabled`
- 패턴: `process_pattern`, `url_pattern`, `window_title_pattern`, `process_path_pattern`
- `chrome_profile`, `tag_id`

### settings
- 알림: `alert_toast_enabled`, `alert_sound_enabled`, `alert_sound_mode`, `alert_sound_selected`,
  `alert_image_enabled`, `alert_image_mode`, `alert_image_selected`
- 모니터링: `polling_interval`, `idle_threshold`
- 로그/분석: `log_retention_days`, `target_daily_hours`, `target_distraction_ratio`

### alert_sounds / alert_images
- 사용자 업로드된 알림 사운드/이미지 목록

---

## Tech Stack

Backend:
- Python 3.x, SQLite (WAL)
- FastAPI, Uvicorn, websockets
- threading, asyncio
- ctypes (Windows API), psutil
- windows-toasts, winsound

Frontend:
- Svelte + Vite
- TailwindCSS
- Chart.js

Desktop:
- PyWebView (EdgeChromium)
- pystray

Chrome Extension:
- Manifest V3
- WebSocket client
