<script>
  import { onMount } from 'svelte';
  import Router from 'svelte-spa-router';
  import Layout from './lib/components/Layout.svelte';
  import { startSelectedDateAutoSync } from './lib/stores/app.js';

  import Dashboard from './pages/Dashboard.svelte';
  import Timeline from './pages/Timeline.svelte';
  import Analysis from './pages/Analysis.svelte';
  import TagManagement from './pages/TagManagement.svelte';
  import Notification from './pages/Notification.svelte';
  import Focus from './pages/Focus.svelte';
  import Settings from './pages/Settings.svelte';

  const routes = {
    '/': Dashboard,
    '/timeline': Timeline,
    '/analysis': Analysis,
    '/tags': TagManagement,
    '/notification': Notification,
    '/focus': Focus,
    '/settings': Settings
  };

  onMount(() => startSelectedDateAutoSync());
</script>

<Layout>
  <Router {routes} />
</Layout>
