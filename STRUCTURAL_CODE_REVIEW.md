# Structural Code Review

작성일: 2026-04-05

## 범위

- 백엔드: `main_webview.pyw`, `backend/*.py`
- 프론트엔드: `webui/src/**/*`
- 목적: 구조적 비효율, 과도한 책임, 중복 책임, 고아/레거시 코드 후보를 찾는 것

## 총평

이 프로젝트는 기능은 분명하게 나뉘어 있는데, 실제 구현은 그 경계가 많이 무너져 있다. 특히 다음 네 지점에 책임이 과도하게 집중되어 있다.

- 앱 부트스트랩과 런타임 제어: `main_webview.pyw`
- HTTP API + 애플리케이션 서비스 + 런타임 제어: `backend/api_server.py`
- 스키마/마이그레이션/시드/조회/집계/자산 정리: `backend/database.py`
- 페이지 단위 상태 머신: `webui/src/pages/Settings.svelte`, `Notification.svelte`, `TagManagement.svelte`

파일 크기만 봐도 집중도가 높다.

- `main_webview.pyw`: 905 lines
- `backend/api_server.py`: 1522 lines
- `backend/database.py`: 842 lines
- `webui/src/pages/Settings.svelte`: 918 lines
- `webui/src/pages/Notification.svelte`: 902 lines
- `webui/src/pages/TagManagement.svelte`: 900 lines

또한 `backend/api_server.py` 안에 라우트가 47개, `backend/database.py` 안에 메서드가 41개 있다. 기능이 많아서라기보다, 계층이 얇고 한 파일이 여러 역할을 동시에 떠안고 있다는 신호에 가깝다.

## 주요 Findings

### 1. `main_webview.pyw`가 앱 조립기 이상으로 비대해져 있다

증거:

- 서버 스레드 구현: `main_webview.pyw:119`
- 네이티브 JS API: `main_webview.pyw:166`
- 앱 상태/런타임 객체 보유: `main_webview.pyw:259`
- 모니터링 엔진 조립: `main_webview.pyw:295`
- 종료 처리: `main_webview.pyw:542`
- 전체 부트 순서 제어: `main_webview.pyw:569`

문제:

- 부트스트랩, 런타임 배선, PyWebView 브리지, 트레이, 종료 시나리오, 서버 준비 검사, 로그 초기화가 한 클래스에 모여 있다.
- 테스트 가능한 단위가 거의 없고, 종료/복원/재시작 같은 라이프사이클 변경이 다른 기능을 쉽게 건드리게 된다.
- 앱 셸이어야 할 파일이 사실상 orchestration layer + infrastructure layer + desktop adapter 역할을 같이 하고 있다.

권장:

- `AppBootstrap`, `DesktopShell`, `RuntimeCoordinator`, `WebViewBridge` 정도로 분리
- `ActivityTrackerApp`는 조립만 하고 실제 동작은 하위 서비스에 위임

### 2. `backend/api_server.py`가 API 계층이 아니라 사실상 “애플리케이션 본체” 역할을 하고 있다

증거:

- 전역 런타임 레지스트리: `backend/api_server.py:34-40`
- 런타임 제어 함수: `backend/api_server.py:43-83`
- 전역 DB 싱글톤: `backend/api_server.py:155-165`
- 설정 API와 부수효과: `backend/api_server.py:721-763`
- 앱 종료/복원 예약: `backend/api_server.py:1322-1452`
- 정적 파일 서빙까지 포함: `backend/api_server.py:1455` 이후

문제:

- HTTP endpoint, 요청 검증, DB 조회, 응답 조합, 로그 재생성, 룰 리로드, 종료 콜백, 정적 파일 서빙이 한 모듈에 있다.
- `_rule_engine`, `_focus_blocker`, `_log_generator`, `_monitor_engine`, `_exit_callback`, `_event_loop` 같은 전역 mutable state에 의존한다.
- API 계층이 런타임 객체의 구체 타입과 수명주기를 직접 알아야 해서 결합도가 높다.
- 이 구조에서는 기능이 늘수록 “엔드포인트 추가”가 아니라 “본체 확장”이 된다.

권장:

- `routers/` + `services/` + `runtime_registry` 또는 `app_context`로 분리
- API는 service 호출만 하고, reload/regen/exit는 service 또는 command handler가 담당
- 전역 변수 대신 명시적 context 주입

