(() => {
  const root = document.querySelector('[data-conversation-list]');
  if (!root) return;

  const list = root.querySelector('[data-conversation-items]');
  const more = root.querySelector('[data-load-conversations]');
  const search = root.querySelector('[data-conversation-search]');
  const refresh = root.querySelector('[data-refresh-conversations]');
  const filters = root.querySelector('[data-conversation-filters]');
  const sprite = '/static/icons/icons.svg?v=3.6.0';
  let before = root.dataset.nextBefore || null;
  let query = '';
  let status = 'all';
  let unread = false;
  let loading = false;

  const icon = name => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'icon'); svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', `${sprite}#${name}`); svg.append(use); return svg;
  };
  const smartTime = value => {
    if (!value) return '';
    const date = new Date(value); if (Number.isNaN(date.getTime())) return '';
    const now = new Date(); const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
    if (date.toDateString() === now.toDateString()) return date.toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'});
    if (date.toDateString() === yesterday.toDateString()) return 'Ontem';
    return date.toLocaleDateString('pt-BR', date.getFullYear() === now.getFullYear() ? {day:'2-digit', month:'2-digit'} : {day:'2-digit', month:'2-digit', year:'2-digit'});
  };
  root.querySelectorAll('[data-smart-time]').forEach(node => { node.textContent = smartTime(node.dateTime); });

  const empty = (title = 'Nenhuma conversa', copy = 'As mensagens recebidas aparecerão aqui.') => {
    const box = document.createElement('div'); box.className = 'conversation-list-empty'; box.dataset.listEmpty = '';
    box.append(icon('message-circle'));
    const strong = document.createElement('strong'); strong.textContent = title;
    const span = document.createElement('span'); span.textContent = copy; box.append(strong, span); list.append(box);
  };
  const add = item => {
    if (list.querySelector(`[data-conversation-id="${item.id}"]`)) return;
    list.querySelector('[data-list-empty]')?.remove();
    const card = document.createElement('a'); card.href = `/conversas/${item.id}`;
    card.className = `conversation-card${item.unread ? ' has-unread' : ''}`;
    card.dataset.conversationId = item.id; card.dataset.status = item.status || '';
    const avatar = document.createElement('span'); avatar.className = 'lead-avatar'; avatar.textContent = (item.name || '?').slice(0, 1).toUpperCase();
    const copy = document.createElement('span'); copy.className = 'conversation-copy';
    const title = document.createElement('span'); title.className = 'conversation-title';
    const name = document.createElement('strong'); name.textContent = item.name || 'Contato WhatsApp'; title.append(name);
    if (item.pinned) { const pin = document.createElement('i'); pin.title = 'Conversa fixada'; pin.append(icon('pin')); title.append(pin); }
    const preview = document.createElement('span'); preview.className = 'conversation-preview'; preview.textContent = item.preview || 'Sem mensagens.';
    const meta = document.createElement('span'); meta.className = 'conversation-meta';
    const state = document.createElement('small'); state.textContent = item.status_label || 'Em atendimento'; meta.append(state);
    if (item.assigned_name) { const assigned = document.createElement('small'); assigned.textContent = item.assigned_name.split(' ')[0]; meta.append(assigned); }
    copy.append(title, preview, meta);
    const tail = document.createElement('span'); tail.className = 'conversation-tail';
    const time = document.createElement('time'); time.dateTime = item.when || ''; time.textContent = smartTime(item.when); tail.append(time);
    if (item.unread) { const badge = document.createElement('b'); badge.className = 'unread'; badge.textContent = item.unread > 99 ? '99+' : item.unread; tail.append(badge); }
    card.append(avatar, copy, tail); list.append(card);
  };
  const params = (cursor = '') => {
    const value = new URLSearchParams({limit:'40'});
    if (cursor) value.set('before', cursor); if (query) value.set('q', query);
    if (status !== 'all') value.set('status', status); if (unread) value.set('unread', 'true');
    return value;
  };
  const load = async (reset = false) => {
    if (loading || (!before && !reset)) return;
    loading = true; more.disabled = true; more.classList.add('loading'); more.hidden = false;
    const cursor = reset ? '' : before;
    if (reset) { list.classList.add('is-loading'); list.setAttribute('aria-busy', 'true'); }
    try {
      const response = await fetch(`/api/conversas?${params(cursor)}`, {headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error('Não foi possível carregar as conversas.');
      const data = await response.json(); if (reset) list.textContent = '';
      data.items.forEach(add); before = data.next_before || null;
      if (!list.querySelector('.conversation-card')) empty(query || status !== 'all' || unread ? 'Nenhum resultado' : 'Nenhuma conversa', query ? 'Tente outro nome, número ou termo.' : 'Altere os filtros ou aguarde uma nova mensagem.');
      more.hidden = !before; more.lastChild.textContent = before ? ' Carregar mais' : ' Todas as conversas foram carregadas';
    } catch (error) {
      if (reset) { list.textContent = ''; empty('Falha ao carregar', 'Confira a conexão e tente novamente.'); }
      more.hidden = false; more.lastChild.textContent = ' Tentar novamente';
    } finally {
      loading = false; more.disabled = false; more.classList.remove('loading'); list.classList.remove('is-loading'); list.removeAttribute('aria-busy');
    }
  };
  const reset = () => { before = null; load(true); };
  more.addEventListener('click', () => load()); refresh?.addEventListener('click', reset);
  filters?.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button) return;
    filters.querySelectorAll('button').forEach(item => item.classList.toggle('active', item === button));
    status = button.dataset.status || 'all'; unread = button.dataset.unread === 'true'; reset();
  });
  let timer; search?.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { query = search.value.trim(); reset(); }, 280); });
  list.addEventListener('scroll', () => {
    if (before && list.scrollHeight - list.scrollTop - list.clientHeight < 220) load();
  }, {passive:true});
})();
