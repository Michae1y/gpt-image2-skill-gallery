const state = {
  view: 'review',
  candidateStatus: 'review',
  categories: [],
  candidates: [],
  published: [],
  sources: [],
  jobs: [],
  selected: new Set(),
  editor: null,
  toastTimer: 0,
};

const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => Array.from(scope.querySelectorAll(selector));

const escapeHtml = (value = '') => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

const api = async (path, options = {}) => {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (response.status === 401) {
    showLogin();
    throw new Error('请重新登录');
  }
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (error) {
      // Keep the HTTP fallback message.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
};

const uploadApi = async (path, body) => {
  const response = await fetch(path, { method: 'POST', body, credentials: 'same-origin' });
  if (response.status === 401) {
    showLogin();
    throw new Error('请重新登录');
  }
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try { detail = (await response.json()).detail || detail; } catch (error) { /* use fallback */ }
    throw new Error(detail);
  }
  return response.json();
};

const toast = (message, error = false) => {
  const node = $('#toast');
  node.textContent = message;
  node.classList.toggle('is-error', error);
  node.classList.add('is-visible');
  window.clearTimeout(state.toastTimer);
  state.toastTimer = window.setTimeout(() => node.classList.remove('is-visible'), 2600);
};

const showLogin = () => {
  $('#login-screen').hidden = false;
  $('#app-shell').hidden = true;
  closeEditor();
};

const showApp = () => {
  $('#login-screen').hidden = true;
  $('#app-shell').hidden = false;
};

const publicAssetUrl = (path) => {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  return `https://michae1y.github.io/gpt-image2-skill-gallery/${path.replace(/^\//, '')}`;
};

const candidateAssetUrl = (candidate, media) => {
  if (!media) return '';
  if (media.preview_path) {
    const filename = media.preview_path.split('/').pop();
    return `/api/media/${encodeURIComponent(candidate.id)}/${encodeURIComponent(filename)}`;
  }
  return media.source_url || '';
};

const statusLabel = (status) => ({
  pending: '待补 prompt',
  prompt_ready: '原词已核验',
  needs_review: '反推待审核',
  approved: '已批准',
  published: '已发布',
  failed: '采集异常',
  rejected: '已移除',
}[status] || status || '待处理');

const statusClass = (status) => {
  if (status === 'approved' || status === 'prompt_ready' || status === 'published') return 'ready';
  if (status === 'failed' || status === 'rejected') return 'failed';
  return '';
};

const formatDate = (value) => {
  if (!value) return '时间未记录';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
};

const debounce = (fn, delay = 260) => {
  let timer = 0;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
};

const setBusy = (button, busy, busyText = '处理中') => {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
};

async function loadSummary() {
  const summary = await api('/api/summary');
  $('#summary-pending').textContent = summary.queue.pending;
  $('#summary-approved').textContent = summary.queue.approved;
  $('#summary-published').textContent = summary.public.entries;
  $('#summary-sources').textContent = summary.queue.enabled_sources;
  $('#nav-review-count').textContent = summary.queue.pending;
}

async function loadCategories() {
  state.categories = await api('/api/categories');
  const options = state.categories.map((category) => (
    `<option value="${escapeHtml(category.id)}">${escapeHtml(category.label)}</option>`
  )).join('');
  $('#editor-category').innerHTML = options;
}

async function loadCandidates() {
  const query = $('#candidate-search').value.trim();
  const params = new URLSearchParams({ status: state.candidateStatus, q: query, limit: '300' });
  state.candidates = await api(`/api/candidates?${params}`);
  renderCandidates();
}

