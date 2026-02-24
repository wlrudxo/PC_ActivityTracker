<script>
  import { onMount, tick } from 'svelte';
  import { api } from '../lib/api/client.js';
  import { toast } from '../lib/stores/toast.js';
  import ConfirmModal from '../lib/components/ConfirmModal.svelte';
  import HelpModal from '../lib/components/HelpModal.svelte';
  import HelpButton from '../lib/components/HelpButton.svelte';

  let loading = true;
  let showHelp = false;
  let error = null;

  // Global settings
  let toastEnabled = true;
  let soundEnabled = false;
  let soundMode = 'single';
  let imageEnabled = false;
  let imageMode = 'single';

  // Lists
  let sounds = [];
  let images = [];
  let tagAlerts = [];

  // Selected IDs
  let selectedSoundId = 0;
  let selectedImageId = 0;

  // File input refs
  let soundFileInput;
  let imageFileInput;

  // Modal states
  let showSoundNameModal = false;
  let showImageNameModal = false;
  let showDeleteSoundModal = false;
  let showDeleteImageModal = false;
  let showImageCropModal = false;

  // Pending file/id for modal actions
  let pendingSoundFile = null;
  let pendingImageFile = null;
  let pendingDeleteSoundId = null;
  let pendingDeleteImageId = null;
  let pendingSoundDefaultName = '';
  let pendingImageDefaultName = '';

  // Crop state
  const CROP_RATIO = 2;
  const CROP_TARGET_WIDTH = 364;
  const CROP_TARGET_HEIGHT = 182;
  let cropCanvas;
  let cropImage = null;
  let cropImageSrc = '';
  let cropRect = null; // { x, y, w, h } in original image coords
  let cropBaseSize = null; // { w, h } base size in original coords
  let cropScale = 1;
  let cropDragging = false;
  let cropDragStart = null; // { x, y } in original coords
  let cropRectStart = null; // { x, y } in original coords
  let cropLoading = false;
  let cropSizeFactor = 1;

  async function loadData() {
    loading = true;
    error = null;

    try {
      const [settingsRes, soundsRes, imagesRes, tagsRes] = await Promise.all([
        api.getAlertSettings(),
        api.getAlertSounds(),
        api.getAlertImages(),
        api.getTagAlertSettings()
      ]);

      toastEnabled = settingsRes.toast_enabled;
      soundEnabled = settingsRes.sound_enabled;
      soundMode = settingsRes.sound_mode;
      selectedSoundId = settingsRes.sound_selected;
      imageEnabled = settingsRes.image_enabled;
      imageMode = settingsRes.image_mode;
      selectedImageId = settingsRes.image_selected;

      sounds = soundsRes.sounds || [];
      images = imagesRes.images || [];
      tagAlerts = tagsRes.tags || [];

    } catch (err) {
      console.error('Failed to load notification settings:', err);
      error = err.message;
    } finally {
      loading = false;
    }
  }

  async function updateSetting(key, value) {
    try {
      await api.updateAlertSettings({ [key]: value });
    } catch (err) {
      console.error('Failed to update setting:', err);
      toast.error('설정 저장 실패: ' + err.message);
    }
  }

  async function handleToastToggle() {
    await updateSetting('toast_enabled', toastEnabled);
  }

  async function handleSoundToggle() {
    await updateSetting('sound_enabled', soundEnabled);
  }

  async function handleSoundModeToggle() {
    soundMode = soundMode === 'random' ? 'single' : 'random';
    await updateSetting('sound_mode', soundMode);
  }

  async function handleImageToggle() {
    await updateSetting('image_enabled', imageEnabled);
  }

  async function handleImageModeToggle() {
    imageMode = imageMode === 'random' ? 'single' : 'random';
    await updateSetting('image_mode', imageMode);
  }

  async function handleSoundSelect(soundId) {
    selectedSoundId = soundId;
    await updateSetting('sound_selected', soundId);
  }

  async function handleImageSelect(imageId) {
    selectedImageId = imageId;
    await updateSetting('image_selected', imageId);
  }

  // File upload handlers
  function triggerSoundUpload() {
    soundFileInput.click();
  }

  function triggerImageUpload() {
    imageFileInput.click();
  }

  function handleSoundFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;

    pendingSoundFile = file;
    pendingSoundDefaultName = file.name.replace(/\.[^/.]+$/, '');
    showSoundNameModal = true;
    event.target.value = '';
  }

  async function confirmSoundUpload(event) {
    const name = event.detail?.value;
    showSoundNameModal = false;
    if (!name || !pendingSoundFile) {
      pendingSoundFile = null;
      return;
    }

    try {
      await api.uploadAlertSound(pendingSoundFile, name);
      await loadData();
      toast.success('사운드가 추가되었습니다.');
    } catch (err) {
      toast.error('업로드 실패: ' + err.message);
    }
    pendingSoundFile = null;
  }

  function cancelSoundUpload() {
    showSoundNameModal = false;
    pendingSoundFile = null;
  }

  function handleImageFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;

    pendingImageFile = file;
    pendingImageDefaultName = file.name.replace(/\.[^/.]+$/, '');
    openImageCropModal(file);
    event.target.value = '';
  }

  async function confirmImageUpload(event) {
    const name = event.detail?.value;
    showImageNameModal = false;
    if (!name || !pendingImageFile) {
      pendingImageFile = null;
      pendingImageDefaultName = '';
      return;
    }

    try {
      await api.uploadAlertImage(pendingImageFile, name);
      await loadData();
      toast.success('이미지가 추가되었습니다.');
    } catch (err) {
      toast.error('업로드 실패: ' + err.message);
    }
    pendingImageFile = null;
    pendingImageDefaultName = '';
  }

  function cancelImageUpload() {
    showImageNameModal = false;
    pendingImageFile = null;
    pendingImageDefaultName = '';
  }

  function openImageCropModal(file) {
    cropLoading = true;
    showImageCropModal = true;
    cropRect = null;
    cropBaseSize = null;
    cropImage = null;
    cropImageSrc = '';
    cropSizeFactor = 1;

    const reader = new FileReader();
    reader.onload = () => {
      cropImageSrc = reader.result;
      const img = new Image();
      img.onload = () => {
        cropImage = img;
        cropLoading = false;
        tick().then(initCropCanvas);
      };
      img.src = cropImageSrc;
    };
    reader.readAsDataURL(file);
  }

  function initCropCanvas() {
    if (!cropCanvas || !cropImage) return;

    const maxWidth = 720;
    const maxHeight = 520;
    cropScale = Math.min(
      maxWidth / cropImage.width,
      maxHeight / cropImage.height,
      1
    );

    cropCanvas.width = Math.round(cropImage.width * cropScale);
    cropCanvas.height = Math.round(cropImage.height * cropScale);

    initCropRect();
    drawCropCanvas();
  }

  function initCropRect() {
    if (!cropImage) return;
    const imgW = cropImage.width;
    const imgH = cropImage.height;

    let cropW;
    let cropH;
    if (imgW / imgH > CROP_RATIO) {
      cropH = imgH;
      cropW = Math.round(cropH * CROP_RATIO);
    } else {
      cropW = imgW;
      cropH = Math.round(cropW / CROP_RATIO);
    }

    cropBaseSize = { w: cropW, h: cropH };
    cropRect = {
      x: Math.round((imgW - cropW) / 2),
      y: Math.round((imgH - cropH) / 2),
      w: cropW,
      h: cropH
    };
    cropSizeFactor = 1;
  }

  function drawCropCanvas() {
    if (!cropCanvas || !cropImage || !cropRect) return;
    const ctx = cropCanvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, cropCanvas.width, cropCanvas.height);
    ctx.drawImage(cropImage, 0, 0, cropCanvas.width, cropCanvas.height);

    const rect = {
      x: cropRect.x * cropScale,
      y: cropRect.y * cropScale,
      w: cropRect.w * cropScale,
      h: cropRect.h * cropScale
    };

    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    ctx.fillRect(0, 0, cropCanvas.width, cropCanvas.height);
    ctx.save();
    ctx.globalCompositeOperation = 'destination-out';
    ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
    ctx.restore();

    ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
    ctx.lineWidth = 2;
    ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);

    ctx.setLineDash([6, 4]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.6)';
    const thirdW = rect.w / 3;
    const thirdH = rect.h / 3;
    ctx.beginPath();
    ctx.moveTo(rect.x + thirdW, rect.y);
    ctx.lineTo(rect.x + thirdW, rect.y + rect.h);
    ctx.moveTo(rect.x + thirdW * 2, rect.y);
    ctx.lineTo(rect.x + thirdW * 2, rect.y + rect.h);
    ctx.moveTo(rect.x, rect.y + thirdH);
    ctx.lineTo(rect.x + rect.w, rect.y + thirdH);
    ctx.moveTo(rect.x, rect.y + thirdH * 2);
    ctx.lineTo(rect.x + rect.w, rect.y + thirdH * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function getCanvasPoint(event) {
    const rect = cropCanvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top
    };
  }

  function isPointInCropRect(point) {
    if (!cropRect) return false;
    const rect = {
      x: cropRect.x * cropScale,
      y: cropRect.y * cropScale,
      w: cropRect.w * cropScale,
      h: cropRect.h * cropScale
    };
    return (
      point.x >= rect.x &&
      point.x <= rect.x + rect.w &&
      point.y >= rect.y &&
      point.y <= rect.y + rect.h
    );
  }

  function handleCropPointerDown(event) {
    if (!cropRect || !cropImage) return;
    const point = getCanvasPoint(event);
    if (!isPointInCropRect(point)) return;

    cropDragging = true;
    cropCanvas.setPointerCapture(event.pointerId);
    cropDragStart = { x: point.x / cropScale, y: point.y / cropScale };
    cropRectStart = { x: cropRect.x, y: cropRect.y };
  }

  function handleCropPointerMove(event) {
    if (!cropRect || !cropImage) return;
    const point = getCanvasPoint(event);

    if (!cropDragging) {
      cropCanvas.style.cursor = isPointInCropRect(point) ? 'grab' : 'default';
      return;
    }

    const current = { x: point.x / cropScale, y: point.y / cropScale };
    const delta = { x: current.x - cropDragStart.x, y: current.y - cropDragStart.y };
    const minX = -cropRect.w / 2;
    const maxX = cropImage.width - cropRect.w / 2;
    const minY = -cropRect.h / 2;
    const maxY = cropImage.height - cropRect.h / 2;

    cropRect.x = Math.max(minX, Math.min(cropRectStart.x + delta.x, maxX));
    cropRect.y = Math.max(minY, Math.min(cropRectStart.y + delta.y, maxY));
    drawCropCanvas();
  }

  function handleCropPointerUp(event) {
    if (!cropDragging) return;
    cropDragging = false;
    cropCanvas.releasePointerCapture(event.pointerId);
  }

  function cancelImageCrop() {
    showImageCropModal = false;
    cropLoading = false;
    cropImage = null;
    cropImageSrc = '';
    cropRect = null;
    pendingImageFile = null;
    pendingImageDefaultName = '';
  }

  function confirmImageCrop() {
    if (!cropImage || !cropRect) return;

    const outputCanvas = document.createElement('canvas');
    outputCanvas.width = CROP_TARGET_WIDTH;
    outputCanvas.height = CROP_TARGET_HEIGHT;
    const ctx = outputCanvas.getContext('2d');
    if (!ctx) return;

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, CROP_TARGET_WIDTH, CROP_TARGET_HEIGHT);
    const scale = CROP_TARGET_WIDTH / cropRect.w;
    const destX = -cropRect.x * scale;
    const destY = -cropRect.y * scale;
    ctx.drawImage(
      cropImage,
      destX,
      destY,
      cropImage.width * scale,
      cropImage.height * scale
    );

    outputCanvas.toBlob((blob) => {
      if (!blob) {
        toast.error('이미지 처리 실패');
        return;
      }
      const fileName = `${pendingImageDefaultName || 'alert-image'}.png`;
      pendingImageFile = new File([blob], fileName, { type: 'image/png' });
      showImageCropModal = false;
      showImageNameModal = true;
    }, 'image/png');
  }

  function handleCropSizeChange(event) {
    if (!cropRect || !cropBaseSize) return;
    const nextFactor = parseFloat(event.target.value);
    const centerX = cropRect.x + cropRect.w / 2;
    const centerY = cropRect.y + cropRect.h / 2;
    const nextW = cropBaseSize.w * nextFactor;
    const nextH = cropBaseSize.h * nextFactor;

    cropSizeFactor = nextFactor;
    cropRect.w = nextW;
    cropRect.h = nextH;
    cropRect.x = centerX - nextW / 2;
    cropRect.y = centerY - nextH / 2;
    drawCropCanvas();
  }

  function deleteSound(soundId) {
    pendingDeleteSoundId = soundId;
    showDeleteSoundModal = true;
  }

  async function confirmDeleteSound() {
    showDeleteSoundModal = false;
    if (!pendingDeleteSoundId) return;

    try {
      await api.deleteAlertSound(pendingDeleteSoundId);
      await loadData();
      toast.success('사운드가 삭제되었습니다.');
    } catch (err) {
      toast.error('삭제 실패: ' + err.message);
    }
    pendingDeleteSoundId = null;
  }

  function cancelDeleteSound() {
    showDeleteSoundModal = false;
    pendingDeleteSoundId = null;
  }

  function deleteImage(imageId) {
    pendingDeleteImageId = imageId;
    showDeleteImageModal = true;
  }

  async function confirmDeleteImage() {
    showDeleteImageModal = false;
    if (!pendingDeleteImageId) return;

    try {
      await api.deleteAlertImage(pendingDeleteImageId);
      await loadData();
      toast.success('이미지가 삭제되었습니다.');
    } catch (err) {
      toast.error('삭제 실패: ' + err.message);
    }
    pendingDeleteImageId = null;
  }

  function cancelDeleteImage() {
    showDeleteImageModal = false;
    pendingDeleteImageId = null;
  }

  // Tag alert handlers
  async function updateTagAlert(tagId, field, value) {
    try {
      await api.updateTagAlertSettings(tagId, { [field]: value });
      // Update local state
      tagAlerts = tagAlerts.map(t =>
        t.id === tagId ? { ...t, [field]: value } : t
      );
    } catch (err) {
      toast.error('설정 저장 실패: ' + err.message);
      await loadData();
    }
  }

  function getFileName(filePath) {
    if (!filePath) return '';
    return filePath.split(/[/\\]/).pop();
  }

  function getImageUrl(imageId) {
    const base = window.location.protocol === 'file:'
      ? 'http://127.0.0.1:8000/api'
      : '/api';
    return `${base}/alerts/images/file/${imageId}`;
  }

  onMount(() => {
    loadData();
  });