### 3. `DatabaseManager`가 저장소 계층을 넘어 스키마/마이그레이션/시드/자산 정리까지 모두 떠안고 있다

증거:

- 스레드별 connection 관리: `backend/database.py:34-45`
- 스키마 생성과 컬럼 마이그레이션: `backend/database.py:47-177`
- 시드 상태 판정과 기본 데이터 주입: `backend/database.py:187-277`
- 자산 경로 정리: `backend/database.py:279-315`
- 이후 CRUD/통계/집중모드 이벤트 등 다수 메서드: `backend/database.py:495` 이후

문제:

- 저장소 객체 생성만으로 `init_database()`가 실행되고, 거기서 테이블 생성, `ALTER TABLE`, 기본 룰 import, 알림 자산 reconcile/seed까지 전부 수행된다.
- `backend.database`가 `backend.import_export.ImportExportManager`를 불러 기본 룰 JSON을 import하는 방식은 계층을 거꾸로 타는 side effect다. `backend/database.py:255-272`
- 마이그레이션 실패를 광범위한 `except Exception: pass`로 삼키는 패턴이 많아 실제 스키마 이상이 숨어버릴 수 있다. `backend/database.py:99-177`

권장:

- `schema.py` / `migrations.py` / `seed.py` / `repositories.py` 분리
- 앱 시작 시 명시적으로 migration/seed를 실행
- `DatabaseManager`는 connection + transaction + repository factory 정도로 축소

### 4. 라이프사이클 책임이 여러 곳에 중복되어 있다

증거:

- 미종료 활동 정리 1: `main_webview.pyw:297-298`
- 미종료 활동 정리 2: `backend/monitor_engine_thread.py:89-90`
- 종료 콜백 등록 1: `main_webview.pyw:320-326`
- 종료 콜백 등록 2: `main_webview.pyw:608-610`
- 로그 재생성 진입점 1: `backend/api_server.py:69-83`
- 로그 재생성 진입점 2: `backend/monitor_engine_thread.py:168-178`

문제:

- 같은 초기화/종료 책임이 여러 곳에 나뉘어 있으면, 이후 변경 시 어느 경로를 기준으로 봐야 하는지 불명확해진다.
- 지금은 운 좋게 큰 충돌이 없더라도, 복원/재시작/종료 시나리오가 늘면 순서 의존 버그가 생길 가능성이 높다.
- 특히 `cleanup_unfinished_activities()`의 중복 호출은 “어디서 이걸 책임져야 하는가”가 이미 흐려졌다는 신호다.

권장:

- 시작/종료/복원/재시작에 대한 단일 lifecycle coordinator 두기
- 각 책임을 “부트 직후 1회”, “모니터 스레드 시작 직전”, “앱 종료 직전”처럼 한 위치로 고정

### 5. 프론트엔드의 핵심 페이지들이 너무 많은 상태와 플로우를 직접 들고 있다

증거:

- `webui/src/pages/Settings.svelte:10-61` 다수 상태 변수
- `webui/src/pages/Settings.svelte:71-353` 설정, 자동시작, 백업/복원, 룰 import/export, 종료, 긴급해제 로직 혼재
- `webui/src/pages/Notification.svelte:13-62` 전역 설정, 파일 업로드, 삭제, crop 상태 혼재
- `webui/src/pages/Notification.svelte:215-426` 이미지 편집/canvas 처리까지 페이지 내부 보유
- `webui/src/pages/TagManagement.svelte:16-37` 모달/선택/재분류 상태 다수
- `webui/src/pages/TagManagement.svelte:70-260` 태그 CRUD, 룰 CRUD, 재분류, 삭제 플로우 혼재

문제:

- “페이지”가 화면 조합 단위를 넘어 독립적인 state machine처럼 커져 있다.
- 모달 open/confirm/cancel, API 호출 후 `await loadData()`, `toast.success/error` 패턴이 반복된다.
- 테스트와 수정 포인트가 분리되지 않아 작은 UI 변경도 쉽게 회귀를 만든다.

권장:

- 도메인별 composable store 또는 feature module 분리
- 예: `settings/general`, `settings/backup`, `settings/system`, `notification/assets`, `notification/tag-alerts`, `tags/rules`, `tags/reclassify`
- crop 로직은 별도 컴포넌트 또는 유틸로 분리

