<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api/client.js';
  import { toast } from '../lib/stores/toast.js';
  import ConfirmModal from '../lib/components/ConfirmModal.svelte';
  import HelpModal from '../lib/components/HelpModal.svelte';
  import HelpButton from '../lib/components/HelpButton.svelte';
  import { getContrastingTextColor } from '../lib/utils/color.js';

  let loading = true;
  let showHelp = false;
  let error = null;
  let tags = [];
  let rules = [];

  // Modal states
  let showTagModal = false;
  let showRuleModal = false;
  let showDeleteModal = false;
  let editingTag = null;
  let editingRule = null;

  // Confirm modal states
  let showDeleteTagModal = false;
  let showDeleteRuleModal = false;
  let showReclassifyUntaggedModal = false;
  let showReclassifyAllModal = false;
  let showDeleteActivitiesModal = false;
  let pendingDeleteTag = null;
  let pendingDeleteRule = null;
  let pendingDeleteCount = 0;

  // Reclassify states
  let reclassifying = false;
  let unclassifiedGroups = [];
  let selectedGroups = new Set();

  // Form data
  let tagForm = { name: '', color: '#4CAF50', category: 'other' };

  // 색상 프리셋 (다크 테마에서 잘 보이는 색상들)
  const colorPresets = [
    '#EF5350', '#EC407A', '#AB47BC', '#7E57C2', // 빨강, 분홍, 보라, 진보라
    '#5C6BC0', '#42A5F5', '#29B6F6', '#26C6DA', // 남색, 파랑, 하늘, 청록
    '#26A69A', '#66BB6A', '#9CCC65', '#D4E157', // 틸, 초록, 연두, 라임
    '#FFEE58', '#FFA726', '#FF7043', '#78909C'  // 노랑, 주황, 딥오렌지, 회색
  ];

  // 카테고리 옵션
  const categoryOptions = [
    { value: 'work', label: '업무', color: 'text-green-400' },
    { value: 'non_work', label: '비업무', color: 'text-red-400' },
    { value: 'other', label: '기타', color: 'text-text-muted' }
  ];
  let ruleForm = {
    name: '',
    tag_id: null,
    priority: 50,
    enabled: true,
    process_pattern: '',
    url_pattern: '',
    window_title_pattern: '',
    chrome_profile: '',
    process_path_pattern: ''
  };

  function createEmptyTagForm() {
    return { name: '', color: '#4CAF50', category: 'other' };
  }

  function createRulePayload(form) {
    return {
      ...form,
      process_pattern: form.process_pattern || null,
      url_pattern: form.url_pattern || null,
      window_title_pattern: form.window_title_pattern || null,
      chrome_profile: form.chrome_profile || null,
      process_path_pattern: form.process_path_pattern || null
    };
  }

  function createEmptyRuleForm() {
    return {
      name: '',
      tag_id: tags[0]?.id || null,
      priority: 50,
      enabled: true,
      process_pattern: '',
      url_pattern: '',
      window_title_pattern: '',
      chrome_profile: '',
      process_path_pattern: ''
    };
  }

  function closeTagModal() {
    showTagModal = false;
    editingTag = null;
  }

  function closeRuleModal() {
    showRuleModal = false;
    editingRule = null;
  }

  function closeDeleteModal() {
    showDeleteModal = false;
    unclassifiedGroups = [];
    selectedGroups = new Set();
  }

  function resetDeleteTagState() {
    showDeleteTagModal = false;
    pendingDeleteTag = null;
  }

  function resetDeleteRuleState() {
    showDeleteRuleModal = false;
    pendingDeleteRule = null;
  }

  function getSelectedActivityIds() {
    const idsToDelete = [];
    for (const idx of selectedGroups) {
      idsToDelete.push(...unclassifiedGroups[idx].ids);
    }
    return idsToDelete;
  }

  function handleModalBackdropKeydown(event, close) {
    if (event.key === 'Escape') {
      close();
    }
  }

  function toggleSelectionFromRow(event, index) {
    if (event.target instanceof HTMLInputElement) {
      return;
    }
    toggleGroupSelection(index);
  }

  function handleSelectableRowKeydown(event, index) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleGroupSelection(index);
    }
  }

  async function loadData() {
    loading = true;
    error = null;

    try {
      const [tagsRes, rulesRes] = await Promise.all([
        api.getTags(),
        api.getRules()
      ]);

      tags = tagsRes.tags || [];
      rules = (rulesRes.rules || []).map(rule => ({
        ...rule,
        tag: tags.find(t => t.id === rule.tag_id) || { name: '미분류', color: '#607D8B' }
      }));

    } catch (err) {
      console.error('Failed to load data:', err);
      error = err.message;
    } finally {
      loading = false;
    }
  }

  // Tag CRUD
  function openTagModal(tag = null) {
    editingTag = tag;
    tagForm = tag
      ? { name: tag.name, color: tag.color, category: tag.category || 'other' }
      : createEmptyTagForm();
    showTagModal = true;
  }

  async function saveTag() {
    try {
      if (editingTag) {
        await api.updateTag(editingTag.id, tagForm);
      } else {
        await api.createTag(tagForm);
      }
      closeTagModal();
      await loadData();
      toast.success('태그가 저장되었습니다.');
    } catch (err) {
      toast.error('저장 실패: ' + err.message);
    }
  }

  function deleteTag(tag) {
    pendingDeleteTag = tag;
    showDeleteTagModal = true;
  }

  async function confirmDeleteTag() {
    if (!pendingDeleteTag) return;

    try {
      await api.deleteTag(pendingDeleteTag.id);
      await loadData();
      toast.success('태그가 삭제되었습니다.');
    } catch (err) {
      toast.error('삭제 실패: ' + err.message);
    }
    resetDeleteTagState();
  }

  function cancelDeleteTag() {
    resetDeleteTagState();
  }

  // Rule CRUD
  function openRuleModal(rule = null) {
    editingRule = rule;
    ruleForm = rule
      ? {
          name: rule.name,
          tag_id: rule.tag_id,
          priority: rule.priority,
          enabled: rule.enabled,
          process_pattern: rule.process_pattern || '',
          url_pattern: rule.url_pattern || '',
          window_title_pattern: rule.window_title_pattern || '',
          chrome_profile: rule.chrome_profile || '',
          process_path_pattern: rule.process_path_pattern || ''
        }
      : createEmptyRuleForm();
    showRuleModal = true;
  }

  async function saveRule() {
    try {
      const data = createRulePayload(ruleForm);

      if (editingRule) {
        await api.updateRule(editingRule.id, data);
      } else {
        await api.createRule(data);
      }
      closeRuleModal();
      await loadData();
      toast.success('규칙이 저장되었습니다.');
    } catch (err) {
      toast.error('저장 실패: ' + err.message);
    }
  }

  function deleteRule(rule) {
    pendingDeleteRule = rule;
    showDeleteRuleModal = true;
  }

  async function confirmDeleteRule() {
    if (!pendingDeleteRule) return;

    try {
      await api.deleteRule(pendingDeleteRule.id);
      await loadData();
      toast.success('규칙이 삭제되었습니다.');
    } catch (err) {
      toast.error('삭제 실패: ' + err.message);
    }
    resetDeleteRuleState();
  }

  function cancelDeleteRule() {
    resetDeleteRuleState();
  }

  async function toggleRule(rule) {
    try {
      await api.updateRule(rule.id, { enabled: !rule.enabled });
      await loadData();
    } catch (err) {
      toast.error('변경 실패: ' + err.message);
    }
  }

  // === Reclassify Functions ===
  function reclassifyUntagged() {
    showReclassifyUntaggedModal = true;
  }

  async function confirmReclassifyUntagged() {
    showReclassifyUntaggedModal = false;
    reclassifying = true;
    try {
      const result = await api.reclassifyUntagged();
      toast.success(`재분류 완료! 재분류됨: ${result.reclassified}개, 여전히 미분류: ${result.remaining}개`);
    } catch (err) {
      toast.error('재분류 실패: ' + err.message);
    } finally {
      reclassifying = false;
    }
  }

  function reclassifyAll() {
    showReclassifyAllModal = true;
  }

  async function confirmReclassifyAll() {
    showReclassifyAllModal = false;
    reclassifying = true;
    try {
      const result = await api.reclassifyAll();
      toast.success(`모든 활동 재분류 완료! 총 재분류: ${result.reclassified}개`);
    } catch (err) {
      toast.error('재분류 실패: ' + err.message);
    } finally {
      reclassifying = false;
    }
  }

  async function openDeleteModal() {
    try {
      const result = await api.getUnclassifiedActivities();
      unclassifiedGroups = result.groups || [];
      selectedGroups = new Set();

      if (unclassifiedGroups.length === 0) {
        toast.info('삭제할 미분류 항목이 없습니다.');
        return;
      }

      showDeleteModal = true;
    } catch (err) {
      toast.error('미분류 목록 로드 실패: ' + err.message);
    }
  }

  function toggleGroupSelection(index) {
    if (selectedGroups.has(index)) {
      selectedGroups.delete(index);
    } else {
      selectedGroups.add(index);
    }
    selectedGroups = selectedGroups; // trigger reactivity
  }

  function selectAllGroups() {
    selectedGroups = new Set(unclassifiedGroups.map((_, i) => i));
  }

  function deselectAllGroups() {
    selectedGroups = new Set();
  }

  function deleteSelectedActivities() {
    const idsToDelete = getSelectedActivityIds();
    if (idsToDelete.length === 0) {
      toast.warning('삭제할 항목을 선택하세요.');
      return;
    }

    pendingDeleteCount = idsToDelete.length;
    showDeleteActivitiesModal = true;
  }

  async function confirmDeleteActivities() {
    showDeleteActivitiesModal = false;
    const idsToDelete = getSelectedActivityIds();

    try {
      await api.deleteActivities(idsToDelete);
      toast.success(`${idsToDelete.length}개의 활동 기록이 삭제되었습니다.`);
      closeDeleteModal();
    } catch (err) {
      toast.error('삭제 실패: ' + err.message);
    }
  }

  onMount(loadData);
