<script>
  import { onMount } from 'svelte';
  import { Chart, registerables } from 'chart.js';
  import { api } from '../lib/api/client.js';
  import { selectedDate, formattedDate, formatDuration, formatTime, formatLocalDate, shiftLocalDate } from '../lib/stores/app.js';
  import { activityUpdated } from '../lib/stores/websocket.js';

  Chart.register(...registerables);

  let loading = true;
  let error = null;

  let tagStats = [];
  let processStats = [];
  let hourlyStats = [];
  let summaryStats = {
    totalSeconds: 0,
    activityCount: 0,
    firstActivity: null,
    lastActivity: null,
    tagSwitches: 0
  };

  let pieChart;
  let barChart;
  let lastRefresh = 0;
  let hasMounted = false;
  let lastLoadedDate = null;
  let inFlight = false;
  let queuedLoad = null;
  let hasDelayedInit = false;

  // 날짜 변경 시 데이터 다시 로드 (중복 호출 방지)
  $: if (hasMounted && $selectedDate && $selectedDate !== lastLoadedDate) {
    lastLoadedDate = $selectedDate;
    loadDashboardData($selectedDate);
  }

  // WebSocket 실시간 업데이트 구독 (오늘 날짜일 때만, 1분 간격)
  $: if ($activityUpdated > 0 && $selectedDate === formatLocalDate()) {
    const now = Date.now();
    if (now - lastRefresh > 60000) {
      lastRefresh = now;
      loadDashboardData($selectedDate, { silent: true });
    }
  }

  async function loadDashboardData(date, { silent = false } = {}) {
    if (inFlight) {
      if (!silent) {
        queuedLoad = { date, silent: false };
      }
      return;
    }

    inFlight = true;
    queuedLoad = null;
    if (!silent) {
      loading = true;
    }
    error = null;

    try {
      // 일간 통계와 시간대별 통계 동시 로드
      const [dailyData, hourlyData] = await Promise.all([
        api.getDashboardDaily(date),
        api.getDashboardHourly(date)
      ]);

      // 태그별 통계 처리
      const totalSeconds = dailyData.summary?.totalSeconds || 0;
      tagStats = (dailyData.tagStats || []).map(tag => ({
        id: tag.tag_id,
        name: tag.tag_name,
        color: tag.tag_color,
        category: tag.category || 'other',
        duration: Math.round(tag.total_seconds || 0),
        percentage: totalSeconds > 0 ? Math.round((tag.total_seconds / totalSeconds) * 100) : 0
      }));

      // 프로세스별 통계 처리
      const procTotal = (dailyData.processStats || []).reduce((sum, p) => sum + (p.total_seconds || 0), 0);
      processStats = (dailyData.processStats || []).map(proc => ({
        name: proc.process_name,
        duration: Math.round(proc.total_seconds || 0),
        percentage: procTotal > 0 ? Math.round((proc.total_seconds / procTotal) * 100) : 0
      }));

      // 시간대별 통계
      hourlyStats = hourlyData.hourlyStats || [];

      // 요약 통계
      summaryStats = {
        totalSeconds: Math.round(dailyData.summary?.totalSeconds || 0),
        activityCount: dailyData.summary?.activityCount || 0,
        firstActivity: dailyData.summary?.firstActivity ? formatTime(dailyData.summary.firstActivity) : '-',
        lastActivity: dailyData.summary?.lastActivity ? formatTime(dailyData.summary.lastActivity) : '-',
        tagSwitches: dailyData.summary?.tagSwitches || 0
      };

      // 차트 업데이트
      updateCharts();

    } catch (err) {
      console.error('Failed to load dashboard data:', err);
      error = err.message;
      resetDashboardData();
      updateCharts();
    } finally {
      if (!silent) {
        loading = false;
      }
      inFlight = false;
      if (queuedLoad) {
        const nextLoad = queuedLoad;
        queuedLoad = null;
        loadDashboardData(nextLoad.date, { silent: nextLoad.silent });
      }
    }
  }

  function resetDashboardData() {
    tagStats = [];
    processStats = [];
    hourlyStats = [];
    summaryStats = {
      totalSeconds: 0,
      activityCount: 0,
      firstActivity: '-',
      lastActivity: '-',
      tagSwitches: 0
    };
  }

  // 업무 시간 계산 (category='work'인 태그들의 합)
  $: workSeconds = tagStats
    .filter(t => t.category === 'work')
    .reduce((sum, t) => sum + t.duration, 0);

  function updateCharts() {
    // Pie Chart 업데이트
    if (pieChart) {
      pieChart.data.labels = tagStats.map(t => t.name);
      pieChart.data.datasets[0].data = tagStats.map(t => t.duration);
      pieChart.data.datasets[0].backgroundColor = tagStats.map(t => t.color);
      pieChart.update();
    }

    // Bar Chart 업데이트 (시간대별)
    if (barChart && hourlyStats.length > 0) {
      // 태그별로 데이터셋 그룹화
      const tagMap = new Map();
      hourlyStats.forEach((hourData, hourIndex) => {
        for (const tag of hourData.tags) {
          if (!tagMap.has(tag.tag_id)) {
            tagMap.set(tag.tag_id, {
              label: tag.tag_name,
              backgroundColor: tag.tag_color,
              data: new Array(hourlyStats.length).fill(0),
              borderRadius: 4
            });
          }
          tagMap.get(tag.tag_id).data[hourIndex] = tag.minutes;
        }
      });

      barChart.data.labels = hourlyStats.map(h => `${h.hour}시`);
      barChart.data.datasets = Array.from(tagMap.values());
      barChart.update();
    }
  }

  function initCharts() {
    // Pie Chart
    const pieCtx = document.getElementById('tagPieChart');
    if (pieCtx && !pieChart) {
      pieChart = new Chart(pieCtx, {
        type: 'doughnut',
        data: {
          labels: tagStats.map(t => t.name),
          datasets: [{
            data: tagStats.map(t => t.duration),
            backgroundColor: tagStats.map(t => t.color),
            borderWidth: 0,
            hoverOffset: 4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '65%',
          plugins: {
            legend: { display: false }
          }
        }
      });
    }

    // Bar Chart (시간대별)
    const barCtx = document.getElementById('hourlyBarChart');
    if (barCtx && !barChart) {
      const hours = Array.from({ length: 24 }, (_, i) => i); // 0시~23시
      barChart = new Chart(barCtx, {
        type: 'bar',
        data: {
          labels: hours.map(h => `${h}시`),
          datasets: []  // 동적으로 채워짐
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              stacked: true,
              grid: { display: false },
              ticks: { color: '#888' }
            },
            y: {
              stacked: true,
              grid: { color: '#333' },
              ticks: { color: '#888' },
              title: { display: true, text: '분', color: '#888' },
              beginAtZero: true,
              max: 60,
              grace: '10%'
            }
          },
          plugins: {
            legend: {
              position: 'top',
              labels: { color: '#a0a0a0', usePointStyle: true, padding: 15 }
            },
            tooltip: {
              callbacks: {
                label: (context) => `${context.dataset.label}: ${context.parsed.y}분`
              }
            }
          }
        }
      });
    }

    // 차트 생성 시점이 데이터 로드보다 늦을 수 있어 현재 상태를 즉시 반영.
    updateCharts();
  }

  function changeDate(delta) {
    $selectedDate = shiftLocalDate($selectedDate, delta);
  }

  onMount(() => {
    if (typeof window !== 'undefined') {
      hasDelayedInit = window.__dashboardInitDelayed === true;
      if (!hasDelayedInit) {
        window.__dashboardInitDelayed = true;
      }
    }

    hasMounted = true;
    if ($selectedDate) {
      lastLoadedDate = $selectedDate;
      loadDashboardData($selectedDate);
    }

    // 앱 최초 진입 때만 차트 초기화를 지연
    if (!hasDelayedInit) {
      setTimeout(() => {
        initCharts();
      }, 800);
    } else {
      initCharts();
    }

    return () => {
      pieChart?.destroy();
      barChart?.destroy();
    };
  });