### 6. 장애를 가리는 데모/폴백 로직이 운영 관점에서 위험하다

증거:

- API 실패 시 데모 데이터 주입: `webui/src/pages/Dashboard.svelte:104-110`
- 실제 배너 문구: `webui/src/pages/Dashboard.svelte:331-334`

문제:

- 백엔드 연결 실패 시 대시보드가 빈 화면이 아니라 “그럴듯한 가짜 데이터”를 보여준다.
- 개발 초기에 유용했던 폴백일 수는 있지만, 운영 앱에서는 장애 인지가 늦어진다.
- 연구실에서 사용 제한/추적 용도라면, “현재 데이터가 진짜인지”가 기능보다 더 중요할 수 있다.

권장:

- 운영 빌드에서는 데모 폴백 제거
- 필요하면 개발 모드에서만 샘플 데이터 허용

## 중복/고아 코드 후보

### 우선 정리할 중복

- `cleanup_unfinished_activities()` 이중 호출
  - `main_webview.pyw:297-298`
  - `backend/monitor_engine_thread.py:89-90`

- 종료 콜백 등록 경로 이중화
  - `set_runtime_engines(..., self.quit_app)` 호출: `main_webview.pyw:320-326`
  - `set_exit_callback(self.quit_app)` 별도 호출: `main_webview.pyw:608-610`
  - 실제 API 모듈에도 두 경로 모두 존재: `backend/api_server.py:43-52`, `backend/api_server.py:1428-1431`

- 로그 갱신 진입점 분산
  - 설정 변경 시: `backend/api_server.py:758-761`
  - 날짜 변경 시: `backend/monitor_engine_thread.py:168-178`
  - 앱 시작 시: `main_webview.pyw:328-342`

### 레거시/고아 후보

- 대시보드의 데모 데이터 로더
  - `webui/src/pages/Dashboard.svelte:124-144`
  - 개발용 흔적에 가깝고, 운영 앱에서는 오해를 유발할 수 있다.

- `backend/database.py` 안의 기본 룰 JSON import
  - `backend/database.py:255-272`
  - 저장소 계층 관점에서는 위치가 어색하고, 초기 부트스트랩/시드 계층으로 이동하는 편이 맞다.

## 리팩터링 우선순위

### 1차

- `backend/api_server.py`를 router/service/runtime-control로 분리
- `main_webview.pyw`에서 lifecycle coordinator 분리
- Dashboard의 데모 데이터 폴백 제거

### 2차

- `DatabaseManager`에서 migration/seed/reconcile 분리
- `Settings.svelte`, `Notification.svelte`, `TagManagement.svelte`를 feature 단위로 쪼개기

### 3차

- 설정 키를 공통 스키마로 정의해 백엔드/프론트 중복 제거
- 공통 mutation 패턴(`API 호출 -> reload -> toast`)을 helper/store로 추출

## 권장 구조 예시

### 백엔드

- `backend/app_context.py`
- `backend/runtime/`
- `backend/routers/`
- `backend/services/`
- `backend/repositories/`
- `backend/db/schema.py`
- `backend/db/migrations.py`
- `backend/db/seeds.py`

### 프론트엔드

- `webui/src/features/settings/`
- `webui/src/features/notification/`
- `webui/src/features/tags/`
- `webui/src/features/dashboard/`
- `webui/src/lib/services/`
- `webui/src/lib/forms/`

## 결론

현재 코드는 “기능을 빨리 붙여서 실제로 돌아가게 만든 앱”의 전형적인 성장 흔적을 갖고 있다. 가장 큰 문제는 개별 구현의 품질보다도, 앱 수명주기와 도메인 로직과 UI 플로우가 각자 자기 계층 안에 갇히지 못하고 서로 섞여 있다는 점이다.

리팩터링은 전체 재작성보다 아래 순서가 효율적이다.

1. 라이프사이클과 런타임 제어를 한곳으로 모은다.
2. API 계층에서 비즈니스 로직과 인프라 제어를 떼어낸다.
3. 프론트 대형 페이지를 feature 단위로 분리한다.

이 세 가지만 먼저 해도 이후 기능 추가 비용과 회귀 위험이 꽤 줄어들 것이다.
