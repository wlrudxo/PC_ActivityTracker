<script>
  import { createEventDispatcher } from 'svelte';
  import { fly } from 'svelte/transition';

  export let show = false;
  export let title = '확인';
  export let confirmText = '확인';
  export let cancelText = '취소';
  export let type = 'warning'; // warning, danger, info
  export let mode = 'confirm'; // confirm, alert, prompt
  export let placeholder = ''; // prompt mode placeholder
  export let initialValue = ''; // prompt mode initial value

  let inputValue = '';

  const dispatch = createEventDispatcher();

  // Reset input value when modal opens
  $: if (show && mode === 'prompt') {
    inputValue = initialValue;
  }

  const typeConfig = {
    warning: {
      iconBg: 'bg-yellow-500/20',
      iconColor: 'text-yellow-400',
      btnBg: 'bg-yellow-500 hover:bg-yellow-400',
      btnText: 'text-black',
      icon: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />`
    },
    danger: {
      iconBg: 'bg-red-500/20',
      iconColor: 'text-red-400',
      btnBg: 'bg-red-500 hover:bg-red-400',
      btnText: 'text-white',
      icon: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />`
    },
    info: {
      iconBg: 'bg-blue-500/20',
      iconColor: 'text-blue-400',
      btnBg: 'bg-blue-500 hover:bg-blue-400',
      btnText: 'text-white',
      icon: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />`
    }
  };

  $: config = typeConfig[type] || typeConfig.warning;

  function handleConfirm() {
    if (mode === 'prompt') {
      dispatch('confirm', { value: inputValue });
    } else {
      dispatch('confirm');
    }
  }

  function handleCancel() {
    if (mode === 'prompt') {
      dispatch('cancel', { value: null });
    } else {
      dispatch('cancel');
    }
  }

  function handleKeydown(e) {
    if (e.key === 'Enter' && mode === 'prompt') {
      handleConfirm();
    }
  }
</script>

{#if show}
  <div
    class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
    transition:fly={{ duration: 150 }}
  >
    <div class="bg-bg-card rounded-xl p-6 w-[450px] border border-border">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-full {config.iconBg} flex items-center justify-center">
          <svg class="w-6 h-6 {config.iconColor}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {@html config.icon}
          </svg>
        </div>
        <h3 class="text-lg font-semibold text-text-primary">{title}</h3>
      </div>

      <div class="text-sm text-text-secondary space-y-3 mb-4">
        <slot />
      </div>

      {#if mode === 'prompt'}
        <input
          type="text"
          bind:value={inputValue}
          on:keydown={handleKeydown}
          placeholder={placeholder}
          class="w-full px-3 py-2 mb-4 bg-bg-tertiary border border-border rounded-lg text-text-primary focus:border-accent focus:ring-1 focus:ring-accent outline-none"
        />
      {/if}

      <div class="flex gap-3 justify-end">
        {#if mode !== 'alert'}
          <button
            on:click={handleCancel}
            class="px-4 py-2 rounded-lg bg-bg-tertiary border border-border text-text-secondary hover:bg-bg-hover transition-colors"
          >
            {cancelText}
          </button>
        {/if}
        <button
          on:click={handleConfirm}
          class="px-4 py-2 rounded-lg {config.btnBg} {config.btnText} font-medium transition-colors"
        >
          {confirmText}
        </button>
      </div>
    </div>
  </div>
{/if}
