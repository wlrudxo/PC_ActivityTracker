<script>
  import { onMount } from 'svelte';
  import { Chart, registerables } from 'chart.js';
  import { api } from '../lib/api/client.js';
  import { formatDuration, formatLocalDate } from '../lib/stores/app.js';
  import HelpModal from '../lib/components/HelpModal.svelte';
  import HelpButton from '../lib/components/HelpButton.svelte';

  Chart.register(...registerables);

  let showHelp = false;

  // 기간 선택 (기본값: 최근 7일)
  const today = new Date();
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 6);

  let startDate = formatLocalDate(weekAgo);
  let endDate = formatLocalDate(today);

  // 데이터
  let loading = false;
  let error = null;
  let periodStats = null;
  let dailyTrend = [];
  let tagStats = [];
  let processStats = [];
  let websiteStats = [];

  // 목표 기준 (설정에서 로드, 기본값 적용)
  let TARGET_DAILY_HOURS = 7;
  let TARGET_NON_WORK_RATIO = 0.20;

  // 차트 인스턴스
  let trendChart;
  let comparisonChart;

  // 마운트 완료 플래그
  let mounted = false;

  // 초기화: 설정 로드 + 최근 7일
  onMount(async () => {
    // 설정에서 목표값 로드
    try {
      const settingsRes = await api.getSettings();
      TARGET_DAILY_HOURS = parseFloat(settingsRes.settings?.target_daily_hours) || 7;
      TARGET_NON_WORK_RATIO = (parseFloat(settingsRes.settings?.target_distraction_ratio) || 20) / 100;
    } catch (err) {
      console.warn('Failed to load goal settings, using defaults');
    }

    initCharts();
    mounted = true;  // reactive statement가 데이터 로드 트리거

    return () => {
      trendChart?.destroy();
      comparisonChart?.destroy();
    };
  });

  // 날짜 변경 시 데이터 로드 (마운트 후에만)
  $: if (mounted && startDate && endDate) {
    loadPeriodData();
  }

  function setQuickRange(range) {
    const today = new Date();
    let start, end;

    switch (range) {
      case '7days':
        end = new Date(today);
        start = new Date(today);
        start.setDate(start.getDate() - 6);
        break;
      case '30days':
        end = new Date(today);
        start = new Date(today);
        start.setDate(start.getDate() - 29);
        break;
      case 'thisMonth':
        start = new Date(today.getFullYear(), today.getMonth(), 1);
        end = new Date(today);
        break;
      case 'lastMonth':
        start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
        end = new Date(today.getFullYear(), today.getMonth(), 0);
        break;
    }

    startDate = formatLocalDate(start);
    endDate = formatLocalDate(end);
  }

  async function loadPeriodData() {
    if (!startDate || !endDate) return;

    loading = true;
    error = null;

    try {
      const data = await api.getDashboardPeriod(startDate, endDate);

      // 기간 요약 통계
      periodStats = data.summary || {};

      // 일별 트렌드 데이터
      dailyTrend = data.dailyTrend || [];

      // 태그별 통계 (자리비움 제외, category 포함)
      const totalSeconds = data.tagStats?.reduce((sum, t) => sum + (t.total_seconds || 0), 0) || 0;
      tagStats = (data.tagStats || [])
        .filter(t => t.tag_name !== '자리비움')
        .map(tag => ({
          id: tag.tag_id,
          name: tag.tag_name,
          color: tag.tag_color,
          category: tag.category || 'other',
          duration: Math.round(tag.total_seconds || 0),
          percentage: totalSeconds > 0 ? ((tag.total_seconds / totalSeconds) * 100).toFixed(1) : 0
        }));

      // 프로세스별 통계
      processStats = (data.processStats || []).slice(0, 10).map(proc => ({
        name: proc.process_name,
        duration: Math.round(proc.total_seconds || 0)
      }));

      // 웹사이트별 통계 (있으면)
      websiteStats = (data.websiteStats || []).slice(0, 10).map(site => ({
        domain: site.domain,
        duration: Math.round(site.total_seconds || 0)
      }));

      updateCharts();

    } catch (err) {
      console.error('Failed to load period data:', err);
      error = err.message;
      loadDemoData();
    } finally {
      loading = false;
    }
  }

  function loadDemoData() {
    const days = getDaysBetween(startDate, endDate);

    periodStats = {
      totalSeconds: 7 * 6 * 3600,  // 7일 * 6시간
      daysCount: days,
      goalAchievedDays: 4
    };

    dailyTrend = Array.from({ length: days }, (_, i) => {
      const date = new Date(startDate);
      date.setDate(date.getDate() + i);
      return {
        date: formatLocalDate(date),
        tags: [
          { tag_name: '업무', tag_color: '#4CAF50', category: 'work', seconds: 18000 + Math.random() * 7200 },
          { tag_name: '휴식', tag_color: '#FF5722', category: 'non_work', seconds: 3600 + Math.random() * 3600 }
        ]
      };
    });

    tagStats = [
      { id: 1, name: '업무', color: '#4CAF50', category: 'work', duration: 126000, percentage: '70.0' },
      { id: 2, name: '휴식', color: '#FF5722', category: 'non_work', duration: 36000, percentage: '20.0' },
      { id: 3, name: '미분류', color: '#607D8B', category: 'other', duration: 18000, percentage: '10.0' }
    ];

    processStats = [
      { name: 'chrome.exe', duration: 72000 },
      { name: 'Code.exe', duration: 54000 },
      { name: 'explorer.exe', duration: 18000 },
      { name: 'Discord.exe', duration: 14400 },
      { name: 'Slack.exe', duration: 10800 }
    ];

    websiteStats = [
      { domain: 'github.com', duration: 28800 },
      { domain: 'stackoverflow.com', duration: 14400 },
      { domain: 'youtube.com', duration: 10800 },
      { domain: 'google.com', duration: 7200 },
      { domain: 'notion.so', duration: 5400 }
    ];

    updateCharts();
  }

  function getDaysBetween(start, end) {
    const s = new Date(start);
    const e = new Date(end);
    return Math.ceil((e - s) / (1000 * 60 * 60 * 24)) + 1;
  }

  // 계산된 지표들
  $: daysCount = getDaysBetween(startDate, endDate);

  $: totalActivitySeconds = periodStats?.totalSeconds ||
    tagStats.reduce((sum, t) => sum + t.duration, 0);

  // 활동이 있는 날만 카운트 (출근 안 한 날 제외)
  $: activeDays = periodStats?.activeDays ?? countActiveDays();
  $: dailyAverageSeconds = activeDays > 0 ? totalActivitySeconds / activeDays : 0;
  $: dailyAverageHours = dailyAverageSeconds / 3600;

  function countActiveDays() {
    return dailyTrend.filter(d => d.tags && d.tags.length > 0).length;
  }

  // 비업무 비율 계산 (category='non_work'인 태그들의 합)
  $: nonWorkSeconds = tagStats
    .filter(t => t.category === 'non_work')
    .reduce((sum, t) => sum + t.duration, 0);
  $: nonWorkRatio = totalActivitySeconds > 0
    ? (nonWorkSeconds / totalActivitySeconds) * 100
    : 0;

  $: goalAchievedDays = periodStats?.goalAchievedDays ?? calculateGoalDays();

  function calculateGoalDays() {
    // 실제 데이터에서 목표 달성 일수 계산 (category='non_work' 기준)
    let count = 0;
    for (const day of dailyTrend) {
      const dayTotal = day.tags?.reduce((sum, t) => sum + (t.seconds || 0), 0) || 0;
      const dayNonWork = day.tags
        ?.filter(t => t.category === 'non_work')
        .reduce((sum, t) => sum + (t.seconds || 0), 0) || 0;

      const dayHours = dayTotal / 3600;
      const dayNonWorkRatio = dayTotal > 0 ? dayNonWork / dayTotal : 0;

      if (dayHours >= TARGET_DAILY_HOURS && dayNonWorkRatio < TARGET_NON_WORK_RATIO) {
        count++;
      }
    }
    return count;
  }

  // 지표 상태 판단
  $: dailyAverageStatus = dailyAverageHours >= TARGET_DAILY_HOURS ? 'good' : 'warning';
  $: nonWorkStatus = nonWorkRatio < TARGET_NON_WORK_RATIO * 100 ? 'good' : 'warning';
  $: goalRatio = daysCount > 0 ? (goalAchievedDays / daysCount) * 100 : 0;
  $: goalStatus = goalRatio >= 70 ? 'good' : goalRatio >= 50 ? 'warning' : 'danger';

  function initCharts() {
    // 트렌드 차트 (Stacked Bar)
    const trendCtx = document.getElementById('trendChart');
    if (trendCtx && !trendChart) {
      trendChart = new Chart(trendCtx, {
        type: 'bar',
        data: {
          labels: [],
          datasets: []
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              stacked: true,
              grid: { display: false },
              ticks: { color: '#888', maxRotation: 45, minRotation: 45 }
            },
            y: {
              stacked: true,
              grid: { color: '#333' },
              ticks: {
                color: '#888',
                callback: (value) => `${(value / 3600).toFixed(0)}h`
              },
              title: { display: true, text: '시간', color: '#888' }
            }
          },
          plugins: {
            legend: {
              position: 'top',
              labels: { color: '#a0a0a0', usePointStyle: true, padding: 15 }
            },
            tooltip: {
              callbacks: {
                label: (context) => {
                  const hours = (context.parsed.y / 3600).toFixed(1);
                  return `${context.dataset.label}: ${hours}시간`;
                }
              }
            }
          }
        }
      });
    }

    // 주중 vs 주말 비교 차트
    const compCtx = document.getElementById('comparisonChart');
    if (compCtx && !comparisonChart) {
      comparisonChart = new Chart(compCtx, {
        type: 'bar',
        data: {
          labels: ['주중 평균', '주말 평균'],
          datasets: [{
            label: '활동 시간',
            data: [0, 0],
            backgroundColor: ['#4CAF50', '#2196F3'],
            borderRadius: 4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          indexAxis: 'y',
          scales: {
            x: {
              grid: { color: '#333' },
              ticks: {
                color: '#888',
                callback: (value) => `${(value / 3600).toFixed(0)}h`
              }
            },
            y: {
              grid: { display: false },
              ticks: { color: '#888' }
            }
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (context) => {
                  const hours = (context.parsed.x / 3600).toFixed(1);
                  return `${hours}시간`;
                }
              }
            }
          }
        }
      });
    }
  }

  function updateCharts() {
    // 트렌드 차트 업데이트
    if (trendChart && dailyTrend.length > 0) {
      const tagMap = new Map();

      for (const day of dailyTrend) {
        for (const tag of (day.tags || [])) {
          if (tag.tag_name === '자리비움') continue;

          if (!tagMap.has(tag.tag_name)) {
            tagMap.set(tag.tag_name, {
              label: tag.tag_name,
              backgroundColor: tag.tag_color,
              data: new Array(dailyTrend.length).fill(0),
              borderRadius: 4
            });
          }
          const dayIndex = dailyTrend.indexOf(day);
          tagMap.get(tag.tag_name).data[dayIndex] = tag.seconds || 0;
        }
      }

      trendChart.data.labels = dailyTrend.map(d => {
        const date = new Date(d.date);
        return `${date.getMonth() + 1}/${date.getDate()}`;
      });
      trendChart.data.datasets = Array.from(tagMap.values());
      trendChart.update();
    }

    // 주중/주말 비교 차트 업데이트
    if (comparisonChart && dailyTrend.length > 0) {
      let weekdayTotal = 0, weekdayCount = 0;
      let weekendTotal = 0, weekendCount = 0;

      for (const day of dailyTrend) {
        const date = new Date(day.date);
        const dayOfWeek = date.getDay();
        const dayTotal = day.tags?.reduce((sum, t) => {
          if (t.tag_name === '자리비움') return sum;
          return sum + (t.seconds || 0);
        }, 0) || 0;

        if (dayOfWeek === 0 || dayOfWeek === 6) {
          weekendTotal += dayTotal;
          if (dayTotal > 0) weekendCount++;
        } else {
          weekdayTotal += dayTotal;
          if (dayTotal > 0) weekdayCount++;
        }
      }

      comparisonChart.data.datasets[0].data = [
        weekdayCount > 0 ? weekdayTotal / weekdayCount : 0,
        weekendCount > 0 ? weekendTotal / weekendCount : 0
      ];
      comparisonChart.update();
    }
  }

  function formatDateRange() {
    const start = new Date(startDate);
    const end = new Date(endDate);
    const opts = { month: 'short', day: 'numeric' };
    return `${start.toLocaleDateString('ko-KR', opts)} ~ ${end.toLocaleDateString('ko-KR', opts)}`;
  }
