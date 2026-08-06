(() => {
  const root = document.querySelector('[data-chat]'); if (!root) return;
  const id = root.dataset.conversationId;
  const history = root.querySelector('[data-chat-history]');
  const form = root.querySelector('[data-chat-form]');
  const text = form.querySelector('[data-composer-text]');
  const file = form.querySelector('[data-attachment]');
  const send = form.querySelector('[data-send]');
  const recordButton = form.querySelector('[data-record]');
  const loader = history.querySelector('[data-history-loader]');
  const historyStart = history.querySelector('[data-history-start]');
  const scrollLatest = history.querySelector('[data-scroll-latest]');
  const toastNode = root.querySelector('[data-chat-toast]');
  const emojiDialog = root.querySelector('[data-emoji-dialog]');
  const mediaDialog = root.querySelector('[data-media-dialog]');
  const replyId = form.querySelector('[data-reply-id]');
  const replyPreview = form.querySelector('[data-reply-preview]');
  const attachmentPreview = form.querySelector('[data-attachment-preview]');
  const recordingPreview = form.querySelector('[data-recording-preview]');
  const sprite = '/static/icons/icons.svg?v=3.6.0';
  const statusIcons = {queued:'◷', pending:'◷', sending:'◷', sent:'✓', delivered:'✓✓', read:'✓✓', played:'✓✓', failed:'!'};
  const statusLabels = {queued:'Na fila de envio', pending:'Pendente', sending:'Enviando', sent:'Enviada', delivered:'Entregue', read:'Lida', played:'Reproduzida', failed:'Falha no envio'};
  let first = Number(window.CHAT_BOOT?.firstId) || 0;
  let last = Number(window.CHAT_BOOT?.lastId) || 0;
  let hasMore = window.CHAT_BOOT?.hasMore === true || root.dataset.initialHasMore === 'true';
  let since = new Date().toISOString();
  let loading = false; let unseen = 0; let reactionMessage = null;
  let recorder = null; let recorderStream = null; let chunks = []; let recordingTimer = null; let recordingStarted = 0;
  let attachmentUrl = null; let draftTimer = null; let zoomed = false;
  const MAX_DOM_MESSAGES = 240; const WINDOW_STEP = 40;
  let olderDetached = []; let newerDetached = [];

  const csrf = () => document.cookie.split('; ').find(value => value.startsWith('escutapet_v2_csrf='))?.split('=').slice(1).join('=') || '';
  const svg = name => `<svg class="icon" aria-hidden="true" focusable="false"><use href="${sprite}#${name}"></use></svg>`;
  const nearBottom = () => history.scrollHeight - history.scrollTop - history.clientHeight < 170;
  const showToast = (message, kind = 'success') => {
    toastNode.textContent = message; toastNode.className = `chat-toast ${kind}`; toastNode.hidden = false;
    clearTimeout(showToast.timer); showToast.timer = setTimeout(() => { toastNode.hidden = true; }, 4200);
  };
  const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, options); let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok || data.ok === false) throw new Error(data.error || 'Não foi possível concluir esta ação.');
    return data;
  };
  const closeDialog = dialog => {
    if (!dialog?.open) return; dialog.close(); dialog.querySelectorAll('video,audio').forEach(media => media.pause());
  };
  const appendFormatted = (node, value) => {
    node.textContent = ''; const pattern = /(\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~|`[^`\n]+`)/g;
    String(value || '').split('\n').forEach((line, index) => {
      if (index) node.append(document.createElement('br')); let cursor = 0;
      for (const match of line.matchAll(pattern)) {
        if (match.index > cursor) node.append(document.createTextNode(line.slice(cursor, match.index)));
        const token = match[0]; const element = document.createElement(token.startsWith('*') ? 'strong' : token.startsWith('_') ? 'em' : token.startsWith('~') ? 'del' : 'code');
        element.textContent = token.slice(1, -1); node.append(element); cursor = match.index + token.length;
      }
      if (cursor < line.length) node.append(document.createTextNode(line.slice(cursor)));
    });
  };
  document.querySelectorAll('[data-rich-text]').forEach(node => appendFormatted(node, node.textContent));

  const mediaNode = media => {
    if (!media.ready) {
      const pending = document.createElement('div'); pending.className = 'media-pending'; pending.dataset.mediaPending = '';
      pending.innerHTML = `${svg('download')}<span><strong></strong><small></small></span>`;
      pending.querySelector('strong').textContent = ['pending','downloading'].includes(media.download_status) ? 'Baixando mídia…' : 'Mídia indisponível';
      pending.querySelector('small').textContent = media.name || 'Aguarde a preparação do arquivo.'; return pending;
    }
    const mime = media.mime || '';
    if (media.type === 'audio') { const audio = document.createElement('audio'); audio.controls = true; audio.preload = 'metadata'; audio.src = media.url; return audio; }
    const button = document.createElement('button'); button.type = 'button'; button.dataset.mediaPreview = '';
    Object.assign(button.dataset, {mediaUrl:media.url, mediaName:media.name || 'Arquivo', mediaMime:mime || 'application/octet-stream'});
    if (media.type === 'image') {
      button.className = 'media-thumb image-thumb'; const image = document.createElement('img'); image.src = media.url; image.alt = media.name || 'Imagem'; image.loading = 'lazy'; button.append(image); return button;
    }
    if (media.type === 'video') {
      button.className = 'media-thumb video-thumb'; const video = document.createElement('video'); video.src = media.url; video.preload = 'metadata';
      const marker = document.createElement('i'); marker.innerHTML = svg('play'); button.append(video, marker); return button;
    }
    button.className = 'attachment-card'; button.innerHTML = `${svg('file-text')}<span><strong></strong><small>Visualizar ou baixar</small></span>`;
    button.querySelector('strong').textContent = media.name || 'Arquivo'; return button;
  };
  const buildReactions = (reactions = []) => {
    const group = document.createElement('div'); group.className = 'message-reactions';
    reactions.forEach(reaction => { const button = document.createElement('button'); button.type = 'button'; button.dataset.reactEmoji = reaction.emoji; button.dataset.mine = String(Boolean(reaction.mine)); button.classList.toggle('mine', Boolean(reaction.mine)); button.append(document.createTextNode(reaction.emoji)); if (reaction.count > 1) { const count = document.createElement('span'); count.textContent = reaction.count; button.append(count); } group.append(button); });
    return group;
  };
  const bubble = message => {
    const article = document.createElement('article'); article.className = `chat-message ${message.direction}`;
    Object.assign(article.dataset, {messageId:message.id, externalId:message.external_id || '', occurredAt:message.occurred_at});
    article.innerHTML = `<div class="message-actions"><button class="icon-button" type="button" data-reply title="Responder" aria-label="Responder a esta mensagem">${svg('reply')}</button><button class="icon-button" type="button" data-react title="Reagir" aria-label="Reagir a esta mensagem">${svg('smile-plus')}</button></div><div class="message-bubble"></div>`;
    if (!message.external_id) article.querySelector('[data-react]').disabled = true;
    const body = article.querySelector('.message-bubble');
    if (message.quoted_content) { const quote = document.createElement('button'); quote.type = 'button'; quote.className = 'quoted-message'; quote.dataset.quotedMessage = ''; quote.textContent = message.quoted_content; body.append(quote); }
    if (message.media) {
      body.append(mediaNode(message.media));
      if (message.media.type === 'audio' && (message.media.transcript || ['pending','processing','failed'].includes(message.media.transcription_status))) {
        const transcript = document.createElement('div'); transcript.className = `audio-transcript ${message.media.transcription_status || ''}`;
        if (message.media.transcript) { const title = document.createElement('strong'); title.textContent = 'Transcrição'; const copy = document.createElement('p'); copy.textContent = message.media.transcript; transcript.append(title, copy); }
        else transcript.textContent = message.media.transcription_status === 'failed' ? 'Não foi possível transcrever este áudio.' : message.media.transcription_status === 'processing' ? 'Transcrevendo áudio…' : 'Áudio aguardando transcrição…';
        body.append(transcript);
      }
    }
    if (message.content && !(message.content.startsWith('[') && message.media)) { const copy = document.createElement('p'); copy.dataset.richText = ''; appendFormatted(copy, message.content); body.append(copy); }
    if (message.reactions?.length) body.append(buildReactions(message.reactions));
    if (message.status === 'failed') { const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'message-retry'; retry.dataset.retryMessage = ''; retry.innerHTML = `${svg('rotate')} Tentar novamente`; body.append(retry); }
    const footer = document.createElement('footer'); if (message.sender) { const sender = document.createElement('span'); sender.textContent = message.sender; footer.append(sender); }
    const time = document.createElement('time'); time.textContent = new Date(message.occurred_at).toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'});
    const state = document.createElement('i'); state.dataset.messageStatus = ''; state.className = `message-status ${message.status || ''}`; state.textContent = statusIcons[message.status] || ''; state.title = message.error || statusLabels[message.status] || '';
    footer.append(time, state); body.append(footer); return article;
  };
  const rebuildDates = () => {
    history.querySelectorAll('.chat-date').forEach(node => node.remove()); let previous = '';
    history.querySelectorAll('.chat-message').forEach(article => {
      const date = new Date(article.dataset.occurredAt || 0); const key = date.toLocaleDateString('pt-BR'); if (key === previous) return; previous = key;
      const today = new Date(); const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
      const label = date.toDateString() === today.toDateString() ? 'Hoje' : date.toDateString() === yesterday.toDateString() ? 'Ontem' : date.toLocaleDateString('pt-BR', {day:'2-digit', month:'long', year:date.getFullYear() !== today.getFullYear() ? 'numeric' : undefined});
      const node = document.createElement('div'); node.className = 'chat-date'; node.textContent = label; article.before(node);
    });
  };
  const insert = (message, older = false) => {
    if (history.querySelector(`[data-message-id="${message.id}"]`) || olderDetached.some(node => node.dataset.messageId === String(message.id)) || newerDetached.some(node => node.dataset.messageId === String(message.id))) return false;
    const node = bubble(message); const firstMessage = history.querySelector('.chat-message');
    if (!older && newerDetached.length) newerDetached.push(node);
    else older && firstMessage ? history.insertBefore(node, firstMessage) : history.insertBefore(node, scrollLatest);
    first = first ? Math.min(first, message.id) : message.id; last = Math.max(last, message.id); return true;
  };
  const visibleMessages = () => [...history.querySelectorAll('.chat-message')];
  const trimEnd = () => {
    const rows = visibleMessages(); const excess = rows.length - MAX_DOM_MESSAGES; if (excess <= 0) return;
    const removed = rows.slice(-excess); removed.forEach(node => node.remove()); newerDetached = [...removed, ...newerDetached];
  };
  const trimStart = () => {
    const rows = visibleMessages(); const excess = rows.length - MAX_DOM_MESSAGES; if (excess <= 0) return;
    const removed = rows.slice(0, excess); removed.forEach(node => node.remove()); olderDetached.push(...removed);
  };
  const restoreOlder = () => {
    if (!olderDetached.length) return false;
    const oldHeight = history.scrollHeight; const current = history.querySelector('.chat-message'); const chunk = olderDetached.splice(-WINDOW_STEP);
    const fragment = document.createDocumentFragment(); chunk.forEach(node => fragment.append(node)); history.insertBefore(fragment, current || scrollLatest); trimEnd(); rebuildDates(); history.scrollTop += history.scrollHeight - oldHeight; return true;
  };
  const restoreNewer = (all = false) => {
    if (!newerDetached.length) return false;
    do { const chunk = newerDetached.splice(0, WINDOW_STEP); const fragment = document.createDocumentFragment(); chunk.forEach(node => fragment.append(node)); history.insertBefore(fragment, scrollLatest); trimStart(); } while (all && newerDetached.length);
    rebuildDates(); return true;
  };
  const earlier = async () => {
    if (loading) return; if (restoreOlder()) return; if (!hasMore || !first) return; loading = true; loader.hidden = false;
    const oldHeight = history.scrollHeight; const oldTop = history.scrollTop;
    try {
      const data = await fetchJson(`/api/conversas/${id}/mensagens?before=${first}&limit=40`);
      data.items.forEach(item => insert(item, true)); hasMore = Boolean(data.has_more); historyStart.hidden = hasMore; trimEnd(); rebuildDates();
      history.scrollTop = oldTop + history.scrollHeight - oldHeight;
    } catch (error) { showToast(error.message, 'error'); }
    finally { loading = false; loader.hidden = !hasMore; }
  };
  new IntersectionObserver(entries => { if (entries[0]?.isIntersecting) earlier(); }, {root:history, rootMargin:'180px 0px 0px'}).observe(loader);
  history.addEventListener('scroll', () => { if (history.scrollTop < 200) earlier(); if (nearBottom()) { if (newerDetached.length) restoreNewer(); else { unseen = 0; scrollLatest.hidden = true; } } }, {passive:true});
  scrollLatest.addEventListener('click', () => { restoreNewer(true); history.scrollTo({top:history.scrollHeight, behavior:'smooth'}); unseen = 0; scrollLatest.hidden = true; });

  const updateComposer = () => { const hasContent = Boolean(text.value.trim() || file.files.length); send.hidden = !hasContent; recordButton.hidden = hasContent; };
  const setReply = article => { replyId.value = article.dataset.messageId; replyPreview.hidden = false; replyPreview.querySelector('[data-reply-copy]').textContent = article.querySelector('[data-rich-text]')?.textContent || 'Mídia ou anexo'; text.focus(); saveDraft(); };
  const clearReply = () => { replyId.value = ''; replyPreview.hidden = true; saveDraft(); };
  form.querySelector('[data-cancel-reply]').addEventListener('click', clearReply);

  const emojiCatalog = {
    recent:[], rostos:['😀','😃','😄','😁','😆','😅','😂','🤣','😊','😇','🙂','🙃','😉','😍','🥰','😘','🤔','🫡','😐','🙄','😢','😭','😮','😴','😬','😱','😳','😠','😡','🤬','😷','🤒','🤕','🤢','🤮'],
    gestos:['👍','👎','👌','🤌','✌️','🤞','🤟','🤘','🤙','👈','👉','👆','👇','☝️','✋','🤚','🖐️','👋','🤝','👏','🙌','🫶','🙏','✍️','💪','👀','🫂'],
    coracoes:['❤️','🧡','💛','💚','💙','💜','🖤','🤍','🤎','💔','❤️‍🔥','❤️‍🩹','💕','💞','💓','💗','💖','💘','💯','✨','⭐','🌟'],
    animais:['🐶','🐱','🐭','🐹','🐰','🦊','🐻','🐼','🐨','🐯','🦁','🐮','🐷','🐸','🐵','🐔','🐧','🐦','🦄','🐝','🦋','🐢','🐍','🐙','🦀','🐠','🐟','🐬','🐾','🌿','🌻','🌞','🌈'],
    objetos:['🎉','🎊','🎁','🏆','🥇','⚽','🎯','🎵','🎶','📱','💻','📷','💡','📌','📍','📅','✅','❌','⚠️','❓','❗','🔔','📣','💬','🩺','💊','🏥','🏠','🚗','☕']
  };
  try { emojiCatalog.recent = JSON.parse(localStorage.getItem('escutapet_recent_emojis') || '[]').slice(0, 18); } catch (_) {}
  let emojiCategory = emojiCatalog.recent.length ? 'recent' : 'rostos';
  const rememberEmoji = emoji => { emojiCatalog.recent = [emoji, ...emojiCatalog.recent.filter(item => item !== emoji)].slice(0, 18); localStorage.setItem('escutapet_recent_emojis', JSON.stringify(emojiCatalog.recent)); };
  const renderEmojis = (query = '') => {
    const categoryIcons = {recent:'clock', rostos:'smile', gestos:'activity', coracoes:'star', animais:'users', objetos:'sparkles'};
    const nav = emojiDialog.querySelector('[data-emoji-categories]'); nav.textContent = '';
    Object.keys(emojiCatalog).filter(key => key !== 'recent' || emojiCatalog.recent.length).forEach(key => { const button = document.createElement('button'); button.type = 'button'; button.dataset.category = key; button.className = key === emojiCategory ? 'active' : ''; button.innerHTML = svg(categoryIcons[key] || 'smile'); button.title = key; nav.append(button); });
    const grid = emojiDialog.querySelector('[data-emoji-grid]'); grid.textContent = ''; const term = query.normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase();
    const aliases = {feliz:'rostos', sorriso:'rostos', triste:'rostos', rosto:'rostos', mao:'gestos', gesto:'gestos', obrigado:'gestos', amor:'coracoes', coracao:'coracoes', pet:'animais', cachorro:'animais', gato:'animais', animal:'animais', festa:'objetos', aviso:'objetos', saude:'objetos'};
    const matchedCategory = Object.entries(aliases).find(([word]) => word.includes(term) || term.includes(word))?.[1];
    const entries = term ? (matchedCategory ? emojiCatalog[matchedCategory] : Object.values(emojiCatalog).flat().filter((item, index, all) => all.indexOf(item) === index)) : emojiCatalog[emojiCategory];
    entries.forEach(emoji => { const button = document.createElement('button'); button.type = 'button'; button.textContent = emoji; button.dataset.emojiValue = emoji; grid.append(button); });
  };
  const openEmoji = (mode = 'compose', article = null) => { reactionMessage = mode === 'reaction' ? article : null; emojiDialog.querySelector('[data-emoji-mode-label]').textContent = reactionMessage ? 'Reagir à mensagem' : 'Inserir na mensagem'; emojiDialog.querySelector('[data-emoji-search]').value = ''; renderEmojis(); emojiDialog.showModal(); };
  emojiDialog.querySelector('[data-emoji-categories]').addEventListener('click', event => { const button = event.target.closest('[data-category]'); if (!button) return; emojiCategory = button.dataset.category; renderEmojis(); });
  emojiDialog.querySelector('[data-emoji-search]').addEventListener('input', event => renderEmojis(event.target.value));
  emojiDialog.querySelector('[data-emoji-grid]').addEventListener('click', async event => {
    const button = event.target.closest('[data-emoji-value]'); if (!button) return; const emoji = button.dataset.emojiValue; rememberEmoji(emoji);
    if (!reactionMessage) { text.setRangeText(emoji, text.selectionStart, text.selectionEnd, 'end'); text.dispatchEvent(new Event('input')); text.focus(); closeDialog(emojiDialog); return; }
    try {
      const data = new FormData(); data.set('message_id', reactionMessage.dataset.messageId); data.set('emoji', emoji);
      await fetchJson(`/conversas/${id}/reagir`, {method:'POST', body:data, headers:{'X-CSRF-Token':csrf(), 'X-Requested-With':'fetch'}});
      let group = reactionMessage.querySelector('.message-reactions'); const items = [];
      group?.querySelectorAll('[data-react-emoji]').forEach(item => { let count = Number(item.querySelector('span')?.textContent || 1); if (item.dataset.mine === 'true') count -= 1; if (count > 0) items.push({emoji:item.dataset.reactEmoji, count, mine:false}); });
      const same = items.find(item => item.emoji === emoji); if (same) { same.count += 1; same.mine = true; } else items.push({emoji, count:1, mine:true});
      const fresh = buildReactions(items); if (group) group.replaceWith(fresh); else reactionMessage.querySelector('.message-bubble footer').before(fresh); closeDialog(emojiDialog);
    } catch (error) { showToast(error.message, 'error'); }
  });
  form.querySelector('[data-emoji]').addEventListener('click', () => openEmoji());

  const removeMineReaction = async (article, button) => {
    try {
      const data = new FormData(); data.set('message_id', article.dataset.messageId); data.set('emoji', button.dataset.reactEmoji); data.set('remove', 'true');
      await fetchJson(`/conversas/${id}/reagir`, {method:'POST', body:data, headers:{'X-CSRF-Token':csrf(), 'X-Requested-With':'fetch'}});
      const count = Number(button.querySelector('span')?.textContent || 1) - 1;
      if (count <= 0) button.remove(); else { button.classList.remove('mine'); button.dataset.mine = 'false'; let span = button.querySelector('span'); if (!span) { span = document.createElement('span'); button.append(span); } span.textContent = count; }
      if (!article.querySelector('.message-reactions')?.children.length) article.querySelector('.message-reactions')?.remove();
    } catch (error) { showToast(error.message, 'error'); }
  };
  const openMedia = trigger => {
    const url = trigger.dataset.mediaUrl; const mime = trigger.dataset.mediaMime || ''; const name = trigger.dataset.mediaName || 'Arquivo'; zoomed = false;
    const viewer = mediaDialog.querySelector('[data-media-viewer]'); viewer.textContent = ''; viewer.classList.remove('zoomed');
    mediaDialog.querySelector('[data-media-title]').textContent = name; mediaDialog.querySelector('[data-media-subtitle]').textContent = mime || 'Arquivo recebido';
    const download = mediaDialog.querySelector('[data-media-download]'); download.href = url; download.download = name; let content;
    if (mime.startsWith('image/')) { content = document.createElement('img'); content.src = url; content.alt = name; }
    else if (mime.startsWith('video/')) { content = document.createElement('video'); content.src = url; content.controls = true; content.autoplay = true; }
    else if (mime === 'application/pdf' || name.toLowerCase().endsWith('.pdf')) { content = document.createElement('iframe'); content.src = `${url}#toolbar=1&navpanes=0`; content.title = name; }
    else { content = document.createElement('div'); content.className = 'unsupported-preview'; content.innerHTML = `${svg('file-text')}<strong></strong><p>Baixe o arquivo para visualizá-lo.</p>`; content.querySelector('strong').textContent = name; }
    viewer.append(content); mediaDialog.querySelector('[data-media-zoom]').hidden = !mime.startsWith('image/'); mediaDialog.showModal();
  };
  mediaDialog.querySelector('[data-media-zoom]').addEventListener('click', () => { zoomed = !zoomed; mediaDialog.querySelector('[data-media-viewer]').classList.toggle('zoomed', zoomed); });
  history.addEventListener('click', event => {
    const media = event.target.closest('[data-media-preview]'); if (media) return openMedia(media);
    const article = event.target.closest('[data-message-id]'); if (!article) return;
    if (event.target.closest('[data-reply]')) return setReply(article);
    if (event.target.closest('[data-react]')) return openEmoji('reaction', article);
    const existing = event.target.closest('[data-react-emoji]'); if (existing) return existing.dataset.mine === 'true' ? removeMineReaction(article, existing) : openEmoji('reaction', article);
    if (event.target.closest('[data-retry-message]')) retryMessage(article);
  });
  root.querySelectorAll('[data-dialog-close]').forEach(button => button.addEventListener('click', () => closeDialog(button.closest('dialog'))));
  root.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) closeDialog(dialog); }));

  form.querySelectorAll('[data-format]').forEach(button => button.addEventListener('click', () => { const wrapper = {bold:'*', italic:'_', strike:'~', code:'`'}[button.dataset.format]; const start = text.selectionStart; const end = text.selectionEnd; const selected = text.value.slice(start, end) || 'texto'; text.setRangeText(`${wrapper}${selected}${wrapper}`, start, end, 'select'); text.dispatchEvent(new Event('input')); text.focus(); }));
  const resizeComposer = () => { text.style.height = 'auto'; text.style.height = `${Math.min(132, Math.max(42, text.scrollHeight))}px`; };
  text.addEventListener('input', () => { resizeComposer(); updateComposer(); clearTimeout(draftTimer); draftTimer = setTimeout(saveDraft, 650); });
  text.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); } });
  const clearAttachment = () => { file.value = ''; attachmentPreview.hidden = true; attachmentPreview.querySelector('[data-attachment-visual]').textContent = ''; if (attachmentUrl) URL.revokeObjectURL(attachmentUrl); attachmentUrl = null; updateComposer(); };
  form.querySelector('[data-clear-attachment]').addEventListener('click', clearAttachment);
  const previewAttachment = selected => {
    clearAttachment(); if (!selected) return; const transfer = new DataTransfer(); transfer.items.add(selected); file.files = transfer.files;
    attachmentUrl = URL.createObjectURL(selected); attachmentPreview.hidden = false; attachmentPreview.querySelector('[data-attachment-title]').textContent = selected.name;
    const size = selected.size >= 1048576 ? `${(selected.size / 1048576).toFixed(1)} MB` : `${Math.max(1, selected.size / 1024).toFixed(0)} KB`;
    attachmentPreview.querySelector('[data-attachment-meta]').textContent = `${selected.type || 'arquivo'} · ${size}`; const visual = attachmentPreview.querySelector('[data-attachment-visual]');
    if (selected.type.startsWith('image/')) { const image = document.createElement('img'); image.src = attachmentUrl; image.alt = ''; visual.append(image); }
    else visual.innerHTML = svg(selected.type.startsWith('audio/') ? 'mic' : selected.type === 'application/pdf' ? 'file-text' : 'paperclip'); updateComposer();
  };
  file.addEventListener('change', () => { const selected = file.files[0]; if (selected) previewAttachment(selected); });
  form.addEventListener('dragover', event => { event.preventDefault(); form.classList.add('dragging'); });
  form.addEventListener('dragleave', () => form.classList.remove('dragging'));
  form.addEventListener('drop', event => { event.preventDefault(); form.classList.remove('dragging'); if (event.dataTransfer.files[0]) previewAttachment(event.dataTransfer.files[0]); });
  form.addEventListener('paste', event => { const selected = [...event.clipboardData.files][0]; if (selected) previewAttachment(selected); });

  const finishRecording = (cancel = false) => {
    if (recorder?.state === 'recording') { recorder.datasetCancel = String(cancel); recorder.stop(); }
    clearInterval(recordingTimer); recordingTimer = null; recordingPreview.hidden = true;
  };
  recordButton.addEventListener('click', async () => {
    try {
      recorderStream = await navigator.mediaDevices.getUserMedia({audio:true}); chunks = []; recorder = new MediaRecorder(recorderStream);
      recorder.ondataavailable = item => { if (item.data.size) chunks.push(item.data); };
      recorder.onstop = () => { recorderStream?.getTracks().forEach(track => track.stop()); if (recorder.datasetCancel !== 'true' && chunks.length) { const mime = recorder.mimeType || 'audio/webm'; previewAttachment(new File([new Blob(chunks, {type:mime})], `audio-${Date.now()}.webm`, {type:mime})); } recorder = null; recorderStream = null; updateComposer(); };
      recorder.start(); recordingStarted = Date.now(); recordingPreview.hidden = false; recordButton.hidden = true;
      recordingTimer = setInterval(() => { const seconds = Math.floor((Date.now() - recordingStarted) / 1000); recordingPreview.querySelector('[data-recording-time]').textContent = `${String(Math.floor(seconds / 60)).padStart(2,'0')}:${String(seconds % 60).padStart(2,'0')}`; }, 250);
    } catch (_) { showToast('Abra por HTTPS e autorize o microfone para gravar áudio.', 'error'); }
  });
  form.querySelector('[data-stop-recording]').addEventListener('click', () => finishRecording(false)); form.querySelector('[data-cancel-recording]').addEventListener('click', () => finishRecording(true));

  const deleteDraft = () => fetch(`/api/conversas/${id}/rascunho`, {method:'DELETE', headers:{'X-CSRF-Token':csrf()}}).catch(() => {});
  function saveDraft() { return fetch(`/api/conversas/${id}/rascunho`, {method:'PUT', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()}, body:JSON.stringify({content:text.value, reply_to_message_id:replyId.value || null})}).catch(() => {}); }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (!text.value.trim() && !file.files.length) return; send.disabled = true; send.classList.add('sending');
    try {
      const result = await fetchJson(form.action, {method:'POST', body:new FormData(form), headers:{'X-CSRF-Token':csrf(), 'X-Requested-With':'fetch', Accept:'application/json'}});
      text.value = ''; resizeComposer(); clearAttachment(); clearReply(); await deleteDraft(); updateComposer();
      showToast(result.status === 'queued' ? 'Mensagem adicionada à fila.' : 'Mensagem enviada.'); setTimeout(poll, 250);
    } catch (error) { showToast(error.message, 'error'); }
    finally { send.disabled = false; send.classList.remove('sending'); }
  });
  const retryMessage = async article => {
    const button = article.querySelector('[data-retry-message]'); button.disabled = true;
    try { await fetchJson(`/conversas/${id}/mensagens/${article.dataset.messageId}/tentar-novamente`, {method:'POST', headers:{'X-CSRF-Token':csrf(), 'X-Requested-With':'fetch'}}); button.remove(); updateStatus(article, {status:'queued'}); showToast('Mensagem recolocada na fila.'); }
    catch (error) { button.disabled = false; showToast(error.message, 'error'); }
  };
  const updateStatus = (article, item) => { const state = article?.querySelector('[data-message-status]'); if (!state) return; state.className = `message-status ${item.status || ''}`; state.textContent = statusIcons[item.status] || ''; state.title = item.error || statusLabels[item.status] || ''; };
  const updateChanged = item => {
    const article = history.querySelector(`[data-message-id="${item.id}"]`) || [...olderDetached, ...newerDetached].find(node => node.dataset.messageId === String(item.id)); updateStatus(article, item);
    if (article && item.media?.transcript) { let box = article.querySelector('.audio-transcript'); if (!box) { box = document.createElement('div'); article.querySelector('.message-bubble audio')?.after(box); } box.className = 'audio-transcript completed'; box.innerHTML = '<strong>Transcrição</strong><p></p>'; box.querySelector('p').textContent = item.media.transcript; }
  };
  const poll = async () => {
    try {
      const data = await fetchJson(`/api/conversas/${id}/atualizacoes?after=${last}&since=${encodeURIComponent(since)}`); const wasNear = nearBottom(); let inserted = 0;
      data.new.forEach(item => { if (insert(item)) inserted += 1; }); data.changed.forEach(updateChanged); rebuildDates(); since = data.server_time || new Date().toISOString();
      if (wasNear && inserted) history.scrollTop = history.scrollHeight; else if (inserted) { unseen += inserted; scrollLatest.hidden = false; scrollLatest.querySelector('[data-new-count]').textContent = unseen; }
    } catch (_) {} finally { setTimeout(poll, document.hidden ? 14000 : 4500); }
  };

  const action = async (name, extra = {}) => {
    const data = new FormData(); data.set('action', name); Object.entries(extra).forEach(([key,value]) => data.set(key, value));
    const result = await fetchJson(`/conversas/${id}/acao`, {method:'POST', body:data, headers:{'X-CSRF-Token':csrf(), 'X-Requested-With':'fetch'}});
    root.querySelector('[data-conversation-status-label]').textContent = result.status_label;
    const card = document.querySelector(`[data-conversation-id="${id}"]`); if (card) card.dataset.status = result.status;
    return result;
  };
  root.querySelectorAll('[data-conversation-action]').forEach(button => button.addEventListener('click', async () => { try { const result = await action(button.dataset.conversationAction); if (['pin','unpin'].includes(button.dataset.conversationAction)) { button.dataset.conversationAction = result.pinned ? 'unpin' : 'pin'; button.querySelector('span').textContent = result.pinned ? 'Desafixar conversa' : 'Fixar conversa'; } if (['open','close'].includes(button.dataset.conversationAction)) { button.dataset.conversationAction = result.status === 'closed' ? 'open' : 'close'; button.querySelector('span').textContent = result.status === 'closed' ? 'Reabrir conversa' : 'Encerrar conversa'; } button.closest('details')?.removeAttribute('open'); showToast('Conversa atualizada.'); } catch (error) { showToast(error.message, 'error'); } }));
  root.querySelector('[data-conversation-assignee]')?.addEventListener('change', async event => { try { await action('assign', {assigned_user_id:event.target.value}); showToast('Responsável atualizado.'); } catch (error) { showToast(error.message, 'error'); } });
  const setContext = open => { root.classList.toggle('context-open', open); const panel = root.querySelector('[data-chat-context]'); panel.setAttribute('aria-hidden', String(!open)); const backdrop = root.querySelector('.context-backdrop'); backdrop.hidden = !open; };
  root.querySelectorAll('[data-context-toggle]').forEach(button => button.addEventListener('click', () => setContext(!root.classList.contains('context-open')))); root.querySelectorAll('[data-context-close]').forEach(button => button.addEventListener('click', () => setContext(false)));
  const searchBar = root.querySelector('[data-chat-search-bar]'); const searchInput = root.querySelector('[data-chat-search]');
  root.querySelector('[data-chat-search-toggle]').addEventListener('click', () => { searchBar.hidden = false; searchInput.focus(); }); root.querySelector('[data-chat-search-close]').addEventListener('click', () => { searchBar.hidden = true; searchInput.value = ''; searchInput.dispatchEvent(new Event('input')); });
  searchInput.addEventListener('input', () => { const term = searchInput.value.trim().toLocaleLowerCase('pt-BR'); let count = 0; history.querySelectorAll('.chat-message').forEach(article => { const found = !term || article.textContent.toLocaleLowerCase('pt-BR').includes(term); article.classList.toggle('search-hidden', !found); if (term && found) count += 1; }); root.querySelector('[data-chat-search-count]').textContent = term ? `${count} resultado${count === 1 ? '' : 's'}` : ''; rebuildDates(); });

  fetch(`/api/conversas/${id}/rascunho`).then(response => response.json()).then(data => { if (data.content) { text.value = data.content; resizeComposer(); updateComposer(); } if (data.reply_to_message_id) { const article = history.querySelector(`[data-message-id="${data.reply_to_message_id}"]`); if (article) setReply(article); else replyId.value = data.reply_to_message_id; } }).catch(() => {});
  rebuildDates(); history.scrollTop = history.scrollHeight; loader.hidden = !hasMore; historyStart.hidden = hasMore; updateComposer(); poll();
})();
