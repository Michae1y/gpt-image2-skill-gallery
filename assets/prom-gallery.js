(() => {
  const data = JSON.parse(document.getElementById('gallery-data').textContent);
  // Keep image-open and favorite controls as siblings, never nested buttons.
  document.querySelectorAll('.tile').forEach(button => {
    const card = document.createElement('article');
    card.className = 'tile';
    card.dataset.tileIndex = button.dataset.tileIndex;
    card.dataset.category = button.dataset.category;
    button.className = 'tile-open';
    button.replaceWith(card);
    card.append(button);
  });
  const tiles = Array.from(document.querySelectorAll('.tile'));
  const chips = Array.from(document.querySelectorAll('.chip'));
  const gallery = document.querySelector('.gallery');
  const empty = document.querySelector('.empty-state');
  const modal = document.querySelector('.modal');
  const modalImage = document.querySelector('.modal-image');
  const modalKicker = document.querySelector('.modal-kicker');
  const modalTitle = document.querySelector('.modal-title');
  const modalEn = document.querySelector('.modal-en');
  const modalTags = document.querySelector('.modal-tags');
  const modalMeta = document.querySelector('.modal-meta');
  const promptLabel = document.querySelector('.prompt-head strong');
  const promptText = document.querySelector('.prompt-text');
  const copyButton = document.querySelector('.copy-button');
  const closeButton = document.querySelector('.modal-close');
  const storageKey = 'prompt-gallery:favorites:v1';
  const knownIds = new Set(data.tiles.map(tile => tile.tileId));
  const missingPrompt = entry => !String(entry.prompt || '').trim() || entry.promptIsComplete !== true;
  const modes = Array.from(document.querySelectorAll('[data-mode]'));
  const resultCount = document.querySelector('.result-count');
  const storageNote = document.querySelector('.storage-note');
  const modalFavorite = document.querySelector('.modal-favorite');
  const promptNotice = document.querySelector('.prompt-notice');
  const exportButton = document.querySelector('.export-favorites');
  let favorites = new Set();
  let activeMode = 'all';
  let onlyMissing = false;
  let activeIndex = null;
  let copyTimer;
  let storageAvailable = true;
  function readFavorites() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || '[]');
      if (!Array.isArray(saved) || !saved.every(id => typeof id === 'string')) throw new Error('Invalid favorites');
      return new Set(saved.filter(id => knownIds.has(id)));
    } catch {
      storageAvailable = false;
      storageNote.textContent = '当前浏览器无法读取收藏记录；本次选择暂存于页面，请导出清单备份。';
      return null;
    }
  }
  favorites = readFavorites() || favorites;
  function refreshFavorites() {
    tiles.forEach(card => {
      const tile = data.tiles[Number(card.dataset.tileIndex)];
      const saved = favorites.has(tile.tileId);
      const button = card.querySelector('.favorite-button');
      button.setAttribute('aria-pressed', String(saved));
      button.setAttribute('aria-label', `${saved ? '取消收藏' : '收藏'}：${tile.alt || tile.title}`);
      button.title = saved ? '取消收藏' : '收藏这张图片';
      button.innerHTML = `<span aria-hidden="true">${saved ? '★' : '☆'}</span><span>${saved ? '已收藏' : '收藏'}</span>`;
    });
    document.querySelector('.favorite-count').textContent = favorites.size;
    exportButton.disabled = favorites.size === 0;
    if (activeIndex !== null) {
      const saved = favorites.has(data.tiles[activeIndex].tileId);
      modalFavorite.textContent = saved ? '★ 已收藏这张图片' : '☆ 收藏这张图片';
      modalFavorite.setAttribute('aria-pressed', String(saved));
    }
  }
  function toggleFavorite(index) {
    // Read the latest selection before writing so other tabs are respected.
    if (storageAvailable) favorites = readFavorites() || favorites;
    const id = data.tiles[index].tileId;
    favorites.has(id) ? favorites.delete(id) : favorites.add(id);
    if (storageAvailable) {
      try { localStorage.setItem(storageKey, JSON.stringify([...favorites])); }
      catch {
        storageAvailable = false;
        storageNote.textContent = '浏览器未能保存收藏；本次选择暂存于页面，请导出清单备份。';
      }
    }
    refreshFavorites();
    if (activeMode === 'favorites') applyFilter(activeCategory);
  }
  tiles.forEach(card => {
    const index = Number(card.dataset.tileIndex);
    const entry = data.entries[data.tiles[index].entryIndex];
    if (missingPrompt(entry)) {
      const badge = document.createElement('span');
      badge.className = 'prompt-badge';
      badge.textContent = '缺少完整提示词';
      card.querySelector('.tile-media').append(badge);
    }
    const favorite = document.createElement('button');
    favorite.type = 'button';
    favorite.className = 'favorite-button';
    favorite.addEventListener('click', () => toggleFavorite(index));
    card.append(favorite);
  });
  const missingCount = data.tiles.filter(tile => missingPrompt(data.entries[tile.entryIndex])).length;
  document.querySelector('.missing-count').textContent = missingCount;
  document.querySelector('.audit-summary').textContent = `${missingCount} 张图片缺少完整提示词（${data.entries.filter(missingPrompt).length} 个条目），已用橙色标签标注。`;
  modes.forEach(button => button.addEventListener('click', () => {
    activeMode = button.dataset.mode;
    applyFilter(activeCategory);
  }));
  document.querySelector('.missing-toggle').addEventListener('click', () => {
    onlyMissing = !onlyMissing;
    applyFilter(activeCategory);
  });
  document.querySelector('.reset-filters').addEventListener('click', () => {
    onlyMissing = false;
    applyFilter('all');
  });
  modalFavorite.addEventListener('click', () => { if (activeIndex !== null) toggleFavorite(activeIndex); });
  window.addEventListener('storage', event => {
    if (event.key === storageKey || event.key === null) {
      favorites = readFavorites() || favorites;
      refreshFavorites();
      applyFilter(activeCategory);
    }
  });
  exportButton.addEventListener('click', () => {
    const assetBase = 'https://michae1y.github.io/gpt-image2-skill-gallery/';
    const selected = data.tiles.filter(tile => favorites.has(tile.tileId)).map(tile => {
      const entry = data.entries[tile.entryIndex];
      const complete = !missingPrompt(entry);
      return {
        tileId: tile.tileId, entryId: entry.id, entryNo: entry.entryNo,
        title: entry.title, imageDescription: tile.alt, category: entry.category,
        imageUrl: new URL(tile.full || tile.src, assetBase).href,
        thumbnailUrl: new URL(tile.src, assetBase).href,
        sourceUrl: entry.sourceUrl || '', promptIsComplete: complete,
        prompt: complete ? entry.prompt : '', sourceText: complete ? '' : entry.prompt || ''
      };
    });
    const blob = new Blob([JSON.stringify({version: 1, exportedAt: new Date().toISOString(), images: selected}, null, 2)], {type: 'application/json;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `精选图片-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  let activePrompt = '';
  let activeCategory = 'all';
  let lastFocus = null;
  let lastColumnCount = 0;
  let layoutFrame = 0;

  function currentColumnCount() {
    return Math.max(1, Number.parseInt(getComputedStyle(gallery).columnCount, 10) || 1);
  }

  function tileRatio(tile) {
    const image = tile.querySelector('img');
    const width = Number(image?.getAttribute('width')) || image?.naturalWidth || 1;
    const height = Number(image?.getAttribute('height')) || image?.naturalHeight || 1;
    return height / Math.max(width, 1);
  }

  function arrangeVisibleTiles(visibleTiles) {
    const columns = currentColumnCount();
    lastColumnCount = columns;
    if (columns === 1) {
      visibleTiles.forEach(tile => gallery.append(tile));
    } else {
      const lanes = Array.from({ length: columns }, () => []);
      const heights = Array(columns).fill(0);
      for (let offset = 0; offset < visibleTiles.length; offset += columns) {
        const row = visibleTiles.slice(offset, offset + columns)
          .sort((first, second) => tileRatio(second) - tileRatio(first));
        const laneOrder = Array.from({ length: columns }, (_, index) => index)
          .sort((first, second) => heights[first] - heights[second] || first - second);
        row.forEach((tile, index) => {
          const lane = laneOrder[index];
          lanes[lane].push(tile);
          heights[lane] += tileRatio(tile);
        });
      }
      lanes.flat().forEach(tile => gallery.append(tile));
    }
    tiles.filter(tile => tile.hidden).forEach(tile => gallery.append(tile));
  }

  function applyFilter(category) {
    activeCategory = category;
    const visibleTiles = [];
    tiles.forEach(tile => {
      const item = data.tiles[Number(tile.dataset.tileIndex)];
      const show = (category === 'all' || tile.dataset.category === category)
        && (activeMode !== 'favorites' || favorites.has(item.tileId))
        && (!onlyMissing || missingPrompt(data.entries[item.entryIndex]));
      tile.hidden = !show;
      if (show) visibleTiles.push(tile);
    });
    arrangeVisibleTiles(visibleTiles);
    empty.classList.toggle('is-visible', visibleTiles.length === 0);
    chips.forEach(chip => {
      chip.classList.toggle('is-active', chip.dataset.filter === category);
      chip.setAttribute('aria-pressed', String(chip.dataset.filter === category));
    });
    modes.forEach(button => {
      button.classList.toggle('is-active', button.dataset.mode === activeMode);
      button.setAttribute('aria-pressed', String(button.dataset.mode === activeMode));
    });
    const missingToggle = document.querySelector('.missing-toggle');
    missingToggle.setAttribute('aria-pressed', String(onlyMissing));
    missingToggle.classList.toggle('is-active', onlyMissing);
    resultCount.textContent = `${activeMode === 'favorites' ? '我的收藏' : '全部图片'} · 当前显示 ${visibleTiles.length} 张`;
    empty.textContent = activeMode === 'favorites' && favorites.size === 0
      ? '还没有收藏。点击图片右上角的 ☆ 收藏，开始挑选你的精选图片。'
      : '当前筛选下暂无图片，试试重置筛选。';
  }

  function openTile(index) {
    const tile = data.tiles[index];
    if (!tile) return;
    const entry = data.entries[tile.entryIndex];
    const image = entry.images[tile.imageIndex] || entry.images[0];
    activeIndex = index;
    clearTimeout(copyTimer);
    lastFocus = document.activeElement;
    modalImage.dataset.fallback = image.src || '';
    modalImage.src = image.full || image.src;
    modalImage.alt = image.alt || entry.title;
    modalKicker.textContent = `${entry.entryNo || 'Reference'} | ${entry.category}`;
    modalTitle.textContent = entry.title || '未命名素材';
    modalEn.textContent = entry.titleEn || image.caption || '';
    modalTags.innerHTML = (entry.tags || []).slice(0, 8).map(tag => `<span>${escapeHtml(tag)}</span>`).join('');
    const platform = entry.sourcePlatform || platformFromUrl(entry.sourceUrl);
    const source = entry.sourceUrl ? `<a class="source-link" href="${escapeAttr(entry.sourceUrl)}" target="_blank" rel="noopener">${escapeHtml(platform)} 来源追溯</a>` : '';
    const meta = (entry.kvs || []).slice(0, 2).join(' ');
    modalMeta.innerHTML = [source, escapeHtml(meta)].filter(Boolean).join(' · ');
    activePrompt = entry.prompt || '这条素材暂未收录完整提示词。';
    const missing = missingPrompt(entry);
    promptNotice.hidden = !missing;
    promptNotice.textContent = entry.prompt?.trim()
      ? '缺少完整提示词 · 当前仅收录帖子正文或摘要，可通过来源链接追溯。'
      : '缺少完整提示词 · 这张图片尚未关联提示词。';
    promptLabel.textContent = missing ? (entry.prompt?.trim() ? '现有正文 / 摘要（非完整提示词）' : '提示词待补充') : (entry.promptLabel || '完整提示词 / Original Prompt');
    refreshFavorites();
    promptText.textContent = activePrompt;
    copyButton.textContent = entry.prompt?.trim() ? (!missing ? '复制' : '复制正文') : '暂无 prompt';
    copyButton.disabled = !entry.prompt?.trim();
    modal.classList.add('is-open');
    document.body.style.overflow = 'hidden';
    closeButton.focus();
  }

  function closeModal() {
    modal.classList.remove('is-open');
    document.body.style.overflow = '';
    modalImage.removeAttribute('src');
    activeIndex = null;
    clearTimeout(copyTimer);
    if (lastFocus?.closest('.tile')?.hidden) document.querySelector('[data-mode="favorites"]').focus();
    else if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  }
  function escapeAttr(value) { return escapeHtml(value).replace(/`/g, '&#96;'); }
  function platformFromUrl(value) {
    if (!value) return '原始';
    try {
      const host = new URL(value).hostname.replace(/^www\./, '');
      if (host === 'x.com' || host === 'twitter.com') return 'X';
      if (host.includes('unsplash.com')) return 'Unsplash';
      if (host.includes('wallhaven.cc')) return 'Wallhaven';
      if (host.includes('behance.net')) return 'Behance';
      if (host.includes('artstation.com')) return 'ArtStation';
      return host;
    } catch {
      return '原始';
    }
  }

  tiles.forEach(tile => {
    const img = tile.querySelector('img');
    img?.addEventListener('error', () => {
      tile.dataset.broken = 'true';
      img.alt = `图片暂时无法加载：${data.tiles[Number(tile.dataset.tileIndex)].title}`;
    }, { once: true });
  });
  modalImage.addEventListener('error', () => {
    const fallback = modalImage.dataset.fallback;
    if (fallback && modalImage.src !== new URL(fallback, window.location.href).href) {
      modalImage.src = fallback;
    }
  });
  chips.forEach(chip => chip.addEventListener('click', () => applyFilter(chip.dataset.filter)));
  tiles.forEach(tile => tile.querySelector('.tile-open').addEventListener('click', () => openTile(Number(tile.dataset.tileIndex))));
  closeButton.addEventListener('click', closeModal);
  modal.addEventListener('click', event => { if (event.target === modal) closeModal(); });
  document.addEventListener('keydown', event => {
    if (!modal.classList.contains('is-open')) return;
    if (event.key === 'Escape') closeModal();
    if (event.key === 'Tab') {
      const focusable = Array.from(modal.querySelectorAll('button:not(:disabled), a[href]'));
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  window.addEventListener('resize', () => {
    cancelAnimationFrame(layoutFrame);
    layoutFrame = requestAnimationFrame(() => {
      if (currentColumnCount() !== lastColumnCount) applyFilter(activeCategory);
    });
  });
  copyButton.addEventListener('click', async () => {
    if (!activePrompt) return;
    const copiedIndex = activeIndex;
    try {
      await navigator.clipboard.writeText(activePrompt);
      if (activeIndex !== copiedIndex) return;
      copyButton.textContent = '已复制';
      copyTimer = setTimeout(() => copyButton.textContent = missingPrompt(data.entries[data.tiles[activeIndex].entryIndex]) ? '复制正文' : '复制', 1200);
    } catch {
      const range = document.createRange();
      range.selectNodeContents(promptText);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      copyButton.textContent = '已选中';
    }
  });
  refreshFavorites();
  applyFilter('all');
})();
