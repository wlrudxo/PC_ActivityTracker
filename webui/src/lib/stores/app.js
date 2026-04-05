import { writable, derived } from 'svelte/store';

// Helper to format date as YYYY-MM-DD in local timezone (not UTC)
export function formatLocalDate(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function shiftLocalDate(dateString, deltaDays) {
  const current = new Date(dateString);
  current.setDate(current.getDate() + deltaDays);
  return formatLocalDate(current);
}

// Selected date for dashboard/timeline
export const selectedDate = writable(formatLocalDate());

let autoDateTimer = null;
let autoDateWatcherStarted = false;
let trackedToday = formatLocalDate();

function clearAutoDateTimer() {
  if (autoDateTimer) {
    clearTimeout(autoDateTimer);
    autoDateTimer = null;
  }
}

function scheduleNextDateBoundaryCheck() {
  clearAutoDateTimer();

  const now = new Date();
  const nextMidnight = new Date(now);
  nextMidnight.setHours(24, 0, 1, 0);
  const delay = Math.max(nextMidnight.getTime() - now.getTime(), 1000);

  autoDateTimer = setTimeout(() => {
    syncSelectedDateWithToday();
    scheduleNextDateBoundaryCheck();
  }, delay);
}

export function syncSelectedDateWithToday() {
  const today = formatLocalDate();
  if (today === trackedToday) return;

  const previousToday = trackedToday;
  trackedToday = today;

  selectedDate.update((current) => current === previousToday ? today : current);
}

export function startSelectedDateAutoSync() {
  if (autoDateWatcherStarted || typeof window === 'undefined') {
    return () => {};
  }

  autoDateWatcherStarted = true;
  trackedToday = formatLocalDate();

  const handleVisibilityOrFocus = () => {
    syncSelectedDateWithToday();
    scheduleNextDateBoundaryCheck();
  };

  scheduleNextDateBoundaryCheck();
  document.addEventListener('visibilitychange', handleVisibilityOrFocus);
  window.addEventListener('focus', handleVisibilityOrFocus);

  return () => {
    clearAutoDateTimer();
    document.removeEventListener('visibilitychange', handleVisibilityOrFocus);
    window.removeEventListener('focus', handleVisibilityOrFocus);
    autoDateWatcherStarted = false;
  };
}

// Derived: formatted current time
export const formattedDate = derived(selectedDate, ($date) => {
  const d = new Date($date);
  return d.toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'short'
  });
});

// Helper to format duration (hours and minutes only)
export function formatDuration(seconds) {
  if (!seconds || seconds < 0) return '0초';

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hours > 0) {
    return minutes > 0 ? `${hours}시간 ${minutes}분` : `${hours}시간`;
  }
  if (minutes > 0) {
    return secs > 0 ? `${minutes}분 ${secs}초` : `${minutes}분`;
  }
  return `${secs}초`;
}

// Helper to format time (24h with seconds)
export function formatTime(timestamp) {
  if (!timestamp) return '';
  const d = new Date(timestamp);
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}
