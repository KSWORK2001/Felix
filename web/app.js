let state = { tasks: [], events: [] };

const el = (id) => document.getElementById(id);

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode.apply(null, chunk);
  }

  return btoa(binary);
}

async function openSettingsModal() {
  setStatus('Loading settings...');
  let s;
  try {
    s = await pywebview.api.get_settings();
  } catch (e) {
    setStatus(String(e));
    return;
  }
  setStatus('');

  const providerSelect = document.createElement('select');
  for (const p of ['openai', 'gemma']) {
    const opt = document.createElement('option');
    opt.value = p;
    opt.textContent = p === 'openai' ? 'OpenAI (GPT)' : 'Gemma (Local)';
    if (s.provider === p) opt.selected = true;
    providerSelect.appendChild(opt);
  }

  const gemmaInput = document.createElement('input');
  gemmaInput.value = s.gemma_model_id || 'google/gemma-3-4b-it';

  const openaiModelInput = document.createElement('input');
  openaiModelInput.value = s.openai_model || 'gpt-4o-mini';

  const openaiKeyInput = document.createElement('input');
  openaiKeyInput.type = 'password';
  openaiKeyInput.placeholder = s.openai_api_key_present ? 'stored' : '';

  const googleSecretsInput = document.createElement('input');
  googleSecretsInput.value = s.google_client_secrets_path || '';

  const googleRow = document.createElement('div');
  googleRow.className = 'row';

  const connectBtn = document.createElement('button');
  connectBtn.className = 'btn';
  connectBtn.type = 'button';
  connectBtn.textContent = 'Connect Google';
  connectBtn.onclick = async () => {
    setStatus('Connecting to Google...');
    try {
      await pywebview.api.update_settings({ google_client_secrets_path: googleSecretsInput.value });
      await pywebview.api.google_connect();
      setStatus('Google connected');
      setTimeout(() => setStatus(''), 1200);
    } catch (e) {
      setStatus(String(e));
    }
  };

  const syncBtn = document.createElement('button');
  syncBtn.className = 'btn btn-primary';
  syncBtn.type = 'button';
  syncBtn.textContent = 'Sync Google';
  syncBtn.onclick = async () => {
    setStatus('Syncing Google Calendar...');
    try {
      await pywebview.api.update_settings({ google_client_secrets_path: googleSecretsInput.value });
      const res = await pywebview.api.google_sync();
      state = res.state || state;
      renderTasks();
      renderEvents();
      setStatus(`Google synced: ${res.synced}`);
      setTimeout(() => setStatus(''), 1500);
    } catch (e) {
      setStatus(String(e));
    }
  };

  googleRow.appendChild(connectBtn);
  googleRow.appendChild(syncBtn);

  const icsRow = document.createElement('div');
  icsRow.className = 'row';

  const icsUrlInput = document.createElement('input');
  icsUrlInput.value = s.ics_url || '';

  const icsUrlRow = document.createElement('div');
  icsUrlRow.className = 'row';

  const syncIcsUrlBtn = document.createElement('button');
  syncIcsUrlBtn.className = 'btn btn-primary';
  syncIcsUrlBtn.type = 'button';
  syncIcsUrlBtn.textContent = 'Sync ICS URL';
  syncIcsUrlBtn.onclick = async () => {
    setStatus('Syncing ICS URL...');
    try {
      await pywebview.api.update_settings({ ics_url: icsUrlInput.value });
      const res = await pywebview.api.ics_url_sync();
      state = res.state || state;
      renderTasks();
      renderEvents();
      setStatus(`ICS URL synced: ${res.imported_events} events, ${res.imported_tasks} tasks`);
      setTimeout(() => setStatus(''), 1500);
    } catch (e) {
      setStatus(String(e));
    }
  };

  icsUrlRow.appendChild(syncIcsUrlBtn);

  const exportIcsBtn = document.createElement('button');
  exportIcsBtn.className = 'btn';
  exportIcsBtn.type = 'button';
  exportIcsBtn.textContent = 'Export ICS';
  exportIcsBtn.onclick = async () => {
    setStatus('Exporting ICS...');
    try {
      const res = await pywebview.api.export_ics();
      const bytes = Uint8Array.from(atob(res.ics_base64), c => c.charCodeAt(0));
      const blob = new Blob([bytes], { type: 'text/calendar' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = res.filename || 'calendar.ics';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus('ICS exported');
      setTimeout(() => setStatus(''), 1200);
    } catch (e) {
      setStatus(String(e));
    }
  };

  const importIcsBtn = document.createElement('button');
  importIcsBtn.className = 'btn btn-primary';
  importIcsBtn.type = 'button';
  importIcsBtn.textContent = 'Import ICS';

  const importInput = document.createElement('input');
  importInput.type = 'file';
  importInput.accept = '.ics,text/calendar';
  importInput.style.display = 'none';
  importInput.onchange = async (ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    setStatus('Importing ICS...');
    try {
      const ab = await file.arrayBuffer();
      const b64 = arrayBufferToBase64(ab);
      const res = await pywebview.api.import_ics(b64);
      state = res.state || state;
      renderTasks();
      renderEvents();
      setStatus(`ICS imported: ${res.imported_events} events, ${res.imported_tasks} tasks`);
      setTimeout(() => setStatus(''), 1500);
    } catch (e) {
      setStatus(String(e));
    } finally {
      ev.target.value = '';
    }
  };

  importIcsBtn.onclick = () => importInput.click();

  icsRow.appendChild(exportIcsBtn);
  icsRow.appendChild(importIcsBtn);
  icsRow.appendChild(importInput);

  const clearWrap = document.createElement('div');
  clearWrap.className = 'row';
  const clearCb = document.createElement('input');
  clearCb.type = 'checkbox';
  const clearLabel = document.createElement('div');
  clearLabel.textContent = 'Clear OpenAI key';
  clearWrap.appendChild(clearCb);
  clearWrap.appendChild(clearLabel);

  openModal('Settings', [
    field('Provider', providerSelect),
    field('Gemma model id', gemmaInput),
    field('OpenAI model', openaiModelInput),
    field('OpenAI key', openaiKeyInput),
    field('Google client secrets path', googleSecretsInput),
    googleRow,
    icsRow,
    field('ICS URL', icsUrlInput),
    icsUrlRow,
    clearWrap
  ], async () => {
    const patch = {
      provider: providerSelect.value,
      gemma_model_id: gemmaInput.value,
      openai_model: openaiModelInput.value,
      google_client_secrets_path: googleSecretsInput.value,
      ics_url: icsUrlInput.value,
    };
    if (clearCb.checked) {
      patch.openai_api_key = '';
    } else if (openaiKeyInput.value && openaiKeyInput.value.trim().length > 0) {
      patch.openai_api_key = openaiKeyInput.value.trim();
    }
    await pywebview.api.update_settings(patch);
    setStatus('Settings saved');
    setTimeout(() => setStatus(''), 1200);
  });
}

function setStatus(msg) {
  el('status').textContent = msg || '';
}

function addBubble(text, who) {
  const b = document.createElement('div');
  b.className = `bubble ${who}`;
  b.textContent = text;
  el('chatLog').appendChild(b);
  el('chatLog').scrollTop = el('chatLog').scrollHeight;
}

function escapeHtml(s) {
  return s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function renderTasks() {
  const root = el('tasksList');
  root.innerHTML = '';

  for (const t of state.tasks) {
    const item = document.createElement('div');
    item.className = 'item';

    const left = document.createElement('div');
    const title = document.createElement('div');
    title.textContent = `${t.completed ? '✓ ' : ''}${t.title} (id ${t.id})`;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = t.due_iso ? `Due: ${t.due_iso}` : 'No due date';
    left.appendChild(title);
    left.appendChild(meta);

    const right = document.createElement('div');
    right.className = 'row';

    const doneBtn = document.createElement('button');
    doneBtn.className = 'btn';
    doneBtn.textContent = t.completed ? 'Uncomplete' : 'Complete';
    doneBtn.onclick = async () => {
      await pywebview.api.update_task(t.id, null, null, !t.completed, null);
      await refresh();
    };

    const editBtn = document.createElement('button');
    editBtn.className = 'btn';
    editBtn.textContent = 'Edit';
    editBtn.onclick = () => openTaskModal(t);

    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-danger';
    delBtn.textContent = 'Delete';
    delBtn.onclick = async () => {
      await pywebview.api.delete_task(t.id);
      await refresh();
    };

    right.appendChild(doneBtn);
    right.appendChild(editBtn);
    right.appendChild(delBtn);

    item.appendChild(left);
    item.appendChild(right);
    root.appendChild(item);
  }
}

function renderEvents() {
  const root = el('eventsList');
  root.innerHTML = '';

  for (const e of state.events) {
    const item = document.createElement('div');
    item.className = 'item';

    const left = document.createElement('div');
    const title = document.createElement('div');
    title.textContent = `${e.title} (id ${e.id})`;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = `${e.start_iso} → ${e.end_iso}${e.source ? ` | ${e.source}` : ''}`;
    left.appendChild(title);
    left.appendChild(meta);

    const right = document.createElement('div');
    right.className = 'row';

    const editBtn = document.createElement('button');
    editBtn.className = 'btn';
    editBtn.textContent = 'Edit';
    editBtn.onclick = () => openEventModal(e);

    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-danger';
    delBtn.textContent = 'Delete';
    delBtn.onclick = async () => {
      await pywebview.api.delete_event(e.id);
      await refresh();
    };

    right.appendChild(editBtn);
    right.appendChild(delBtn);

    item.appendChild(left);
    item.appendChild(right);
    root.appendChild(item);
  }
}

async function refresh() {
  const res = await pywebview.api.get_state();
  state = res;
  renderTasks();
  renderEvents();
  renderDashboard();
}

function field(label, inputEl) {
  const wrap = document.createElement('div');
  wrap.className = 'field';
  const l = document.createElement('label');
  l.textContent = label;
  wrap.appendChild(l);
  wrap.appendChild(inputEl);
  return wrap;
}

function openModal(title, bodyEls, onSave) {
  el('modalTitle').textContent = title;
  const body = el('modalBody');
  body.innerHTML = '';
  for (const b of bodyEls) body.appendChild(b);

  const modal = el('modal');

  el('modalSave').onclick = async (ev) => {
    ev.preventDefault();
    await onSave();
    modal.close();
  };

  modal.showModal();
}

function openTaskModal(t) {
  const titleInput = document.createElement('input');
  titleInput.value = t?.title || '';

  const dueInput = document.createElement('input');
  dueInput.placeholder = 'ISO datetime (optional)';
  dueInput.value = t?.due_iso || '';

  const notesInput = document.createElement('textarea');
  notesInput.value = t?.notes || '';

  openModal(t ? `Edit task (id ${t.id})` : 'Add task', [
    field('Title', titleInput),
    field('Due (ISO)', dueInput),
    field('Notes', notesInput)
  ], async () => {
    if (t) {
      await pywebview.api.update_task(t.id, titleInput.value, dueInput.value || null, null, notesInput.value || null);
    } else {
      await pywebview.api.add_task(titleInput.value || 'New task', dueInput.value || null, notesInput.value || null);
    }
    await refresh();
  });
}

function openEventModal(e) {
  const titleInput = document.createElement('input');
  titleInput.value = e?.title || '';

  const startInput = document.createElement('input');
  startInput.placeholder = 'ISO datetime';
  startInput.value = e?.start_iso || '';

  const endInput = document.createElement('input');
  endInput.placeholder = 'ISO datetime';
  endInput.value = e?.end_iso || '';

  const locationInput = document.createElement('input');
  locationInput.value = e?.location || '';

  const notesInput = document.createElement('textarea');
  notesInput.value = e?.notes || '';

  openModal(e ? `Edit event (id ${e.id})` : 'Add event', [
    field('Title', titleInput),
    field('Start (ISO)', startInput),
    field('End (ISO)', endInput),
    field('Location', locationInput),
    field('Notes', notesInput),
  ], async () => {
    if (e) {
      await pywebview.api.update_event(e.id, titleInput.value, startInput.value, endInput.value, locationInput.value || null, notesInput.value || null);
    } else {
      await pywebview.api.add_event(titleInput.value || 'New event', startInput.value, endInput.value, locationInput.value || null, notesInput.value || null, 'manual');
    }
    await refresh();
  });
}

async function sendChat(text) {
  addBubble(text, 'user');
  setStatus('Thinking...');

  let res;
  try {
    res = await pywebview.api.chat(text);
  } catch (e) {
    setStatus(String(e));
    return;
  }

  addBubble(res.reply || '(no reply)', 'assistant');
  state = res.state || state;
  renderTasks();
  renderEvents();
  setStatus('');

  await speakText(res.reply || '');
}

async function importScreenshot(file) {
  setStatus('Importing screenshot...');
  const bytes = await file.arrayBuffer();
  const b64 = arrayBufferToBase64(bytes);

  let res;
  try {
    res = await pywebview.api.import_calendar_screenshot(b64);
  } catch (e) {
    setStatus(String(e));
    return;
  }

  state = res.state || state;
  renderTasks();
  renderEvents();
  setStatus(`Imported: ${res.parsed_count} parsed, ${res.created_event_ids?.length || 0} created`);
}

let mediaRecorder = null;
let audioChunks = [];
let currentAudio = null;
let isSpeaking = false;

async function speakText(text) {
  if (!text) return;

  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  if (isSpeaking && 'speechSynthesis' in window) {
    speechSynthesis.cancel();
  }

  try {
    const tts = await pywebview.api.tts(text);
    if (tts && tts.audio_wav_base64) {
      return new Promise((resolve) => {
        currentAudio = new Audio(`data:audio/wav;base64,${tts.audio_wav_base64}`);
        currentAudio.onended = () => {
          currentAudio = null;
          resolve();
        };
        currentAudio.onerror = () => {
          currentAudio = null;
          resolve();
        };
        currentAudio.play().catch(() => resolve());
      });
    }
  } catch (_) {}

  if ('speechSynthesis' in window) {
    return new Promise((resolve) => {
      isSpeaking = true;
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.0;
      utterance.pitch = 1.0;
      utterance.volume = 1.0;
      utterance.onend = () => {
        isSpeaking = false;
        resolve();
      };
      utterance.onerror = () => {
        isSpeaking = false;
        resolve();
      };
      speechSynthesis.speak(utterance);
    });
  }
}

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  audioChunks = [];

  const options = { mimeType: 'audio/webm' };
  try {
    mediaRecorder = new MediaRecorder(stream, options);
  } catch {
    mediaRecorder = new MediaRecorder(stream);
  }

  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) audioChunks.push(e.data);
  };

  mediaRecorder.onstop = async () => {
    const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
    const ab = await blob.arrayBuffer();
    const b64 = arrayBufferToBase64(ab);

    setStatus('Transcribing...');

    try {
      const res = await pywebview.api.transcribe_and_chat(b64, 'audio.webm');
      if (res.transcript) addBubble(`(transcript) ${res.transcript}`, 'user');
      addBubble(res.reply || '(no reply)', 'assistant');
      state = res.state || state;
      renderTasks();
      renderEvents();
      renderDashboard();
      setStatus('');
      await speakText(res.reply || '');
    } catch (e) {
      setStatus(String(e));
    }
  };

  mediaRecorder.start();
}