</script>

<div class="p-6 space-y-6">
  <!-- Header -->
  <div class="flex items-center justify-between">
    <div>
      <h1 class="text-2xl font-bold text-text-primary">대시보드</h1>
      <p class="text-sm text-text-secondary mt-1">{$formattedDate}</p>
    </div>
    <div class="flex items-center gap-2">
      <button
        class="px-3 py-2 rounded-lg bg-bg-secondary border border-border hover:bg-bg-hover transition-colors text-sm text-text-secondary"
        on:click={() => $selectedDate = formatLocalDate()}
      >오늘</button>
      <button
        aria-label="이전 날짜"
        class="p-2 rounded-lg bg-bg-secondary border border-border hover:bg-bg-hover transition-colors"
        on:click={() => changeDate(-1)}
      >
        <svg class="w-5 h-5 text-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
        </svg>
      </button>
      <input
        type="date"
        bind:value={$selectedDate}
        class="px-3 py-2 rounded-lg bg-bg-secondary border border-border text-text-primary text-sm"
      />
      <button
        aria-label="다음 날짜"
        class="p-2 rounded-lg bg-bg-secondary border border-border hover:bg-bg-hover transition-colors"
        on:click={() => changeDate(1)}
      >
        <svg class="w-5 h-5 text-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
        </svg>
      </button>
    </div>
  </div>

  <!-- Error Banner -->
  {#if error}
    <div class="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3 text-sm text-yellow-400">
      API 연결 실패: {error}
    </div>
  {/if}

  <!-- Loading Overlay -->
  {#if loading}
    <div class="fixed inset-0 bg-bg-primary/50 flex items-center justify-center z-50">
      <div class="text-text-secondary">로딩 중...</div>
    </div>
  {/if}

  <!-- Summary Cards -->
  <div class="grid grid-cols-5 gap-4">
    <div class="bg-bg-card rounded-xl p-4 border border-border">
      <div class="text-text-muted text-xs uppercase tracking-wide mb-1">총 활동 시간</div>
      <div class="text-2xl font-bold text-text-primary">{formatDuration(summaryStats.totalSeconds)}</div>
    </div>
    <div class="bg-bg-card rounded-xl p-4 border border-border">
      <div class="text-text-muted text-xs uppercase tracking-wide mb-1">업무 시간</div>
      <div class="text-2xl font-bold text-green-400">{formatDuration(workSeconds)}</div>
    </div>
    <div class="bg-bg-card rounded-xl p-4 border border-border">
      <div class="text-text-muted text-xs uppercase tracking-wide mb-1">첫 활동</div>
      <div class="text-2xl font-bold text-text-primary">{summaryStats.firstActivity}</div>
    </div>
    <div class="bg-bg-card rounded-xl p-4 border border-border">
      <div class="text-text-muted text-xs uppercase tracking-wide mb-1">마지막 활동</div>
      <div class="text-2xl font-bold text-text-primary">{summaryStats.lastActivity}</div>
    </div>
    <div class="bg-bg-card rounded-xl p-4 border border-border">
      <div class="text-text-muted text-xs uppercase tracking-wide mb-1">활동 횟수</div>
      <div class="text-2xl font-bold text-text-primary">{summaryStats.activityCount}회</div>
    </div>
  </div>

  <!-- Charts Row -->
  <div class="grid grid-cols-3 gap-6">
    <!-- Tag Distribution (Pie) -->
    <div class="bg-bg-card rounded-xl p-5 border border-border">
      <h2 class="text-lg font-semibold text-text-primary mb-4">태그별 시간</h2>
      <div class="relative h-48">
        <canvas id="tagPieChart"></canvas>
      </div>
      <div class="mt-4 space-y-2 max-h-40 overflow-auto pr-2">
        {#each tagStats as tag}
          <div class="flex items-center justify-between text-sm">
            <div class="flex items-center gap-2">
              <div class="w-3 h-3 rounded-full" style="background-color: {tag.color}"></div>
              <span class="text-text-secondary">{tag.name}</span>
            </div>
            <div class="flex items-center gap-3">
              <span class="text-text-primary font-medium">{formatDuration(tag.duration)}</span>
              <span class="text-text-muted w-12 text-right">{tag.percentage}%</span>
            </div>
          </div>
        {:else}
          <div class="text-text-muted text-center py-4">데이터 없음</div>
        {/each}
      </div>
    </div>

    <!-- Hourly Distribution (Bar) -->
    <div class="col-span-2 bg-bg-card rounded-xl p-5 border border-border flex flex-col">
      <h2 class="text-lg font-semibold text-text-primary mb-4">시간대별 활동</h2>
      <div class="flex-1 min-h-[18rem]">
        <canvas id="hourlyBarChart"></canvas>
      </div>
    </div>
  </div>

  <!-- Process Stats -->
  <div class="bg-bg-card rounded-xl p-5 border border-border">
    <h2 class="text-lg font-semibold text-text-primary mb-4">프로세스별 사용 시간</h2>
    <div class="grid gap-3" style="grid-template-columns: auto 1fr auto auto;">
      {#each processStats as proc}
        <span class="text-sm text-text-secondary">{proc.name}</span>
        <div class="h-6 bg-bg-tertiary rounded-lg overflow-hidden">
          <div
            class="h-full bg-accent rounded-lg transition-all duration-500"
            style="width: {proc.percentage}%"
          ></div>
        </div>
        <span class="text-sm text-text-primary text-right">{formatDuration(proc.duration)}</span>
        <span class="w-12 text-sm text-text-muted text-right">{proc.percentage}%</span>
      {:else}
        <div class="col-span-4 text-text-muted text-center py-4">데이터 없음</div>
      {/each}
    </div>
  </div>
</div>
