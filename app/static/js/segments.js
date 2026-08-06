(() => {
  const open = (modal) => {
    if (!modal) return;
    modal.hidden = false;
    document.body.classList.add('modal-open');
    modal.querySelector('input,select,button')?.focus();
  };
  const close = (modal) => {
    if (!modal) return;
    modal.hidden = true;
    document.body.classList.remove('modal-open');
  };

  const segmentModal = document.querySelector('[data-segment-modal]');
  const automationModal = document.querySelector('[data-automation-modal]');
  document.querySelectorAll('[data-open-segment-modal]').forEach(button => button.addEventListener('click', () => open(segmentModal)));
  document.querySelectorAll('[data-open-automation]').forEach(button => button.addEventListener('click', () => open(automationModal)));
  document.querySelectorAll('[data-close-modal]').forEach(button => button.addEventListener('click', () => close(button.closest('.modal-backdrop'))));
  document.querySelectorAll('.modal-backdrop').forEach(modal => modal.addEventListener('mousedown', event => {
    if (event.target === modal) close(modal);
  }));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') document.querySelectorAll('.modal-backdrop:not([hidden])').forEach(close);
  });

  const rules = document.querySelector('[data-segment-rules]');
  const template = document.querySelector('[data-rule-template]');
  const bindRemove = (root) => root.querySelectorAll('[data-remove-rule]').forEach(button => {
    button.onclick = () => button.closest('.segment-rule-row')?.remove();
  });
  if (rules && template) {
    bindRemove(rules);
    rules.querySelector('[data-add-rule]')?.addEventListener('click', () => {
      rules.querySelector('[data-rule-list]').append(template.content.cloneNode(true));
      bindRemove(rules);
    });
    if (!rules.querySelector('.segment-rule-row')) rules.querySelector('[data-add-rule]')?.click();
  }

  const form = document.querySelector('[data-automation-form]');
  if (!form) return;

  const campaignOptions = form.querySelector('[data-campaign-options]');
  const entryOptions = form.querySelector('[data-entry-options]');
  const schedule = form.querySelector('[data-schedule-type]');
  const selectedTrigger = () => form.querySelector('input[name="trigger_type"]:checked')?.value || 'campaign';

  const syncSchedule = () => {
    const campaign = selectedTrigger() === 'campaign';
    if (campaignOptions) campaignOptions.hidden = !campaign;
    if (entryOptions) entryOptions.hidden = campaign;
    if (schedule) {
      const timed = schedule.value !== 'now';
      form.querySelector('[data-scheduled-at]').hidden = !campaign || !timed;
      form.querySelector('[data-recurrence]').hidden = !campaign || schedule.value !== 'recurring';
    }
    const hybrid = selectedTrigger() === 'hybrid';
    form.querySelector('[data-entry-recurrence]').hidden = !hybrid;
    form.querySelector('[data-max-cycles]').hidden = !hybrid;
  };
  form.querySelectorAll('input[name="trigger_type"]').forEach(input => input.addEventListener('change', syncSchedule));
  schedule?.addEventListener('change', syncSchedule);
  syncSchedule();

  const selectedQuestionnaires = () => [...form.querySelectorAll('input[name="questionnaire_ids"]:checked')];
  form.addEventListener('submit', event => {
    if (!selectedQuestionnaires().length) {
      event.preventDefault();
      const box = form.querySelector('[data-audience-preview]');
      box.querySelector('strong').textContent = 'Selecione ao menos uma pesquisa antes de ativar';
      form.querySelector('[data-questionnaire-list]')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  });

  form.querySelector('[data-preview-audience]')?.addEventListener('click', async () => {
    const box = form.querySelector('[data-audience-preview]');
    const selected = selectedQuestionnaires();
    if (!selected.length) {
      box.querySelector('strong').textContent = 'Selecione ao menos uma pesquisa primeiro';
      return;
    }
    box.classList.add('loading');
    box.querySelector('strong').textContent = 'Calculando...';
    try {
      const response = await fetch(form.dataset.previewUrl, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      const data = await response.json();
      const s = data.stats;
      box.querySelector('strong').textContent = `${s.eligible} elegível(is) de ${s.segment} no segmento · ${data.selected_questionnaires} pesquisa(s)`;
      box.querySelector('span').textContent = `${s.without_consent} sem consentimento · ${s.without_whatsapp} sem WhatsApp · ${s.active_execution || 0} com pesquisa ativa · ${s.cooldown || 0} em intervalo · ${s.already_received} já receberam · ${s.unconfirmed} não confirmados · ${s.outside_sample || 0} fora da amostra`;
    } catch (_) {
      box.querySelector('strong').textContent = 'Não foi possível calcular agora';
    } finally {
      box.classList.remove('loading');
    }
  });
})();