function stopRecording() {
  if (!mediaRecorder) return;
  mediaRecorder.stop();
}

function switchTab(tabName) {
  document.querySelectorAll('.nav-item[data-tab]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });

  document.querySelectorAll('.tab-content').forEach(tab => {
    tab.classList.toggle('active', tab.id === `tab-${tabName}`);
  });

  const titles = {
    dashboard: 'Dashboard',
    chat: 'Chat',
    calendar: 'Calendar',
    tasks: 'Tasks'
  };
  el('pageTitle').textContent = titles[tabName] || 'Dashboard';
}

function renderDashboard() {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
  const todayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).toISOString();

  const todayEvents = (state.events || []).filter(e => {
    return e.start_iso >= todayStart && e.start_iso < todayEnd;
  });

  const pendingTasks = (state.tasks || []).filter(t => !t.completed);

  el('todayEventsCount').textContent = todayEvents.length;
  el('pendingTasksCount').textContent = pendingTasks.length;

  const eventsRoot = el('todayEventsList');
  eventsRoot.innerHTML = '';
  if (todayEvents.length === 0) {
    eventsRoot.innerHTML = '<div class="dash-item">No events today</div>';
  } else {
    for (const e of todayEvents.slice(0, 5)) {
      const item = document.createElement('div');
      item.className = 'dash-item';
      item.innerHTML = `<div class="dash-item-title">${escapeHtml(e.title)}</div><div class="dash-item-meta">${e.start_iso}</div>`;
      eventsRoot.appendChild(item);
    }
  }

  const tasksRoot = el('pendingTasksList');
  tasksRoot.innerHTML = '';
  if (pendingTasks.length === 0) {
    tasksRoot.innerHTML = '<div class="dash-item">No pending tasks</div>';
  } else {
    for (const t of pendingTasks.slice(0, 5)) {
      const item = document.createElement('div');
      item.className = 'dash-item';
      item.innerHTML = `<div class="dash-item-title">${escapeHtml(t.title)}</div><div class="dash-item-meta">${t.due_iso || 'No due date'}</div>`;
      tasksRoot.appendChild(item);
    }
  }
}