</script>

<!-- Hidden file inputs -->
<input
  type="file"
  accept=".wav"
  bind:this={soundFileInput}
  on:change={handleSoundFileSelect}
  class="hidden"
/>
<input
  type="file"
  accept=".png,.jpg,.jpeg"
  bind:this={imageFileInput}
  on:change={handleImageFileSelect}
  class="hidden"
/>

<div class="p-6 space-y-6">
  <div>
    <div class="flex items-center gap-2">
      <h1 class="text-2xl font-bold text-text-primary">알림 설정</h1>
      <HelpButton on:click={() => showHelp = true} />
    </div>
    <p class="text-sm text-text-secondary mt-1">토스트 알림, 사운드, 이미지, 태그별 알림을 설정합니다</p>
  </div>

  <!-- Error Banner -->
  {#if error}
    <div class="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-sm text-red-400">
      데이터 로드 실패: {error}
    </div>
  {/if}

  {#if loading}
    <div class="flex items-center justify-center py-12">
      <div class="text-text-muted">로딩 중...</div>
    </div>
  {:else}
    <!-- Global Settings -->
    <div class="bg-bg-card rounded-xl border border-border p-5 space-y-4">
      <h2 class="text-lg font-semibold text-text-primary">전역 설정</h2>

      <div class="flex items-center justify-between py-2">
        <div>
          <div class="text-text-primary font-medium">토스트 알림</div>
          <div class="text-sm text-text-muted">Windows 토스트 알림을 표시합니다</div>
        </div>
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" bind:checked={toastEnabled} on:change={handleToastToggle} class="sr-only peer">
          <div class="w-11 h-6 bg-bg-tertiary rounded-full peer peer-checked:bg-accent transition-colors after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:after:translate-x-5"></div>
        </label>
      </div>
    </div>

    <!-- Sound Settings -->
    <div class="bg-bg-card rounded-xl border border-border p-5 space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-text-primary">사운드</h2>
        <div class="flex items-center gap-4">
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" bind:checked={soundEnabled} on:change={handleSoundToggle} class="w-4 h-4 rounded border-border bg-bg-tertiary text-accent focus:ring-accent focus:ring-offset-0">
            <span class="text-sm text-text-secondary">사운드 재생</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={soundMode === 'random'} on:change={handleSoundModeToggle} class="w-4 h-4 rounded border-border bg-bg-tertiary text-accent focus:ring-accent focus:ring-offset-0">
            <span class="text-sm text-text-secondary">랜덤</span>
          </label>
        </div>
      </div>

      <div class="space-y-2">
        {#each sounds as sound}
          <div
            class="flex items-center justify-between p-3 rounded-lg cursor-pointer transition-colors {selectedSoundId === sound.id ? 'bg-accent/20 border border-accent/50' : 'bg-bg-secondary hover:bg-bg-hover'}"
            on:click={() => handleSoundSelect(sound.id)}
            on:keypress={(e) => e.key === 'Enter' && handleSoundSelect(sound.id)}
            role="button"
            tabindex="0"
          >
            <div class="flex items-center gap-3">
              <svg class="w-5 h-5 text-text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
              </svg>
              <div>
                <span class="text-text-primary">{sound.name}</span>
                <span class="text-xs text-text-muted ml-2">({getFileName(sound.file_path)})</span>
              </div>
            </div>
            <button
              class="p-2 rounded-lg hover:bg-red-500/20 transition-colors"
              on:click|stopPropagation={() => deleteSound(sound.id)}
              aria-label="삭제"
            >
              <svg class="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        {:else}
          <div class="text-center py-4 text-text-muted text-sm">등록된 사운드가 없습니다</div>
        {/each}
      </div>

      <button
        class="w-full py-2 border-2 border-dashed border-border rounded-lg text-text-muted hover:border-accent hover:text-accent transition-colors"
        on:click={triggerSoundUpload}
      >
        + 사운드 추가
      </button>

      <p class="text-xs text-text-muted">WAV만 지원. 사운드가 없으면 시스템 기본음 재생.</p>
    </div>

    <!-- Image Settings -->
    <div class="bg-bg-card rounded-xl border border-border p-5 space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-text-primary">이미지</h2>
        <div class="flex items-center gap-4">
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" bind:checked={imageEnabled} on:change={handleImageToggle} class="w-4 h-4 rounded border-border bg-bg-tertiary text-accent focus:ring-accent focus:ring-offset-0">
            <span class="text-sm text-text-secondary">이미지 표시</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={imageMode === 'random'} on:change={handleImageModeToggle} class="w-4 h-4 rounded border-border bg-bg-tertiary text-accent focus:ring-accent focus:ring-offset-0">
            <span class="text-sm text-text-secondary">랜덤</span>
          </label>
        </div>
      </div>

      <div class="grid grid-cols-4 gap-4">
        {#each images as image}
          <div
            class="relative group rounded-lg overflow-hidden border cursor-pointer transition-all {selectedImageId === image.id ? 'border-accent ring-2 ring-accent/30' : 'border-border hover:border-accent/50'}"
            on:click={() => handleImageSelect(image.id)}
            on:keypress={(e) => e.key === 'Enter' && handleImageSelect(image.id)}
            role="button"
            tabindex="0"
          >
            <div class="aspect-[2/1] bg-bg-tertiary">
              <img
                src={getImageUrl(image.id)}
                alt={image.name}
                class="w-full h-full object-cover"
              />
            </div>
            <div class="p-2 bg-bg-secondary">
              <div class="text-sm text-text-primary truncate">{image.name}</div>
            </div>
            <div class="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
              <button
                class="p-2 rounded-lg bg-bg-card hover:bg-red-500/20 transition-colors"
                on:click|stopPropagation={() => deleteImage(image.id)}
                aria-label="삭제"
              >
                <svg class="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
          </div>
        {/each}
        <button
          class="aspect-[2/1] border-2 border-dashed border-border rounded-lg text-text-muted hover:border-accent hover:text-accent transition-colors flex items-center justify-center"
          on:click={triggerImageUpload}
        >
          + 이미지 추가
        </button>
      </div>

      <p class="text-xs text-text-muted">PNG, JPG 지원. 업로드 전에 2:1 비율로 크롭합니다.</p>
    </div>

    <!-- Per-Tag Alert Settings -->
    <div class="bg-bg-card rounded-xl border border-border p-5 space-y-4">
      <h2 class="text-lg font-semibold text-text-primary">태그별 알림</h2>
      <p class="text-xs text-text-muted -mt-2">특정 태그 활동 감지 시 알림을 보냅니다. 쿨다운 시간 동안 중복 알림을 방지합니다.</p>

      <div class="space-y-3">
        {#each tagAlerts as tag}
          <div class="flex items-center gap-4 p-4 bg-bg-secondary rounded-lg">
            <div class="w-4 h-4 rounded-full flex-shrink-0" style="background-color: {tag.color}"></div>
            <span class="font-medium text-text-primary w-20 flex-shrink-0">{tag.name}</span>

            <label class="flex items-center gap-2 cursor-pointer flex-shrink-0">
              <input
                type="checkbox"
                checked={tag.alert_enabled}
                on:change={(e) => updateTagAlert(tag.id, 'alert_enabled', e.target.checked)}
                class="w-4 h-4 rounded border-border bg-bg-tertiary text-accent focus:ring-accent focus:ring-offset-0"
              >
              <span class="text-sm text-text-secondary">활성화</span>
            </label>

            <input
              type="text"
              value={tag.alert_message}
              placeholder="알림 메시지"
              on:blur={(e) => updateTagAlert(tag.id, 'alert_message', e.target.value)}
              class="flex-1 px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary text-sm focus:border-accent focus:ring-1 focus:ring-accent outline-none"
            />

            <div class="flex items-center gap-2 flex-shrink-0">
              <span class="text-sm text-text-muted">쿨다운</span>
              <input
                type="number"
                value={tag.alert_cooldown}
                min="1"
                on:blur={(e) => updateTagAlert(tag.id, 'alert_cooldown', parseInt(e.target.value) || 30)}
                class="w-16 px-2 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary text-sm text-center focus:border-accent focus:ring-1 focus:ring-accent outline-none"
              />
              <span class="text-sm text-text-muted">초</span>
            </div>
          </div>
        {:else}
          <div class="text-center py-4 text-text-muted text-sm">태그가 없습니다</div>
        {/each}
      </div>
    </div>
  {/if}
</div>

{#if showImageCropModal}
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" on:click={cancelImageCrop}>
    <div class="bg-bg-card rounded-xl p-6 border border-border w-[860px] max-w-[92vw]" on:click|stopPropagation>
      <div class="flex items-start justify-between gap-4 mb-4">
        <div>
          <h3 class="text-lg font-semibold text-text-primary">이미지 크롭</h3>
          <p class="text-sm text-text-muted">드래그해서 2:1 영역을 이동하세요.</p>
        </div>
        <button
          class="p-2 rounded-lg bg-bg-tertiary border border-border text-text-muted hover:text-text-primary hover:bg-bg-hover transition-colors"
          on:click={cancelImageCrop}
          aria-label="닫기"
        >
          ✕
        </button>
      </div>

      {#if cropLoading}
        <div class="py-16 text-center text-text-muted">이미지 불러오는 중...</div>
      {:else}
        <div class="flex items-center justify-center">
          <canvas
            bind:this={cropCanvas}
            class="border border-border rounded-lg bg-bg-tertiary max-w-full"
            on:pointerdown={handleCropPointerDown}
            on:pointermove={handleCropPointerMove}
            on:pointerup={handleCropPointerUp}
            on:pointerleave={handleCropPointerUp}
          ></canvas>
        </div>
        <div class="mt-4">
          <label class="text-xs text-text-muted block mb-2">크롭 크기</label>
          <input
            type="range"
            min="0.5"
            max="2.5"
            step="0.05"
            value={cropSizeFactor}
            on:input={handleCropSizeChange}
            class="w-full accent-accent"
          />
          <div class="mt-1 text-xs text-text-muted text-right">{Math.round(cropSizeFactor * 100)}%</div>
        </div>
      {/if}

      <div class="flex items-center justify-between mt-4">
        <p class="text-xs text-text-muted">최종 저장 크기: 364x182 (2:1)</p>
        <div class="flex gap-3">
          <button
            class="px-4 py-2 rounded-lg bg-bg-tertiary border border-border text-text-secondary hover:bg-bg-hover transition-colors"
            on:click={cancelImageCrop}
          >
            취소
          </button>
          <button
            class="px-4 py-2 rounded-lg bg-accent text-white hover:brightness-110 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            on:click={confirmImageCrop}
            disabled={cropLoading || !cropRect}
          >
            적용
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}

<!-- Sound Name Prompt Modal -->
<ConfirmModal
  show={showSoundNameModal}
  title="사운드 이름 입력"
  type="info"
  mode="prompt"
  placeholder="사운드 이름"
  initialValue={pendingSoundDefaultName}
  confirmText="추가"
  on:confirm={confirmSoundUpload}
  on:cancel={cancelSoundUpload}
>
  <p>업로드할 사운드의 이름을 입력하세요.</p>
</ConfirmModal>

<!-- Image Name Prompt Modal -->
<ConfirmModal
  show={showImageNameModal}
  title="이미지 이름 입력"
  type="info"
  mode="prompt"
  placeholder="이미지 이름"
  initialValue={pendingImageDefaultName}
  confirmText="추가"
  on:confirm={confirmImageUpload}
  on:cancel={cancelImageUpload}
>
  <p>업로드할 이미지의 이름을 입력하세요.</p>
</ConfirmModal>

<!-- Delete Sound Confirm Modal -->
<ConfirmModal
  show={showDeleteSoundModal}
  title="사운드 삭제"
  type="danger"
  confirmText="삭제"
  on:confirm={confirmDeleteSound}
  on:cancel={cancelDeleteSound}
>
  <p>이 사운드를 삭제하시겠습니까?</p>
</ConfirmModal>

<!-- Delete Image Confirm Modal -->
<ConfirmModal
  show={showDeleteImageModal}
  title="이미지 삭제"
  type="danger"
  confirmText="삭제"
  on:confirm={confirmDeleteImage}
  on:cancel={cancelDeleteImage}
>
  <p>이 이미지를 삭제하시겠습니까?</p>
</ConfirmModal>

<!-- Help Modal -->
<HelpModal show={showHelp} title="알림 설정 도움말" on:close={() => showHelp = false}>
  <div class="space-y-4">
    <div>
      <h4 class="font-semibold text-text-primary mb-2">알림 시스템</h4>
      <p class="text-text-secondary">
        태그가 변경될 때 토스트 알림, 사운드, 이미지로 알려줍니다.
        태그별로 알림 방식을 다르게 설정할 수 있습니다.
      </p>
    </div>

    <div>
      <h4 class="font-semibold text-text-primary mb-2">알림 종류</h4>
      <ul class="list-disc list-inside space-y-1 text-text-secondary">
        <li><strong class="text-text-primary">토스트</strong> - Windows 알림 센터에 표시</li>
        <li><strong class="text-text-primary">사운드</strong> - 알림음 재생 (단일/랜덤 선택)</li>
        <li><strong class="text-text-primary">이미지</strong> - 토스트에 히어로 이미지 표시 (364x180)</li>
      </ul>
    </div>

    <div>
      <h4 class="font-semibold text-text-primary mb-2">태그별 알림</h4>
      <ul class="list-disc list-inside space-y-1 text-text-secondary">
        <li><strong class="text-text-primary">전역 설정 사용</strong> - 위의 공통 설정 따름</li>
        <li><strong class="text-text-primary">알림 끄기</strong> - 해당 태그는 알림 없음</li>
        <li><strong class="text-text-primary">커스텀</strong> - 태그별 사운드/이미지 지정</li>
      </ul>
    </div>

    <div class="pt-2 border-t border-border">
      <p class="text-text-muted text-xs">
        팁: 토스트가 안 보이면 Windows 설정 → 시스템 → 알림에서 앱 알림을 확인하세요.
      </p>
    </div>
  </div>
</HelpModal>
