import { writable } from 'svelte/store';

function createToastStore() {
  const { subscribe, update } = writable([]);

  let id = 0;

  function show(message, type = 'info', duration = 3000) {
    const toastId = ++id;

    update(toasts => [...toasts, { id: toastId, message, type }]);

    if (duration > 0) {
      setTimeout(() => {
        dismiss(toastId);
      }, duration);
    }

    return toastId;
  }

  function dismiss(toastId) {
    update(toasts => toasts.filter(t => t.id !== toastId));
  }

  return {
    subscribe,
    show,
    success: (msg, duration) => show(msg, 'success', duration),
    error: (msg, duration) => show(msg, 'error', duration ?? 5000),
    info: (msg, duration) => show(msg, 'info', duration),
    warning: (msg, duration) => show(msg, 'warning', duration),
    dismiss
  };
}

export const toast = createToastStore();