window.addEventListener('pywebviewready', async () => {
  document.querySelectorAll('.nav-item[data-tab]').forEach(btn => {
    btn.onclick = () => switchTab(btn.dataset.tab);
  });

  el('settingsBtn').onclick = openSettingsModal;
  el('refreshBtn').onclick = refresh;
  el('addTaskBtn').onclick = () => openTaskModal(null);
  el('addEventBtn').onclick = () => openEventModal(null);
  el('dashAddTask').onclick = () => openTaskModal(null);
  el('dashAddEvent').onclick = () => openEventModal(null);

  el('sendBtn').onclick = async () => {
    const text = el('chatInput').value.trim();
    if (!text) return;
    el('chatInput').value = '';
    await sendChat(text);
  };

  el('chatInput').addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') {
      const text = el('chatInput').value.trim();
      if (!text) return;
      el('chatInput').value = '';
      await sendChat(text);
    }
  });

  el('screenshotInput').addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await importScreenshot(file);
    e.target.value = '';
  });

  el('recordBtn').onclick = async () => {
    try {
      await startRecording();
      el('recordBtn').disabled = true;
      el('stopBtn').disabled = false;
      setStatus('Recording...');
    } catch (e) {
      setStatus(String(e));
    }
  };

  el('stopBtn').onclick = () => {
    stopRecording();
    el('recordBtn').disabled = false;
    el('stopBtn').disabled = true;
  };

  await refresh();
  renderDashboard();
  addBubble('Hello! I\'m Felix, your AI secretary. Click Record to talk to me, or type your message below.', 'assistant');
  await speakText('Hello! I\'m Felix, your AI secretary. How can I help you today?');
});
