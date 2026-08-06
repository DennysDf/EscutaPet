(() => {
  const root = document.querySelector('[data-verification-status]');
  if (!root) return;
  const token = root.dataset.token;
  const copy = root.querySelector('[data-status-copy]');
  const finish = root.querySelector('[data-finish-button]');
  const required = root.dataset.required === '1';
  if (!copy) return;
  const order = ['pending', 'sent', 'delivered', 'read', 'confirmed'];
  const labels = {
    pending: 'Preparando o envio da confirmação…',
    sent: 'Mensagem enviada. Peça para a pessoa tocar em “Confirmar meu WhatsApp”.',
    delivered: 'Mensagem entregue ao WhatsApp informado.',
    read: 'Mensagem lida. Aguardando o clique de confirmação.',
    confirmed: 'WhatsApp confirmado com sucesso.',
    failed: 'Falha no envio. Confira o número e tente novamente.'
  };
  let stopped = false;

  const render = (state, nextUrl) => {
    const normalized = state && state.startsWith('confirmed') ? 'confirmed' : state;
    copy.textContent = labels[normalized] || labels.pending;
    const current = order.indexOf(normalized);
    root.querySelectorAll('[data-state]').forEach((item) => {
      const idx = order.indexOf(item.dataset.state);
      item.classList.toggle('active', current >= idx && current >= 0);
    });
    if (nextUrl) {
      stopped = true;
      copy.textContent = 'Confirmação concluída. Continuando para a próxima pesquisa…';
      window.location.href = nextUrl;
    }
    if (normalized === 'confirmed') { finish.classList.add('ready'); finish.classList.remove('is-hidden'); }
    else if (required) finish.classList.add('is-hidden');
  };

  const poll = async () => {
    if (stopped) return;
    try {
      const response = await fetch(`/coleta/sessao/${token}/status`, { cache: 'no-store' });
      const data = await response.json();
      render(data.verification_status || data.confirmation_status, data.next_url);
    } catch (_) {
      copy.textContent = 'Sem conexão para atualizar o status. Tentaremos novamente.';
    }
    if (!stopped) setTimeout(poll, 2500);
  };
  poll();
})();
