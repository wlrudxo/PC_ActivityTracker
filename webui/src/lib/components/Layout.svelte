<script>
  import { onMount, onDestroy } from 'svelte';
  import { link, location } from 'svelte-spa-router';
  import { connectWebSocket, disconnectWebSocket, wsConnected } from '../stores/websocket.js';
  import { theme } from '../stores/theme.js';
  import Toast from './Toast.svelte';

  onMount(() => {
    theme.init();
    connectWebSocket();
  });

  onDestroy(() => {
    disconnectWebSocket();
  });

  const navItems = [
    { path: '/', label: '대시보드', icon: 'chart-pie' },
    { path: '/timeline', label: '타임라인', icon: 'clock' },
    { path: '/analysis', label: '분석', icon: 'chart-bar' },
    { path: '/tags', label: '태그 관리', icon: 'tag' },
    { path: '/notification', label: '알림', icon: 'bell' },
    { path: '/focus', label: '집중', icon: 'shield-check' },
    { path: '/settings', label: '설정', icon: 'cog' }
  ];

  function isActive(path) {
    if (path === '/') {
      return $location === '/';
    }
    return $location.startsWith(path);
  }
</script>

<div class="flex h-screen bg-bg-primary">
  <!-- Sidebar -->
  <nav class="w-36 bg-bg-secondary border-r border-border flex flex-col">
    <!-- Logo -->
    <div class="h-[70px] flex flex-col items-center justify-center border-b border-border leading-tight">
      <span class="text-xs text-text-muted tracking-wider">ACTIVITY</span>
      <span class="text-xl font-bold text-text-primary">Tracker</span>
    </div>

    <!-- Navigation Items -->
    <div class="flex-1 py-4 px-2 space-y-1">
      {#each navItems as item}
        <a
          href={item.path}
          use:link
          class="flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-150
            {isActive(item.path)
              ? 'bg-accent/15 text-accent'
              : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'}"
        >
          <span class="w-5 h-5">
            {#if item.icon === 'chart-pie'}
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z" />
              </svg>
            {:else if item.icon === 'chart-bar'}
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            {:else if item.icon === 'clock'}
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            {:else if item.icon === 'tag'}
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
              </svg>
            {:else if item.icon === 'bell'}
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
            {:else if item.icon === 'shield-check'}
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            {:else if item.icon === 'cog'}
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            {/if}
          </span>
          <span class="text-sm font-medium">{item.label}</span>
        </a>
      {/each}
    </div>

    <!-- Footer -->
    <div class="p-4 border-t border-border">
      <div class="flex items-center gap-2 text-xs text-text-muted">
        {#if $wsConnected}
          <div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
          <span>실시간 연결됨</span>
        {:else}
          <div class="w-2 h-2 rounded-full bg-yellow-500"></div>
          <span>연결 중...</span>
        {/if}
      </div>
    </div>
  </nav>

  <!-- Main Content -->
  <main class="flex-1 overflow-auto">
    <slot />
  </main>
</div>

<Toast />