</script>

<div class="p-6 space-y-6">
  <!-- Header -->
  <div class="flex items-center justify-between">
    <div>
      <div class="flex items-center gap-2">
        <h1 class="text-2xl font-bold text-text-primary">분석</h1>
        <HelpButton on:click={() => showHelp = true} />
      </div>
      <p class="text-sm text-text-secondary mt-1">{formatDateRange()} ({daysCount}일)</p>
    </div>
  </div>

  <!-- Date Range Selector -->
  <div class="bg-bg-card rounded-xl p-4 border border-border">
    <div class="flex items-center gap-4 flex-wrap">
      <!-- Quick Range Buttons -->
      <div class="flex gap-2">
        <button
          class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
            bg-accent/10 text-accent hover:bg-accent/20"
          on:click={() => setQuickRange('7days')}
        >
          최근 7일
        </button>
        <button
          class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
            bg-bg-tertiary text-text-secondary hover:bg-bg-hover"
          on:click={() => setQuickRange('30days')}
        >
          최근 30일
        </button>
        <button
          class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
            bg-bg-tertiary text-text-secondary hover:bg-bg-hover"
          on:click={() => setQuickRange('thisMonth')}
        >
          이번 달
        </button>
        <button
          class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
            bg-bg-tertiary text-text-secondary hover:bg-bg-hover"
          on:click={() => setQuickRange('lastMonth')}
        >
          지난 달
        </button>
      </div>

      <!-- Date Pickers -->
      <div class="flex items-center gap-2 ml-auto">
        <input
          type="date"
          bind:value={startDate}
          class="px-3 py-1.5 rounded-lg bg-bg-secondary border border-border text-text-primary text-sm"
        />
        <span class="text-text-muted">~</span>
        <input
          type="date"
          bind:value={endDate}
          class="px-3 py-1.5 rounded-lg bg-bg-secondary border border-border text-text-primary text-sm"
        />
      </div>
    </div>
  </div>

  <!-- Error Banner -->
  {#if error}
    <div class="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-3 text-sm text-yellow-400">
      API 연결 실패: {error} (데모 데이터 표시 중)
    </div>
  {/if}

  <!-- Loading Overlay -->
  {#if loading}
    <div class="fixed inset-0 bg-bg-primary/50 flex items-center justify-center z-50">
      <div class="text-text-secondary">로딩 중...</div>
    </div>
  {/if}

  <!-- KPI Cards -->
  <div class="grid grid-cols-4 gap-4">
    <!-- Total Activity Time -->
    <div class="bg-bg-card rounded-xl p-4 border border-border">
      <div class="text-text-muted text-xs uppercase tracking-wide mb-1">총 활동 시간</div>
      <div class="text-2xl font-bold text-text-primary">{formatDuration(totalActivitySeconds)}</div>
      <div class="text-xs text-text-muted mt-1">{daysCount}일 합계</div>
    </div>

    <!-- Daily Average -->
    <div class="bg-bg-card rounded-xl p-4 border border-border">
      <div class="text-text-muted text-xs uppercase tracking-wide mb-1">일 평균 활동 ({activeDays}일)</div>
      <div class="text-2xl font-bold {dailyAverageStatus === 'good' ? 'text-green-400' : 'text-yellow-400'}">
        {dailyAverageHours.toFixed(1)}시간
      </div>
      <div class="text-xs {dailyAverageStatus === 'good' ? 'text-green-400' : 'text-yellow-400'} mt-1">
        목표 {TARGET_DAILY_HOURS}시간 {dailyAverageStatus === 'good' ? '달성' : '미달'}
      </div>
    </div>

    <!-- Non-Work Ratio -->
    <div class="bg-bg-card rounded-xl p-4 border border-border">
      <div class="text-text-muted text-xs uppercase tracking-wide mb-1">비업무 비율</div>
      <div class="text-2xl font-bold {nonWorkStatus === 'good' ? 'text-green-400' : 'text-red-400'}">
        {nonWorkRatio.toFixed(1)}%
      </div>
      <div class="text-xs {nonWorkStatus === 'good' ? 'text-green-400' : 'text-red-400'} mt-1">
        목표 {TARGET_NON_WORK_RATIO * 100}% 미만 {nonWorkStatus === 'good' ? '달성' : '초과'}
      </div>
    </div>

    <!-- Goal Achieved Days -->
    <div class="bg-bg-card rounded-xl p-4 border border-border">
      <div class="text-text-muted text-xs uppercase tracking-wide mb-1">목표 달성 일수</div>
      <div class="text-2xl font-bold
        {goalStatus === 'good' ? 'text-green-400' : goalStatus === 'warning' ? 'text-yellow-400' : 'text-red-400'}">
        {goalAchievedDays}/{daysCount}일
      </div>
      <div class="text-xs text-text-muted mt-1">
        {TARGET_DAILY_HOURS}시간 + 비업무 {Math.round(TARGET_NON_WORK_RATIO * 100)}% 미만
      </div>
    </div>
  </div>

  <!-- Trend Chart -->
  <div class="bg-bg-card rounded-xl p-5 border border-border">
    <h2 class="text-lg font-semibold text-text-primary mb-4">일별 활동 트렌드</h2>
    <div class="h-72">
      <canvas id="trendChart"></canvas>
    </div>
  </div>

  <!-- Two Column: Tag Stats Table + Weekday/Weekend Comparison -->
  <div class="grid grid-cols-3 gap-6">
    <!-- Tag Stats Table -->
    <div class="col-span-2 bg-bg-card rounded-xl p-5 border border-border">
      <h2 class="text-lg font-semibold text-text-primary mb-4">태그별 통계</h2>
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead>
            <tr class="border-b border-border">
              <th class="text-left py-2 px-3 text-xs text-text-muted uppercase">태그</th>
              <th class="text-right py-2 px-3 text-xs text-text-muted uppercase">총 시간</th>
              <th class="text-right py-2 px-3 text-xs text-text-muted uppercase">일 평균</th>
              <th class="text-right py-2 px-3 text-xs text-text-muted uppercase">비율</th>
              <th class="py-2 px-3 text-xs text-text-muted uppercase w-32"></th>
            </tr>
          </thead>
          <tbody>
            {#each tagStats as tag}
              <tr class="border-b border-border/50 hover:bg-bg-hover/50">
                <td class="py-3 px-3">
                  <div class="flex items-center gap-2">
                    <div class="w-3 h-3 rounded-full" style="background-color: {tag.color}"></div>
                    <span class="text-text-primary">{tag.name}</span>
                  </div>
                </td>
                <td class="py-3 px-3 text-right text-text-primary font-medium">
                  {formatDuration(tag.duration)}
                </td>
                <td class="py-3 px-3 text-right text-text-secondary">
                  {formatDuration(Math.round(tag.duration / daysCount))}
                </td>
                <td class="py-3 px-3 text-right text-text-muted">
                  {tag.percentage}%
                </td>
                <td class="py-3 px-3">
                  <div class="h-2 bg-bg-tertiary rounded-full overflow-hidden">
                    <div
                      class="h-full rounded-full"
                      style="width: {tag.percentage}%; background-color: {tag.color}"
                    ></div>
                  </div>
                </td>
              </tr>
            {:else}
              <tr>
                <td colspan="5" class="text-center py-8 text-text-muted">데이터 없음</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Weekday vs Weekend -->
    <div class="bg-bg-card rounded-xl p-5 border border-border">
      <h2 class="text-lg font-semibold text-text-primary mb-4">주중 vs 주말</h2>
      <div class="h-48">
        <canvas id="comparisonChart"></canvas>
      </div>
    </div>
  </div>

  <!-- TOP 10: Process & Website -->
  <div class="grid grid-cols-2 gap-6">
    <!-- Process TOP 10 -->
    <div class="bg-bg-card rounded-xl p-5 border border-border">
      <h2 class="text-lg font-semibold text-text-primary mb-4">프로세스 TOP 10</h2>
      <div class="grid gap-3" style="grid-template-columns: auto auto 1fr auto;">
        {#each processStats as proc, i}
          {@const maxDuration = processStats[0]?.duration || 1}
          <span class="w-5 text-xs text-text-muted text-right">{i + 1}</span>
          <span class="text-sm text-text-secondary">{proc.name}</span>
          <div class="h-5 bg-bg-tertiary rounded overflow-hidden">
            <div
              class="h-full bg-accent rounded transition-all duration-500"
              style="width: {(proc.duration / maxDuration) * 100}%"
            ></div>
          </div>
          <span class="text-sm text-text-primary text-right">{formatDuration(proc.duration)}</span>
        {:else}
          <div class="col-span-4 text-text-muted text-center py-4">데이터 없음</div>
        {/each}
      </div>
    </div>

    <!-- Website TOP 10 -->
    <div class="bg-bg-card rounded-xl p-5 border border-border">
      <h2 class="text-lg font-semibold text-text-primary mb-4">웹사이트 TOP 10</h2>
      {#if websiteStats.length > 0}
        <div class="grid gap-3" style="grid-template-columns: auto auto 1fr auto;">
          {#each websiteStats as site, i}
            {@const maxDuration = websiteStats[0]?.duration || 1}
            <span class="w-5 text-xs text-text-muted text-right">{i + 1}</span>
            <span class="text-sm text-text-secondary">{site.domain}</span>
            <div class="h-5 bg-bg-tertiary rounded overflow-hidden">
              <div
                class="h-full bg-blue-500 rounded transition-all duration-500"
                style="width: {(site.duration / maxDuration) * 100}%"
              ></div>
            </div>
            <span class="text-sm text-text-primary text-right">{formatDuration(site.duration)}</span>
          {/each}
        </div>
      {:else}
        <div class="text-text-muted text-center py-4 flex flex-col items-center gap-2">
          <svg class="w-8 h-8 text-text-muted/50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
          </svg>
          <span>웹사이트 통계 없음</span>
          <span class="text-xs">(Chrome 확장 필요)</span>
        </div>
      {/if}
    </div>
  </div>
</div>

<!-- Help Modal -->
<HelpModal show={showHelp} title="분석 도움말" on:close={() => showHelp = false}>
  <div class="space-y-4">
    <div>
      <h4 class="font-semibold text-text-primary mb-2">분석 탭이란?</h4>
      <p class="text-text-secondary">
        선택한 기간의 활동 데이터를 분석하고 목표 달성 여부를 판단합니다.
        일별 트렌드, 태그별 통계, 프로세스/웹사이트별 사용 시간을 확인할 수 있습니다.
      </p>
    </div>

    <div>
      <h4 class="font-semibold text-text-primary mb-2">목표 달성 기준</h4>
      <ul class="list-disc list-inside space-y-1 text-text-secondary">
        <li><strong class="text-green-400">달성</strong> - 활동시간 ≥ 목표시간 AND 비업무 비율 &lt; 상한</li>
        <li><strong class="text-red-400">미달</strong> - 조건 중 하나라도 만족하지 못함</li>
        <li>목표값은 설정 탭에서 변경 가능</li>
      </ul>
    </div>

    <div>
      <h4 class="font-semibold text-text-primary mb-2">차트 설명</h4>
      <ul class="list-disc list-inside space-y-1 text-text-secondary">
        <li><strong class="text-text-primary">일별 트렌드</strong> - 업무/비업무 시간 추이 (막대: 업무, 선: 비업무)</li>
        <li><strong class="text-text-primary">태그 비교</strong> - 업무 vs 비업무 태그 비율</li>
      </ul>
    </div>

    <div class="pt-2 border-t border-border">
      <p class="text-text-muted text-xs">
        팁: 빠른 기간 선택 버튼으로 7일/30일/이번 달/지난 달을 빠르게 조회할 수 있습니다.
      </p>
    </div>
  </div>
</HelpModal>