</script>

<div class="p-6 space-y-6">
  <div class="flex items-center justify-between">
    <div>
      <div class="flex items-center gap-2">
        <h1 class="text-2xl font-bold text-text-primary">태그 관리</h1>
        <HelpButton on:click={() => showHelp = true} />
      </div>
      <p class="text-sm text-text-secondary mt-1">태그와 분류 규칙을 관리합니다</p>
    </div>
    <div class="flex items-center gap-2">
      <button
        class="px-3 py-2 bg-bg-secondary hover:bg-bg-hover border border-border text-text-primary text-sm rounded-lg transition-colors disabled:opacity-50"
        on:click={reclassifyUntagged}
        disabled={reclassifying}
      >
        {reclassifying ? '처리중...' : '미분류 재분류'}
      </button>
      <button
        class="px-3 py-2 bg-bg-secondary hover:bg-bg-hover border border-border text-text-primary text-sm rounded-lg transition-colors disabled:opacity-50"
        on:click={openDeleteModal}
        disabled={reclassifying}
      >
        미분류 삭제
      </button>
      <button
        class="px-3 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/50 text-red-400 text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
        on:click={reclassifyAll}
        disabled={reclassifying}
      >
        ⚠ 전체 재분류
      </button>
    </div>
  </div>

  <!-- Error Banner -->
  {#if error}
    <div class="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm text-red-400">
      데이터 로드 실패: {error}
    </div>
  {/if}

  <!-- Tags Section -->
  <div class="bg-bg-card rounded-xl border border-border">
    <div class="px-5 py-4 border-b border-border flex items-center justify-between">
      <h2 class="text-lg font-semibold text-text-primary">태그 목록</h2>
      <button
        class="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm font-medium rounded-lg transition-colors"
        on:click={() => openTagModal()}
      >
        + 태그 추가
      </button>
    </div>

    {#if loading}
      <div class="p-8 text-center text-text-muted">로딩 중...</div>
    {:else}
      <div class="grid grid-cols-4 gap-4 p-5">
        {#each tags as tag}
          {@const catOption = categoryOptions.find(c => c.value === tag.category) || categoryOptions[2]}
          <div class="bg-bg-secondary rounded-lg p-4 border border-border hover:border-border-light transition-colors">
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-3">
                <div class="w-4 h-4 rounded-full" style="background-color: {tag.color}"></div>
                <span class="font-medium text-text-primary">{tag.name}</span>
              </div>
              <div class="flex items-center gap-1">
                {#if tag.name !== '미분류' && tag.name !== '자리비움'}
                  <button
                    aria-label="수정"
                    class="p-1.5 rounded hover:bg-bg-hover transition-colors"
                    on:click={() => openTagModal(tag)}
                  >
                    <svg class="w-4 h-4 text-text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                    </svg>
                  </button>
                  <button
                    aria-label="삭제"
                    class="p-1.5 rounded hover:bg-bg-hover transition-colors"
                    on:click={() => deleteTag(tag)}
                  >
                    <svg class="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                {/if}
              </div>
            </div>
            <div class="flex items-center justify-between">
              <span class="text-xs px-2 py-0.5 rounded-full {catOption.color} bg-bg-tertiary">{catOption.label}</span>
              <span class="text-sm text-text-muted">{tag.rule_count || 0}개 규칙</span>
            </div>
          </div>
        {:else}
          <div class="col-span-4 text-center text-text-muted py-8">태그가 없습니다</div>
        {/each}
      </div>
    {/if}
  </div>

  <!-- Rules Section -->
  <div class="bg-bg-card rounded-xl border border-border">
    <div class="px-5 py-4 border-b border-border flex items-center justify-between">
      <h2 class="text-lg font-semibold text-text-primary">분류 규칙</h2>
      <button
        class="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm font-medium rounded-lg transition-colors"
        on:click={() => openRuleModal()}
      >
        + 규칙 추가
      </button>
    </div>

    {#if loading}
      <div class="p-8 text-center text-text-muted">로딩 중...</div>
    {:else if rules.length === 0}
      <div class="p-8 text-center text-text-muted">규칙이 없습니다</div>
    {:else}
      <table class="w-full table-fixed">
        <thead class="bg-bg-secondary">
          <tr>
            <th class="w-16 px-3 py-3 text-left text-xs font-medium text-text-muted uppercase">상태</th>
            <th class="w-16 px-3 py-3 text-left text-xs font-medium text-text-muted uppercase">우선</th>
            <th class="w-28 px-3 py-3 text-left text-xs font-medium text-text-muted uppercase">이름</th>
            <th class="w-20 px-3 py-3 text-left text-xs font-medium text-text-muted uppercase">태그</th>
            <th class="px-3 py-3 text-left text-xs font-medium text-text-muted uppercase">프로세스</th>
            <th class="px-3 py-3 text-left text-xs font-medium text-text-muted uppercase">URL 패턴</th>
            <th class="w-20 px-3 py-3 text-left text-xs font-medium text-text-muted uppercase">작업</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          {#each rules as rule}
            <tr class="hover:bg-bg-hover transition-colors">
              <td class="px-3 py-3">
                <label class="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={rule.enabled}
                    on:change={() => toggleRule(rule)}
                    class="sr-only peer"
                  >
                  <div class="w-9 h-5 bg-bg-tertiary rounded-full peer peer-checked:bg-accent transition-colors after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-4"></div>
                </label>
              </td>
              <td class="px-3 py-3 text-sm text-text-primary">{rule.priority}</td>
              <td class="px-3 py-3 text-sm text-text-primary font-medium truncate" title={rule.name}>{rule.name}</td>
              <td class="px-3 py-3">
                <span
                  class="inline-block px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap"
                  style="background-color: {rule.tag?.color || '#607D8B'}; color: {getContrastingTextColor(rule.tag?.color || '#607D8B')}"
                >
                  {rule.tag?.name || rule.tag_name || '미분류'}
                </span>
              </td>
              <td class="px-3 py-3 text-sm text-text-secondary font-mono truncate" title={rule.process_pattern || ''}>{rule.process_pattern || '-'}</td>
              <td class="px-3 py-3 text-sm text-text-secondary font-mono truncate" title={rule.url_pattern || ''}>{rule.url_pattern || '-'}</td>
              <td class="px-3 py-3">
                <div class="flex items-center gap-1">
                  <button
                    aria-label="수정"
                    class="p-1.5 rounded hover:bg-bg-secondary transition-colors"
                    on:click={() => openRuleModal(rule)}
                  >
                    <svg class="w-4 h-4 text-text-muted hover:text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                    </svg>
                  </button>
                  <button
                    aria-label="삭제"
                    class="p-1.5 rounded hover:bg-bg-secondary transition-colors"
                    on:click={() => deleteRule(rule)}
                  >
                    <svg class="w-4 h-4 text-red-400 hover:text-red-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>

<!-- Tag Modal -->
{#if showTagModal}
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
    on:click|self={closeTagModal}
    on:keydown={(event) => handleModalBackdropKeydown(event, closeTagModal)}
    role="dialog"
    tabindex="-1"
  >
    <div
      class="bg-bg-card rounded-xl p-6 w-96 border border-border"
      role="document"
    >
      <h3 class="text-lg font-semibold text-text-primary mb-4">
        {editingTag ? '태그 수정' : '태그 추가'}
      </h3>

      <div class="space-y-4">
        <div>
          <label for="tag-name" class="block text-sm text-text-secondary mb-1">이름</label>
          <input
            id="tag-name"
            type="text"
            bind:value={tagForm.name}
            class="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary focus:border-accent focus:ring-1 focus:ring-accent outline-none"
            placeholder="태그 이름"
          />
        </div>
        <div>
          <label for="tag-color-picker" class="block text-sm text-text-secondary mb-1">색상</label>
          <div class="grid grid-cols-8 gap-1.5 mb-3">
            {#each colorPresets as preset}
              <button
                type="button"
                class="w-8 h-8 rounded-lg border-2 transition-all hover:scale-110"
                style="background-color: {preset}; border-color: {tagForm.color === preset ? 'white' : 'transparent'}"
                on:click={() => tagForm.color = preset}
                title={preset}
              ></button>
            {/each}
          </div>
          <div class="flex items-center gap-3">
            <input
              id="tag-color-picker"
              type="color"
              bind:value={tagForm.color}
              class="w-12 h-10 rounded border border-border cursor-pointer"
            />
            <input
              aria-label="색상 코드"
              type="text"
              bind:value={tagForm.color}
              class="flex-1 px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary font-mono text-sm"
            />
          </div>
        </div>
        <div>
          <label for="tag-category" class="block text-sm text-text-secondary mb-1">카테고리</label>
          <select
            id="tag-category"
            bind:value={tagForm.category}
            class="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary focus:border-accent outline-none"
          >
            {#each categoryOptions as option}
              <option value={option.value}>{option.label}</option>
            {/each}
          </select>
          <p class="text-xs text-text-muted mt-1">분석 페이지에서 업무/비업무 비율 계산에 사용됩니다</p>
        </div>
      </div>

      <div class="flex justify-end gap-3 mt-6">
        <button
          class="px-4 py-2 text-text-secondary hover:text-text-primary transition-colors"
          on:click={closeTagModal}
        >
          취소
        </button>
        <button
          class="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-lg transition-colors"
          on:click={saveTag}
        >
          저장
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- Rule Modal -->
{#if showRuleModal}
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
    on:click|self={closeRuleModal}
    on:keydown={(event) => handleModalBackdropKeydown(event, closeRuleModal)}
    role="dialog"
    tabindex="-1"
  >
    <div
      class="bg-bg-card rounded-xl p-6 w-[500px] border border-border"
      role="document"
    >
      <h3 class="text-lg font-semibold text-text-primary mb-4">
        {editingRule ? '규칙 수정' : '규칙 추가'}
      </h3>

      <div class="space-y-4">
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label for="rule-name" class="block text-sm text-text-secondary mb-1">이름</label>
            <input
              id="rule-name"
              type="text"
              bind:value={ruleForm.name}
              class="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary focus:border-accent outline-none"
              placeholder="규칙 이름"
            />
          </div>
          <div>
            <label for="rule-tag" class="block text-sm text-text-secondary mb-1">태그</label>
            <select
              id="rule-tag"
              bind:value={ruleForm.tag_id}
              class="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary focus:border-accent outline-none"
            >
              {#each tags as tag}
                <option value={tag.id}>{tag.name}</option>
              {/each}
            </select>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label for="rule-priority" class="block text-sm text-text-secondary mb-1">우선순위</label>
            <input
              id="rule-priority"
              type="number"
              bind:value={ruleForm.priority}
              min="0"
              max="100"
              class="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary focus:border-accent outline-none"
            />
          </div>
          <div class="flex items-center pt-6">
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" bind:checked={ruleForm.enabled} class="w-4 h-4 rounded border-border bg-bg-tertiary text-accent">
              <span class="text-sm text-text-secondary">활성화</span>
            </label>
          </div>
        </div>

        <div>
          <label for="rule-process-pattern" class="block text-sm text-text-secondary mb-1">프로세스 패턴</label>
          <input
            id="rule-process-pattern"
            type="text"
            bind:value={ruleForm.process_pattern}
            class="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary font-mono text-sm focus:border-accent outline-none"
            placeholder="예: chrome.exe, *code*.exe"
          />
        </div>

        <div>
          <label for="rule-url-pattern" class="block text-sm text-text-secondary mb-1">URL 패턴</label>
          <input
            id="rule-url-pattern"
            type="text"
            bind:value={ruleForm.url_pattern}
            class="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary font-mono text-sm focus:border-accent outline-none"
            placeholder="예: *youtube.com*, *github.com*"
          />
        </div>

        <div>
          <label for="rule-window-title-pattern" class="block text-sm text-text-secondary mb-1">창 제목 패턴</label>
          <input
            id="rule-window-title-pattern"
            type="text"
            bind:value={ruleForm.window_title_pattern}
            class="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary font-mono text-sm focus:border-accent outline-none"
            placeholder="예: *Visual Studio*"
          />
        </div>

        <div>
          <label for="rule-chrome-profile" class="block text-sm text-text-secondary mb-1">Chrome 프로필</label>
          <input
            id="rule-chrome-profile"
            type="text"
            bind:value={ruleForm.chrome_profile}
            class="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary font-mono text-sm focus:border-accent outline-none"
            placeholder="예: Profile 1, Default"
          />
        </div>

        <div>
          <label for="rule-process-path-pattern" class="block text-sm text-text-secondary mb-1">프로세스 경로 패턴</label>
          <input
            id="rule-process-path-pattern"
            type="text"
            bind:value={ruleForm.process_path_pattern}
            class="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary font-mono text-sm focus:border-accent outline-none"
            placeholder="예: *\\Obsidian\\*, *\\AnkiProgramFiles\\*"
          />
        </div>
      </div>

      <div class="flex justify-end gap-3 mt-6">
        <button
          class="px-4 py-2 text-text-secondary hover:text-text-primary transition-colors"
          on:click={closeRuleModal}
        >
          취소
        </button>
        <button
          class="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-lg transition-colors"
          on:click={saveRule}
        >
          저장
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- Delete Unclassified Modal -->
{#if showDeleteModal}
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
    on:click|self={closeDeleteModal}
    on:keydown={(event) => handleModalBackdropKeydown(event, closeDeleteModal)}
    role="dialog"
    tabindex="-1"
  >
    <div
      class="bg-bg-card rounded-xl p-6 w-[800px] max-h-[80vh] border border-border flex flex-col"
      role="document"
    >
      <h3 class="text-lg font-semibold text-text-primary mb-4">
        미분류 항목 삭제 ({unclassifiedGroups.reduce((sum, g) => sum + g.count, 0)}개)
      </h3>

      <div class="flex gap-2 mb-4">
        <button
          class="px-3 py-1 text-sm bg-bg-secondary hover:bg-bg-hover border border-border rounded transition-colors"
          on:click={selectAllGroups}
        >
          전체 선택
        </button>
        <button
          class="px-3 py-1 text-sm bg-bg-secondary hover:bg-bg-hover border border-border rounded transition-colors"
          on:click={deselectAllGroups}
        >
          전체 해제
        </button>
      </div>

      <div class="flex-1 overflow-auto border border-border rounded-lg">
        <table class="w-full">
          <thead class="bg-bg-secondary sticky top-0">
            <tr>
              <th class="w-12 px-3 py-2 text-left text-xs font-medium text-text-muted">선택</th>
              <th class="px-3 py-2 text-left text-xs font-medium text-text-muted">프로세스</th>
              <th class="px-3 py-2 text-left text-xs font-medium text-text-muted">창 제목</th>
              <th class="px-3 py-2 text-left text-xs font-medium text-text-muted">URL</th>
              <th class="w-16 px-3 py-2 text-right text-xs font-medium text-text-muted">개수</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            {#each unclassifiedGroups as group, index}
              <tr
                class="hover:bg-bg-hover transition-colors cursor-pointer"
                on:click={(event) => toggleSelectionFromRow(event, index)}
                on:keydown={(event) => handleSelectableRowKeydown(event, index)}
                tabindex="0"
              >
                <td class="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selectedGroups.has(index)}
                    on:change={() => toggleGroupSelection(index)}
                    class="w-4 h-4 rounded border-border bg-bg-tertiary text-accent"
                  />
                </td>
                <td class="px-3 py-2 text-sm text-text-primary">{group.process_name || '-'}</td>
                <td class="px-3 py-2 text-sm text-text-secondary truncate max-w-[200px]" title={group.window_title}>
                  {group.window_title || '-'}
                </td>
                <td class="px-3 py-2 text-sm text-text-muted truncate max-w-[200px]" title={group.chrome_url}>
                  {group.chrome_url || '-'}
                </td>
                <td class="px-3 py-2 text-sm text-text-primary text-right font-medium">{group.count}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <div class="flex justify-between items-center mt-4">
        <span class="text-sm text-text-muted">
          선택됨: {[...selectedGroups].reduce((sum, idx) => sum + unclassifiedGroups[idx]?.count || 0, 0)}개
        </span>
        <div class="flex gap-3">
          <button
            class="px-4 py-2 text-text-secondary hover:text-text-primary transition-colors"
            on:click={closeDeleteModal}
          >
            취소
          </button>
          <button
            class="px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors"
            on:click={deleteSelectedActivities}
          >
            삭제
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}

<!-- Delete Tag Confirm Modal -->
<ConfirmModal
  show={showDeleteTagModal}
  title="태그 삭제"
  type="danger"
  confirmText="삭제"
  on:confirm={confirmDeleteTag}
  on:cancel={cancelDeleteTag}
>
  <p><strong class="text-text-primary">'{pendingDeleteTag?.name}'</strong> 태그를 삭제하시겠습니까?</p>
  <p class="text-text-muted">이 태그에 연결된 규칙은 유지되지만 태그 연결이 해제됩니다.</p>
</ConfirmModal>

<!-- Delete Rule Confirm Modal -->
<ConfirmModal
  show={showDeleteRuleModal}
  title="규칙 삭제"
  type="danger"
  confirmText="삭제"
  on:confirm={confirmDeleteRule}
  on:cancel={cancelDeleteRule}
>
  <p><strong class="text-text-primary">'{pendingDeleteRule?.name}'</strong> 규칙을 삭제하시겠습니까?</p>
</ConfirmModal>

<!-- Reclassify Untagged Confirm Modal -->
<ConfirmModal
  show={showReclassifyUntaggedModal}
  title="미분류 재분류"
  type="info"
  confirmText="재분류"
  on:confirm={confirmReclassifyUntagged}
  on:cancel={() => showReclassifyUntaggedModal = false}
>
  <p>미분류 항목을 현재 규칙에 따라 재분류하시겠습니까?</p>
</ConfirmModal>

<!-- Reclassify All Confirm Modal -->
<ConfirmModal
  show={showReclassifyAllModal}
  title="전체 재분류"
  type="danger"
  confirmText="재분류"
  on:confirm={confirmReclassifyAll}
  on:cancel={() => showReclassifyAllModal = false}
>
  <p class="text-yellow-400 font-medium">정말 모든 활동을 재분류하시겠습니까?</p>
  <p class="text-text-muted">이 작업은 시간이 오래 걸릴 수 있습니다.</p>
</ConfirmModal>

<!-- Delete Activities Confirm Modal -->
<ConfirmModal
  show={showDeleteActivitiesModal}
  title="활동 기록 삭제"
  type="danger"
  confirmText="삭제"
  on:confirm={confirmDeleteActivities}
  on:cancel={() => showDeleteActivitiesModal = false}
>
  <p><strong class="text-text-primary">{pendingDeleteCount}개</strong>의 활동 기록을 삭제하시겠습니까?</p>
  <p class="text-yellow-400">이 작업은 되돌릴 수 없습니다.</p>
</ConfirmModal>

<!-- Help Modal -->
<HelpModal show={showHelp} title="태그 관리 도움말" on:close={() => showHelp = false}>
  <div class="space-y-4">
    <div>
      <h4 class="font-semibold text-text-primary mb-2">태그란?</h4>
      <p class="text-text-secondary">
        활동을 분류하는 라벨입니다. 각 태그는 카테고리(업무/비업무/기타)를 가지며,
        통계와 분석에서 이 카테고리를 기준으로 집계됩니다.
      </p>
    </div>

    <div>
      <h4 class="font-semibold text-text-primary mb-2">분류 규칙(룰)</h4>
      <ul class="list-disc list-inside space-y-1 text-text-secondary">
        <li><strong class="text-text-primary">우선순위</strong> - 숫자가 높을수록 먼저 매칭 (100이 1보다 우선)</li>
        <li><strong class="text-text-primary">패턴</strong> - 와일드카드(*) 사용 가능 (예: *youtube*)</li>
        <li><strong class="text-text-primary">Chrome 프로필</strong> - 특정 프로필에서만 매칭</li>
      </ul>
    </div>

    <div>
      <h4 class="font-semibold text-text-primary mb-2">버튼 설명</h4>
      <ul class="list-disc list-inside space-y-1 text-text-secondary">
        <li><strong class="text-text-primary">미분류 재분류</strong> - 태그 없는 활동에 룰 다시 적용</li>
        <li><strong class="text-text-primary">전체 재분류</strong> - 모든 활동에 룰 다시 적용 (시간 소요)</li>
        <li><strong class="text-text-primary">미분류 삭제</strong> - 태그 없는 활동 일괄 삭제</li>
      </ul>
    </div>

    <div class="pt-2 border-t border-border">
      <p class="text-text-muted text-xs">
        팁: 룰 추가 후 "미분류 재분류"를 누르면 기존 활동에도 새 룰이 적용됩니다.
      </p>
    </div>
  </div>
</HelpModal>
