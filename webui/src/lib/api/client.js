/**
 * API 기본 URL 결정
 * - file:// 프로토콜: PyWebView에서 로드, 절대 경로 사용
 * - http(s)://: 개발 서버나 프록시 사용, 상대 경로 사용
 */
export function getApiBaseUrl() {
  if (typeof window === 'undefined') return '/api';
  if (window.location.protocol === 'file:') {
    return 'http://127.0.0.1:8000';
  }
  return '';
}

function getApiBase() {
  if (window.location.protocol === 'file:') {
    return 'http://127.0.0.1:8000/api';
  }
  return '/api';
}

const API_BASE = getApiBase();

/**
 * Fetch wrapper with error handling
 */
async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    },
    ...options
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({ detail: response.statusText }));
    const error = new Error(errorBody.detail || 'API request failed');
    error.status = response.status;
    throw error;
  }

  return response.json();
}

/**
 * FormData request for file uploads
 */
async function uploadRequest(endpoint, formData) {
  const url = `${API_BASE}${endpoint}`;

  const response = await fetch(url, {
    method: 'POST',
    body: formData
    // Note: Don't set Content-Type header, browser will set it with boundary
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Upload failed');
  }

  return response.json();
}

export const api = {
  // Dashboard
  getDashboardDaily: (date) => request(`/dashboard/daily?date=${date}`),
  getDashboardPeriod: (start, end) => request(`/dashboard/period?start=${start}&end=${end}`),
  getDashboardHourly: (date) => request(`/dashboard/hourly?date=${date}`),

  // Timeline
  getTimeline: (date, tagId = null) => {
    let url = `/timeline?date=${date}`;
    if (tagId) url += `&tag_id=${tagId}`;
    return request(url);
  },

  // Tags
  getTags: () => request('/tags'),
  createTag: (data) => request('/tags', { method: 'POST', body: JSON.stringify(data) }),
  updateTag: (id, data) => request(`/tags/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteTag: (id) => request(`/tags/${id}`, { method: 'DELETE' }),

  // Rules
  getRules: () => request('/rules'),
  createRule: (data) => request('/rules', { method: 'POST', body: JSON.stringify(data) }),
  updateRule: (id, data) => request(`/rules/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteRule: (id) => request(`/rules/${id}`, { method: 'DELETE' }),

  // Reclassify
  reclassifyUntagged: () => request('/reclassify/untagged', { method: 'POST' }),
  reclassifyAll: () => request('/reclassify/all', { method: 'POST' }),
  getUnclassifiedActivities: () => request('/activities/unclassified'),
  deleteActivities: (ids) => request('/activities/delete', { method: 'POST', body: JSON.stringify({ ids }) }),

  // Settings
  getSettings: () => request('/settings'),
  updateSettings: (data) => request('/settings', { method: 'PUT', body: JSON.stringify(data) }),
  openAppData: () => request('/open/appdata', { method: 'POST' }),

  // Alerts - Settings
  getAlertSettings: () => request('/alerts/settings'),
  updateAlertSettings: (data) => request('/alerts/settings', { method: 'PUT', body: JSON.stringify(data) }),

  // Alerts - Sounds
  getAlertSounds: () => request('/alerts/sounds'),
  uploadAlertSound: (file, name) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('name', name);
    return uploadRequest('/alerts/sounds/upload', formData);
  },
  deleteAlertSound: (id) => request(`/alerts/sounds/${id}`, { method: 'DELETE' }),

  // Alerts - Images
  getAlertImages: () => request('/alerts/images'),
  uploadAlertImage: (file, name) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('name', name);
    return uploadRequest('/alerts/images/upload', formData);
  },
  deleteAlertImage: (id) => request(`/alerts/images/${id}`, { method: 'DELETE' }),

  // Alerts - Tag Settings
  getTagAlertSettings: () => request('/alerts/tags'),
  updateTagAlertSettings: (tagId, data) => request(`/alerts/tags/${tagId}`, { method: 'PUT', body: JSON.stringify(data) }),

  // Focus
  getFocusSettings: () => request('/focus'),
  getFocusStatus: () => request('/focus/status'),
  updateFocusSettings: (tagId, data) => request(`/focus/${tagId}`, { method: 'PUT', body: JSON.stringify(data) }),
  emergencyResetFocus: (reason) => request('/focus/emergency-reset', { method: 'POST', body: JSON.stringify({ reason }) }),

  // System
  exitApp: () => request('/system/exit', { method: 'POST' }),

  // Auto Start
  getAutoStart: () => request('/settings/autostart'),
  setAutoStart: (enabled) => request('/settings/autostart', { method: 'PUT', body: JSON.stringify({ enabled }) }),

  // Data Management - DB Backup/Restore
  backupDatabase: (includeMedia = true) => {
    // 파일 다운로드를 위해 직접 fetch 사용
    const url = `${API_BASE}/data/db/backup?include_media=${includeMedia ? 'true' : 'false'}`;
    return fetch(url).then(res => {
      if (!res.ok) throw new Error('Backup failed');
      return res.blob();
    }).then(blob => {
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const filename = includeMedia
        ? `activity_tracker_backup_${timestamp}.zip`
        : `activity_tracker_backup_${timestamp}.db`;
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      window.URL.revokeObjectURL(url);
      return { success: true };
    });
  },
  restoreDatabase: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return uploadRequest('/data/db/restore', formData);
  },

  // Data Management - Rules Export/Import
  exportRules: () => request('/data/rules/export'),
  importRules: (file, mergeMode = true) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('merge_mode', mergeMode.toString());
    return uploadRequest('/data/rules/import', formData);
  }
};
