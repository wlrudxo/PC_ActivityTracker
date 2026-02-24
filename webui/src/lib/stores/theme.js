/**
 * Theme store - 서버 DB 기반 다크/라이트 테마 관리
 */
import { writable } from 'svelte/store';
import { getApiBaseUrl } from '../api/client.js';

function createThemeStore() {
  const { subscribe, set, update } = writable('dark');

  /**
   * 서버에서 테마 로드
   */
  async function loadFromServer() {
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/settings/theme`);
      if (res.ok) {
        const data = await res.json();
        return data.theme || 'dark';
      }
    } catch (e) {
      console.warn('[Theme] Failed to load from server:', e);
    }
    return 'dark';
  }

  /**
   * 서버에 테마 저장
   */
  async function saveToServer(theme) {
    try {
      await fetch(`${getApiBaseUrl()}/api/settings/theme`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme })
      });
    } catch (e) {
      console.warn('[Theme] Failed to save to server:', e);
    }
  }

  return {
    subscribe,

    /**
     * 테마 설정
     * @param {'light' | 'dark'} newTheme
     */
    set: (newTheme) => {
      applyTheme(newTheme);
      set(newTheme);
      saveToServer(newTheme);
    },

    /**
     * 테마 토글
     */
    toggle: () => {
      update(current => {
        const newTheme = current === 'dark' ? 'light' : 'dark';
        applyTheme(newTheme);
        saveToServer(newTheme);
        return newTheme;
      });
    },

    /**
     * 초기화 (앱 시작 시 호출)
     */
    init: async () => {
      if (typeof window === 'undefined') return;
      // 먼저 dark 적용 (깜빡임 방지)
      applyTheme('dark');
      // 서버에서 실제 테마 로드
      const savedTheme = await loadFromServer();
      applyTheme(savedTheme);
      set(savedTheme);
    }
  };
}

/**
 * HTML에 테마 클래스 적용
 */
function applyTheme(theme) {
  if (typeof document === 'undefined') return;

  if (theme === 'dark') {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
}

export const theme = createThemeStore();