function renderCandidates() {
  const list = $('#candidate-list');
  list.innerHTML = state.candidates.map((candidate) => {
    const media = (candidate.media || [])[0];
    const imageUrl = candidateAssetUrl(candidate, media);
    const checked = state.selected.has(candidate.id) ? 'checked' : '';
    const promptPreview = candidate.active_prompt || candidate.quality_notes || candidate.source_text || '尚未获得可用提示词。';
    return `
      <article class="candidate-card" data-candidate-id="${escapeHtml(candidate.id)}">
        <label class="select-cell" title="选择发布"><input type="checkbox" data-select-candidate="${escapeHtml(candidate.id)}" ${checked}></label>
        <div class="candidate-thumb">
          ${imageUrl ? `<img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(candidate.title)}" loading="lazy">` : ''}
          <span class="image-count">${candidate.media?.length || 0} 图</span>
        </div>
        <div class="candidate-body">
          <div class="candidate-meta"><span>${escapeHtml((candidate.platform || '').toUpperCase())}</span><span>${escapeHtml(candidate.author || '未署名')}</span><span>${escapeHtml(formatDate(candidate.source_published_at || candidate.collected_at))}</span></div>
          <h3>${escapeHtml(candidate.title || '未命名素材')}</h3>
          <p>${escapeHtml(promptPreview)}</p>
        </div>
        <div class="candidate-side">
          <span class="status-badge ${statusClass(candidate.status)}">${escapeHtml(statusLabel(candidate.status))}</span>
          <span class="category-label">${escapeHtml(candidate.category_label || '待分类')}</span>
          <button class="text-action" type="button" data-open-candidate="${escapeHtml(candidate.id)}">审核与编辑 →</button>
        </div>
      </article>`;
  }).join('');
  $('#candidate-empty').hidden = state.candidates.length > 0;

  $$('[data-select-candidate]', list).forEach((checkbox) => {
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) state.selected.add(checkbox.dataset.selectCandidate);
      else state.selected.delete(checkbox.dataset.selectCandidate);
    });
  });
  $$('[data-open-candidate]', list).forEach((button) => {
    button.addEventListener('click', () => openCandidate(button.dataset.openCandidate));
  });
}

async function loadPublished() {
  const params = new URLSearchParams({
    q: $('#published-search').value.trim(),
    include_hidden: String($('#show-hidden').checked),
  });
  state.published = await api(`/api/published?${params}`);
  renderPublished();
}

function renderPublished() {
  const list = $('#published-list');
  list.innerHTML = state.published.map((entry) => {
    const image = entry.images?.[0];
    return `
      <article class="published-card ${entry.hidden ? 'is-hidden' : ''}">
        <button type="button" data-open-published="${escapeHtml(entry.id)}">
          <div class="published-image">${image ? `<img src="${escapeHtml(publicAssetUrl(image.src))}" alt="${escapeHtml(entry.title)}" loading="lazy">` : ''}</div>
          <div class="published-copy"><small>${escapeHtml(entry.entry_no || 'REF')} · ${escapeHtml(entry.category)}</small><h3>${escapeHtml(entry.title)}</h3><p>${escapeHtml(entry.source_url || entry.title_en || '站内条目')}</p></div>
        </button>
      </article>`;
  }).join('');
  $$('[data-open-published]', list).forEach((button) => {
    button.addEventListener('click', () => openPublished(button.dataset.openPublished));
  });
}

async function loadSources() {
  state.sources = await api('/api/sources');
  renderSources();
}

function renderSources() {
  $('#source-list').innerHTML = state.sources.map((source) => `
    <article class="source-row" data-source-id="${escapeHtml(source.id)}">
      <button class="switch ${source.enabled ? 'is-on' : ''}" type="button" data-toggle-source="${escapeHtml(source.id)}" aria-label="${source.enabled ? '停用' : '启用'} ${escapeHtml(source.label)}"></button>
      <div><span class="source-platform">${escapeHtml(source.platform.toUpperCase())}</span><strong>${escapeHtml(source.label)}</strong></div>
      <span class="source-locator">${escapeHtml(source.locator)}</span>
      <span class="source-frequency">每 ${escapeHtml(source.frequency_hours)} 小时</span>
      <span class="source-state ${source.last_error ? 'error' : ''}">${source.last_error ? escapeHtml(source.last_error) : escapeHtml(source.last_checked_at ? `上次 ${formatDate(source.last_checked_at)}` : '尚未运行')}</span>
      <button class="icon-button" type="button" data-delete-source="${escapeHtml(source.id)}" title="删除来源" aria-label="删除来源">×</button>
    </article>`).join('');

  $$('[data-toggle-source]').forEach((button) => button.addEventListener('click', async () => {
    const source = state.sources.find((item) => item.id === button.dataset.toggleSource);
    if (!source) return;
    try {
      await api('/api/sources', {
        method: 'POST',
        body: JSON.stringify({
          ...source,
          enabled: !source.enabled,
          config: source.config || {},
        }),
      });
      await Promise.all([loadSources(), loadSummary()]);
    } catch (error) {
      toast(error.message, true);
    }
  }));

  $$('[data-delete-source]').forEach((button) => button.addEventListener('click', async () => {
    const source = state.sources.find((item) => item.id === button.dataset.deleteSource);
    if (!source || !window.confirm(`删除采集源“${source.label}”？`)) return;
    try {
      await api(`/api/sources/${encodeURIComponent(source.id)}`, { method: 'DELETE' });
      await Promise.all([loadSources(), loadSummary()]);
      toast('采集源已删除');
    } catch (error) {
      toast(error.message, true);
    }
  }));
}

async function loadJobs() {
  state.jobs = await api('/api/jobs?limit=100');
  $('#job-list').innerHTML = state.jobs.map((job) => `
    <div class="job-row"><span>${escapeHtml(formatDate(job.started_at))}</span><strong>${escapeHtml(job.job_type)}</strong><span class="status-badge ${statusClass(job.status)}">${escapeHtml(job.status)}</span><span>${escapeHtml(job.summary || '无摘要')}</span></div>
  `).join('');
}

const viewTitles = {
  review: '审核队列',
  published: '已发布内容',
  sources: '采集源',
  jobs: '运行记录',
};

async function switchView(view) {
  state.view = view;
  $$('.nav-item').forEach((button) => button.classList.toggle('is-active', button.dataset.view === view));
  $$('.view').forEach((section) => section.classList.toggle('is-active', section.id === `view-${view}`));
  $('#view-title').textContent = viewTitles[view];
  $('#publish-button').hidden = !['review', 'published'].includes(view);
  $('#publish-button').innerHTML = view === 'published'
    ? '<span>↑</span>发布站点更改'
    : '<span>↑</span>发布选中项';
  $('#collect-button').hidden = view === 'published';
  if (view === 'review') await loadCandidates();
  if (view === 'published') await loadPublished();
  if (view === 'sources') await loadSources();
  if (view === 'jobs') await loadJobs();
}

function renderEditorMedia(record, kind) {
  const media = kind === 'candidate' ? (record.media || []) : (record.images || []);
  $('#editor-media').innerHTML = media.map((item, index) => {
    const src = kind === 'candidate' ? candidateAssetUrl(record, item) : publicAssetUrl(item.full || item.src);
    return `<figure><img src="${escapeHtml(src)}" alt="图片 ${index + 1}"></figure>`;
  }).join('') || '<figure></figure>';
}

function openEditor(record, kind) {
  state.editor = { record, kind };
  $('#editor-kind').value = kind;
  $('#editor-id').value = record.id;
  $('#editor-heading').textContent = record.title || '素材详情';
  $('#editor-status').textContent = kind === 'candidate' ? statusLabel(record.status) : (record.hidden ? '已隐藏' : '线上');
  $('#editor-status').className = `status-badge ${statusClass(record.status)}`;
  $('#editor-title').value = record.title || '';
  $('#editor-category').value = record.category_id || record.section_id || '';
  $('#editor-prompt').value = record.active_prompt || record.prompt || '';
  $('#editor-prompt-kind').textContent = kind === 'candidate'
    ? ({ original: '原始 prompt 已核验', reverse: '图片反推 prompt', pending: '提示词待补' }[record.prompt_kind] || '来源待核验')
    : (record.prompt_label || '站内提示词');
  $('#editor-quality').textContent = record.quality_score != null ? `复原质检 ${record.quality_score}/100` : '未进行复原打分';
  $('#editor-source').href = record.canonical_url || record.source_url || '#';
  $('#editor-hide').textContent = record.hidden ? '恢复显示' : '隐藏';
  $('#editor-approve').hidden = kind !== 'candidate';
  $('#editor-approve').textContent = record.status === 'approved' ? '已批准' : '批准';
  renderEditorMedia(record, kind);
  document.body.classList.add('drawer-open');
  $('#editor-drawer').setAttribute('aria-hidden', 'false');
}

async function openCandidate(id) {
  try {
    const record = await api(`/api/candidates/${encodeURIComponent(id)}`);
    openEditor(record, 'candidate');
  } catch (error) {
    toast(error.message, true);
  }
}

function openPublished(id) {
  const record = state.published.find((item) => item.id === id);
  if (record) openEditor(record, 'published');
}

function closeEditor() {
  state.editor = null;
  document.body.classList.remove('drawer-open');
  $('#editor-drawer')?.setAttribute('aria-hidden', 'true');
}

async function saveEditor() {
  const editor = state.editor;
  if (!editor) return;
  const categoryId = $('#editor-category').value;
  const category = state.categories.find((item) => item.id === categoryId);
  if (editor.kind === 'candidate') {
    const result = await api(`/api/candidates/${encodeURIComponent(editor.record.id)}`, {
      method: 'PATCH',
      body: JSON.stringify({
        title: $('#editor-title').value.trim(),
        active_prompt: $('#editor-prompt').value.trim(),
        category_id: categoryId,
        category_label: category?.label || '',
      }),
    });
    openEditor(result, 'candidate');
    await loadCandidates();
  } else {
    await api(`/api/published/${encodeURIComponent(editor.record.id)}`, {
      method: 'PATCH',
      body: JSON.stringify({
        title: $('#editor-title').value.trim(),
        prompt: $('#editor-prompt').value.trim(),
        category_id: categoryId,
      }),
    });
    await loadPublished();
    const updated = state.published.find((item) => item.id === editor.record.id);
    if (updated) openEditor(updated, 'published');
  }
  toast('修改已保存，发布后同步到两个前台');
}

async function toggleEditorHidden() {
  const editor = state.editor;
  if (!editor) return;
  const hidden = !Boolean(editor.record.hidden);
  if (editor.kind === 'candidate') {
    const result = await api(`/api/candidates/${encodeURIComponent(editor.record.id)}`, {
      method: 'PATCH', body: JSON.stringify({ hidden }),
    });
    openEditor(result, 'candidate');
    await loadCandidates();
  } else {
    await api(`/api/published/${encodeURIComponent(editor.record.id)}`, {
      method: 'PATCH', body: JSON.stringify({ hidden }),
    });
    await loadPublished();
    const updated = state.published.find((item) => item.id === editor.record.id);
    if (updated) openEditor(updated, 'published');
  }
  toast(hidden ? '已隐藏，发布后从两个前台消失' : '已恢复显示');
}

async function approveEditor() {
  const editor = state.editor;
  if (!editor || editor.kind !== 'candidate') return;
  if (!$('#editor-prompt').value.trim()) {
    toast('提示词为空，不能批准', true);
    return;
  }
  await saveEditor();
  const result = await api(`/api/candidates/${encodeURIComponent(editor.record.id)}`, {
    method: 'PATCH', body: JSON.stringify({ status: 'approved' }),
  });
  state.selected.add(result.id);
  openEditor(result, 'candidate');
  await Promise.all([loadCandidates(), loadSummary()]);
  toast('已批准并加入本次发布');
}

async function deleteEditor() {
  const editor = state.editor;
  if (!editor) return;
  if (!window.confirm(`确认删除“${editor.record.title}”？已发布条目会先存入本地归档。`)) return;
  if (editor.kind === 'candidate') {
    await api(`/api/candidates/${encodeURIComponent(editor.record.id)}`, {
      method: 'PATCH', body: JSON.stringify({ status: 'rejected' }),
    });
    state.selected.delete(editor.record.id);
    await loadCandidates();
  } else {
    await api(`/api/published/${encodeURIComponent(editor.record.id)}`, { method: 'DELETE' });
    await loadPublished();
  }
  closeEditor();
  await loadSummary();
  toast('条目已移除，等待发布同步');
}

async function publishSelected() {
  const ids = Array.from(state.selected);
  if (!ids.length && state.view !== 'published') {
    toast('请先选择要发布的审核条目', true);
    return;
  }
  const button = $('#publish-button');
  setBusy(button, true, '发布中');
  try {
    const result = await api('/api/publish', {
      method: 'POST',
      body: JSON.stringify({
        candidate_ids: ids,
        commit_message: ids.length
          ? `Publish ${ids.length} reviewed gallery references`
          : 'Update published gallery entries',
      }),
    });
    state.selected.clear();
    await Promise.all([loadCandidates(), loadSummary()]);
    toast(ids.length
      ? `已生成 ${result.entry_ids.length} 个条目并同步两个前台${result.commit ? `，提交 ${result.commit}` : ''}`
      : `站点修改已同步到两个前台${result.commit ? `，提交 ${result.commit}` : ''}`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function collectNow() {
  const button = $('#collect-button');
  setBusy(button, true, '已启动');
  try {
    await api('/api/collect', { method: 'POST', body: '{}' });
    toast('采集任务已启动，结果会进入审核队列');
    window.setTimeout(async () => {
      await Promise.all([loadCandidates(), loadJobs(), loadSummary()]);
      setBusy(button, false);
    }, 3500);
  } catch (error) {
    setBusy(button, false);
    toast(error.message, true);
  }
}

async function submitImport(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const payload = {
    platform: data.get('platform'),
    canonical_url: data.get('canonical_url').trim(),
    author: data.get('author').trim(),
    title: data.get('title').trim(),
    source_text: data.get('source_text').trim(),
    media_urls: data.get('media_urls').split(/\n+/).map((value) => value.trim()).filter(Boolean),
    prompt: data.get('prompt').trim(),
    rights_confirmed: data.get('rights_confirmed') === 'on',
  };
  try {
    const files = data.getAll('images').filter((file) => file && file.size > 0);
    let result;
    if (files.length) {
      const upload = new FormData();
      ['platform', 'canonical_url', 'author', 'title', 'source_text', 'prompt'].forEach((key) => upload.append(key, payload[key]));
      upload.append('rights_confirmed', String(payload.rights_confirmed));
      files.forEach((file) => upload.append('images', file));
      result = await uploadApi('/api/import-upload', upload);
    } else if (payload.media_urls.length) {
      result = await api('/api/import', { method: 'POST', body: JSON.stringify(payload) });
    } else {
      result = await api('/api/import-link', {
        method: 'POST',
        body: JSON.stringify({ url: payload.canonical_url, rights_confirmed: payload.rights_confirmed }),
      });
    }
    $('#import-dialog').close();
    form.reset();
    await Promise.all([loadCandidates(), loadSummary()]);
    toast(result.created ? '素材已进入审核队列' : '这个来源已经收录过');
  } catch (error) {
    toast(error.message, true);
  }
}

async function submitSource(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const platform = data.get('platform');
  const locator = data.get('locator').trim();
  const payload = {
    platform,
    source_type: platform === 'x' ? 'creator' : 'discovery',
    label: data.get('label').trim(),
    locator,
    enabled: data.get('enabled') === 'on',
    collection_mode: ['design-milk', 'abduzeedo'].includes(platform) ? 'rss' : 'api',
    frequency_hours: Number(data.get('frequency_hours')),
    config: platform === 'x' ? { max_results: 10, fetch_thread: true } : { max_results: 12 },
  };
  try {
    await api('/api/sources', { method: 'POST', body: JSON.stringify(payload) });
    $('#source-dialog').close();
    form.reset();
    await Promise.all([loadSources(), loadSummary()]);
    toast('采集源已保存');
  } catch (error) {
    toast(error.message, true);
  }
}

function bindEvents() {
  $('#login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    $('#login-error').textContent = '';
    try {
      await api('/api/session', {
        method: 'POST',
        body: JSON.stringify({ password: $('#login-password').value }),
      });
      $('#login-password').value = '';
      showApp();
      await initializeApp();
    } catch (error) {
      $('#login-error').textContent = error.message;
    }
  });

  $('#logout-button').addEventListener('click', async () => {
    await api('/api/session', { method: 'DELETE' });
    showLogin();
  });
  $$('.nav-item').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
  $$('.segmented [data-status]').forEach((button) => button.addEventListener('click', async () => {
    state.candidateStatus = button.dataset.status;
    $$('.segmented [data-status]').forEach((item) => item.classList.toggle('is-active', item === button));
    await loadCandidates();
  }));
  $('#candidate-search').addEventListener('input', debounce(loadCandidates));
  $('#published-search').addEventListener('input', debounce(loadPublished));
  $('#show-hidden').addEventListener('change', loadPublished);
  $('#collect-button').addEventListener('click', collectNow);
  $('#publish-button').addEventListener('click', publishSelected);
  $('#import-button').addEventListener('click', () => $('#import-dialog').showModal());
  $('#add-source-button').addEventListener('click', () => $('#source-dialog').showModal());
  $$('[data-dialog-close]').forEach((button) => button.addEventListener('click', () => {
    document.getElementById(button.dataset.dialogClose)?.close();
  }));
  $('#import-form').addEventListener('submit', submitImport);
  $('#source-form').addEventListener('submit', submitSource);
  $('#drawer-close').addEventListener('click', closeEditor);
  $('#drawer-backdrop').addEventListener('click', closeEditor);
  $('#editor-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try { await saveEditor(); } catch (error) { toast(error.message, true); }
  });
  $('#editor-hide').addEventListener('click', async () => {
    try { await toggleEditorHidden(); } catch (error) { toast(error.message, true); }
  });
  $('#editor-approve').addEventListener('click', async () => {
    try { await approveEditor(); } catch (error) { toast(error.message, true); }
  });
  $('#editor-delete').addEventListener('click', async () => {
    try { await deleteEditor(); } catch (error) { toast(error.message, true); }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && document.body.classList.contains('drawer-open')) closeEditor();
  });
}

async function initializeApp() {
  await Promise.all([loadCategories(), loadSummary()]);
  await switchView(state.view);
}

async function boot() {
  bindEvents();
  try {
    await api('/api/me');
    showApp();
    await initializeApp();
  } catch (error) {
    showLogin();
  }
}

boot();
