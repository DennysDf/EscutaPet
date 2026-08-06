(() => {
  const form = document.querySelector('[data-editor-recovery]');
  const adapter = window.EditorRecoveryAdapter;
  if (!form || !adapter?.capture || !adapter?.restore) return;

  const entityType = form.dataset.editorEntity;
  const entityKey = form.dataset.editorKey;
  const baseRevision = Number(form.dataset.editorRevision || 0);
  const serverUpdatedAt = form.dataset.editorUpdatedAt || '';
  const storageKey = `escutapet:editor-draft:v1:${entityType}:${entityKey}`;
  const apiUrl = `/api/editor-drafts/${encodeURIComponent(entityType)}/${encodeURIComponent(entityKey)}`;
  const autosaveStatus = form.querySelector('[data-autosave-status]');
  const csrf = () => document.cookie.split('; ').find(item => item.startsWith('escutapet_v2_csrf='))?.split('=').slice(1).join('=') || '';
  let timer = null, saving = false, queued = false, restored = false, changed = false;

  const setStatus = (text, state = '') => { if (autosaveStatus) { autosaveStatus.textContent = text; autosaveStatus.dataset.state = state; } };
  const safeJson = value => { try { return JSON.parse(value); } catch { return null; } };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const localDraft = () => safeJson(localStorage.getItem(storageKey) || '');
  const snapshot = () => ({
    schema: 1,
    entity_type: entityType,
    entity_key: entityKey,
    base_revision: baseRevision,
    server_updated_at: serverUpdatedAt,
    saved_at: new Date().toISOString(),
    data: adapter.capture(),
  });
  const persistLocal = value => { try { localStorage.setItem(storageKey, JSON.stringify(value)); return true; } catch { setStatus('Sem espaço para cópia local', 'error'); return false; } };

  async function persistServer(value) {
    if (saving) { queued = true; return; }
    saving = true; setStatus('Salvando rascunho…', 'saving');
    try {
      const response = await fetch(apiUrl, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()}, body:JSON.stringify(value), credentials:'same-origin'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      setStatus(result.conflict ? 'Rascunho salvo · servidor mudou' : 'Rascunho salvo automaticamente', result.conflict ? 'warning' : 'saved');
    } catch {
      setStatus('Cópia local salva · servidor indisponível', 'warning');
    } finally {
      saving = false;
      if (queued) { queued = false; persistServer(snapshot()); }
    }
  }

  function scheduleSave() {
    if (!changed) return;
    clearTimeout(timer);
    timer = setTimeout(() => { const value = snapshot(); if (persistLocal(value)) persistServer(value); }, 1400);
  }
  const changedEvent = () => { changed = true; scheduleSave(); };
  form.addEventListener('input', changedEvent);
  form.addEventListener('change', changedEvent);
  form.addEventListener('editor:changed', changedEvent);

  function recoveryDialog(candidate, origin) {
    const dialog = document.createElement('dialog');
    dialog.className = 'editor-recovery-dialog';
    dialog.innerHTML = `<div class="recovery-dialog-head"><div><span class="eyebrow">RECUPERAÇÃO DE RASCUNHO</span><h2>Há trabalho mais recente</h2></div><button class="icon-button" type="button" data-recovery-close aria-label="Fechar">×</button></div><div class="recovery-dialog-body"><p data-recovery-message></p><div class="recovery-comparison" data-recovery-comparison hidden></div></div><footer><button class="btn danger ghost" type="button" data-recovery-discard>Descartar</button><button class="btn ghost" type="button" data-recovery-compare>Comparar</button><button class="btn primary" type="button" data-recovery-restore>Restaurar</button></footer>`;
    document.body.append(dialog);
    const when = new Date(candidate.saved_at || candidate.client_updated_at || candidate.server_saved_at || Date.now());
    dialog.querySelector('[data-recovery-message]').textContent = `Foi encontrado um rascunho não enviado de ${when.toLocaleDateString('pt-BR')} às ${when.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}.`;
    dialog.querySelector('[data-recovery-close]').addEventListener('click', () => dialog.close());
    dialog.querySelector('[data-recovery-compare]').addEventListener('click', () => {
      const target = dialog.querySelector('[data-recovery-comparison]');
      const current = adapter.summary ? adapter.summary(adapter.capture()) : {origem:'Servidor'};
      const recovered = adapter.summary ? adapter.summary(candidate.data) : {origem:'Rascunho'};
      const keys = [...new Set([...Object.keys(current || {}), ...Object.keys(recovered || {})])];
      target.innerHTML = `<div><strong>Versão aberta</strong>${keys.map(key => `<span><b>${esc(key)}</b>${esc(current?.[key] ?? '—')}</span>`).join('')}</div><div><strong>Rascunho recuperável</strong>${keys.map(key => `<span><b>${esc(key)}</b>${esc(recovered?.[key] ?? '—')}</span>`).join('')}</div>`;
      target.hidden = false;
    });
    dialog.querySelector('[data-recovery-restore]').addEventListener('click', async () => {
      adapter.restore(candidate.data); restored = true; changed = true;
      const source = form.querySelector('[name="editor_recovery_source"]'); if (source) source.value = origin;
      setStatus('Rascunho restaurado · revise e salve', 'warning');
      dialog.close();
      try { await fetch(`${apiUrl}/restore`, {method:'POST', headers:{'X-CSRF-Token':csrf()}, credentials:'same-origin'}); } catch {}
      form.dispatchEvent(new CustomEvent('editor:changed', {bubbles:true}));
    });
    dialog.querySelector('[data-recovery-discard]').addEventListener('click', async () => {
      localStorage.removeItem(storageKey); dialog.close();
      try { await fetch(apiUrl, {method:'DELETE', headers:{'X-CSRF-Token':csrf()}, credentials:'same-origin'}); } catch {}
      setStatus('Rascunho descartado', '');
    });
    dialog.addEventListener('close', () => setTimeout(() => dialog.remove(), 0));
    dialog.showModal();
  }

  async function discoverDraft() {
    const local = localDraft();
    let remote = null;
    try { const response = await fetch(apiUrl, {credentials:'same-origin'}); if (response.ok) remote = (await response.json()).draft; } catch {}
    const remotePayload = remote?.payload?.data ? remote.payload : null;
    const candidates = [local && {value:local, origin:'local'}, remotePayload && {value:remotePayload, origin:'server'}].filter(Boolean).sort((a,b) => new Date(b.value.saved_at || 0) - new Date(a.value.saved_at || 0));
    const chosen = candidates[0]; if (!chosen) return;
    const newerRevision = Number(chosen.value.base_revision || 0) >= baseRevision;
    const newerTime = !serverUpdatedAt || new Date(chosen.value.saved_at || 0) > new Date(serverUpdatedAt);
    if (newerRevision && newerTime) recoveryDialog(chosen.value, chosen.origin);
    else if (Number(chosen.value.base_revision || 0) < baseRevision) { localStorage.removeItem(storageKey); try { await fetch(apiUrl,{method:'DELETE',headers:{'X-CSRF-Token':csrf()},credentials:'same-origin'}); } catch {} }
  }

  function conflictDialog(conflict) {
    if (!conflict) return;
    const dialog = document.createElement('dialog'); dialog.className = 'editor-recovery-dialog conflict-dialog';
    dialog.innerHTML = `<div class="recovery-dialog-head"><div><span class="eyebrow">CONFLITO DE EDIÇÃO</span><h2>O item mudou em outra sessão</h2></div></div><div class="recovery-dialog-body"><p data-conflict-message></p><div class="recovery-comparison" data-conflict-comparison hidden></div></div><footer><a class="btn ghost" href="${location.pathname}">Recarregar servidor</a><button class="btn ghost" type="button" data-conflict-compare>Comparar</button><button class="btn primary" type="button" data-conflict-duplicate>Duplicar como rascunho</button></footer>`;
    const editorName = conflict.last_user || conflict.last_editor || 'outro usuário';
    dialog.querySelector('[data-conflict-message]').textContent = `${editorName} salvou a revisão ${conflict.current_revision}. Suas alterações continuam visíveis, mas não substituíram o servidor.`;
    dialog.querySelector('[data-conflict-compare]').addEventListener('click', () => { const target=dialog.querySelector('[data-conflict-comparison]'); target.innerHTML=`<div><strong>Sua edição</strong><span><b>Revisão carregada</b>${esc(conflict.submitted_revision)}</span></div><div><strong>Servidor</strong><span><b>Revisão atual</b>${esc(conflict.current_revision)}</span><span><b>Último editor</b>${esc(editorName)}</span></div>`; target.hidden=false; });
    dialog.querySelector('[data-conflict-duplicate]').addEventListener('click', () => {
      adapter.prepareDuplicate?.();
      form.action = entityType === 'flow' ? '/fluxos/novo' : '/questionarios/novo';
      const revision = form.querySelector('[name="base_revision"]'); if (revision) revision.value = '0';
      const token = form.querySelector('[name="submission_token"]'); if (token) token.value = crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
      if (form.elements.status) form.elements.status.value = 'draft';
      dialog.close();
      const draftButton = form.querySelector('button[name="editor_action"][value="draft"]');
      form.requestSubmit(draftButton || form.querySelector('[type="submit"]'));
    });
    document.body.append(dialog); dialog.showModal();
  }

  form.addEventListener('editor:submitting', () => {
    clearTimeout(timer); localStorage.removeItem(storageKey);
    fetch(apiUrl, {method:'DELETE', headers:{'X-CSRF-Token':csrf()}, credentials:'same-origin', keepalive:true}).catch(() => {});
  });
  window.addEventListener('online', () => { if (localDraft()) persistServer(localDraft()); });
  setInterval(() => { if (document.visibilityState === 'visible' && !saving) scheduleSave(); }, 20000);
  requestAnimationFrame(() => {
    const conflict = safeJson(document.querySelector('#editor-conflict-data')?.textContent || 'null');
    if (conflict && Object.keys(conflict).length) conflictDialog(conflict); else discoverDraft();
  });
})();
