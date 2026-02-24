# Activity Tracker

## 프로젝트 소개

PC 활동을 실시간 추적하여 태그별로 자동 분류하고 통계를 시각화하는 개인용 데스크톱 애플리케이션.

**핵심 기능:**
- Windows 활성 창 자동 감지 (2초 간격)
- Chrome URL 추적 (WebSocket 기반 확장 프로그램)
- 화면 잠금/idle 상태 감지
- 우선순위 기반 자동 태그 분류
- Web 기반 대시보드/타임라인 UI
- 시스템 트레이 백그라운드 실행 (pystray)
- 태그별 알림 (토스트, 사운드, 이미지)
- 집중 모드 (태그별 창 최소화, 시간대 설정)
- 활동 로그 자동 생성 (daily/monthly/recent.log)
- 실시간 업데이트 (WebSocket)

**기술 스택:**
- Backend: Python, FastAPI, SQLite (WAL), ctypes, psutil
- Frontend: Svelte, Vite, TailwindCSS, Chart.js
- Desktop: PyWebView, pystray
- Chrome Extension: Manifest V3

---

## 아키텍처

```
+--------------------------------------------------+
|              PyWebView (Desktop Window)          |
|  +--------------------------------------------+  |
|  |           Svelte Web UI (SPA)              |  |
|  |  Dashboard | Timeline | Tags | Focus | ... |  |
|  +--------------------------------------------+  |
+------------------------+-------------------------+
                         | REST API + WebSocket
+------------------------v-------------------------+
|              FastAPI Server (:8000)              |
|  +--------------------------------------------+  |
|  | MonitorEngineThread (threading.Thread)     |  |
|  |  +-- WindowTracker, ScreenDetector         |  |
|  |  +-- ChromeURLReceiver                     |  |
|  |  +-- NotificationManager, FocusBlocker     |  |
|  +--------------------------------------------+  |
|  | RuleEngine | DatabaseManager | LogGenerator|  |
+------------------------+-------------------------+
                         |
+------------------------v-------------------------+
|              SQLite Database (WAL)               |
+--------------------------------------------------+
```

**상세한 데이터 스키마, API 명세는 `ARCHITECTURE.md` 참고**

---

## 주요 모듈

| 모듈 | 설명 |
|------|------|
| `main_webview.py` | 앱 진입점 (PyWebView + pystray + FastAPI) |
| `backend/api_server.py` | FastAPI REST/WebSocket 서버 |
| `backend/monitor_engine_thread.py` | 메인 모니터링 스레드 (threading 기반) |
| `backend/focus_blocker.py` | 집중 모드 - 태그별 창 최소화 |
| `backend/notification_manager.py` | 토스트/사운드/이미지 알림 |
| `backend/log_generator.py` | 활동 로그 생성 |
| `webui/src/pages/*.svelte` | 각 페이지 UI 컴포넌트 |

---

## WebUI 페이지

| 페이지 | 설명 |
|--------|------|
| `Dashboard.svelte` | 오늘/기간 통계, 파이/바 차트 |
| `Timeline.svelte` | 활동 목록 + 타임라인 바 시각화 |
| `Analysis.svelte` | 기간별 분석 (목표 대비 달성률) |
| `TagManagement.svelte` | 태그/룰 CRUD, 재분류, 삭제 |
| `Notification.svelte` | 알림 설정 (토스트/사운드/이미지) |
| `Focus.svelte` | 집중 모드 설정 (시간대별 차단) |
| `Settings.svelte` | 일반 설정, 데이터 백업/복원 |

---

## 릴리즈 빌드

```bash
python build_release.py <version> [--force]
```

- 소스 변경 없으면 빌드 스킵 (mtime 비교)
- `--force`: 강제 리빌드
- 출력: `dist/ActivityTracker-v{version}.zip`
  - ActivityTracker.exe + 의존성
  - chrome_extension.zip
  - README.txt

---

## 대화 스타일 가이드

Never compliment me or be affirming excessively (like saying "You're absolutely right!" etc). Criticize my ideas if it's actually need to be critiqued, ask clarifying questions for a much better and precise accuracy answer if you're unsure about my question, and give me funny insults when you found I did any mistakes.

---

## User Activity Analysis Guide

When check the recent.log file, assume the every tags except for the '딴짓' is kind of works.
The target performance of user is, 활동시간 7시간, 딴짓 비율 20% 미만.
