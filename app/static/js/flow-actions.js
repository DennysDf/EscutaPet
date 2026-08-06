(() => {
  const form = document.querySelector('#flow-editor-form');
  const list = document.querySelector('[data-flow-actions]');
  const count = document.querySelector('[data-actions-count]');
  const template = document.querySelector('#flow-action-template');
  if (!form || !list || !count || !template) return;

  const definitions = window.FLOW_QUESTIONNAIRES || {};
  const versions = window.FLOW_QUESTIONNAIRE_VERSIONS || {};
  const versionQuestions = window.FLOW_VERSION_QUESTIONS || {};
  const questionnaireMeta = window.FLOW_QUESTIONNAIRE_META || {};
  const registrationSummaries = window.FLOW_REGISTRATION_SUMMARIES || {};
  const status = form.querySelector('[data-save-status]');
  const drawer = form.querySelector('[data-action-drawer]');
  const backdrop = form.querySelector('[data-drawer-backdrop], .journey-drawer-backdrop');
  const live = form.querySelector('[data-reorder-live]') || document.querySelector('[data-reorder-live]');
  const cards = () => [...list.querySelectorAll('[data-flow-action]')];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const newKey = () => `action:new:${crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
  const field = (card, name) => card?.querySelector(`[data-action-field="${name}"]`);
  const proxy = name => drawer?.querySelector(`[data-proxy-field="${name}"]`);
  const valueOf = (card, name) => field(card, name)?.value || '';
  const keyFor = card => {
    if (!card.dataset.itemKey) card.dataset.itemKey = valueOf(card, 'id') ? `action:${valueOf(card, 'id')}` : newKey();
    if (field(card, 'item_key')) field(card, 'item_key').value = card.dataset.itemKey;
    return card.dataset.itemKey;
  };
  const cardName = (card, fallback = 'Ação') => valueOf(card, 'name').trim() || fallback;
  const announce = text => { if (live) live.textContent = text; };
  const setStatus = (text, state = '') => { if (status) { status.textContent = text; status.dataset.state = state; } };

  let serverErrors = [];
  try { serverErrors = JSON.parse(document.querySelector('#editor-errors')?.textContent || '[]'); } catch { serverErrors = []; }
  let dirty = form.dataset.serverError === '1';
  let submitting = false;
  let draggedCard = null;
  let editingCard = null;
  if (form.dataset.saved === '1') setStatus(`Salvo às ${new Date().toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'})}`, 'saved');
  else if (dirty) setStatus('Erro ao salvar', 'error');

  function markDirty() {
    if (submitting) return;
    dirty = true;
    setStatus('Alterações não salvas', 'dirty');
  }

  function activateTab(name, focus = false) {
    const button = form.querySelector(`[data-flow-tab="${name}"]`);
    const panel = form.querySelector(`[data-flow-panel="${name}"]`);
    if (!button || !panel) return;
    form.querySelectorAll('[data-flow-tab]').forEach(item => { const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-selected', String(active)); });
    form.querySelectorAll('[data-flow-panel]').forEach(item => { const active = item === panel; item.classList.toggle('active', active); item.hidden = !active; });
    if (focus) { panel.scrollIntoView({behavior:'smooth', block:'start'}); panel.querySelector('input:not([type="hidden"]),select,textarea,button')?.focus({preventScroll:true}); }
  }
  form.querySelector('[data-flow-tabs]')?.addEventListener('click', event => {
    const button = event.target.closest('[data-flow-tab]');
    if (button) activateTab(button.dataset.flowTab);
  });
  form.querySelector('[data-flow-tabs]')?.addEventListener('keydown', event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    const tabs = [...form.querySelectorAll('[data-flow-tab]')], current = tabs.indexOf(event.target.closest('[data-flow-tab]'));
    if (current < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    activateTab(tabs[next].dataset.flowTab); tabs[next].focus();
  });
  form.addEventListener('click', event => {
    if (event.target.closest('[data-next-flow-tab], [data-prev-flow-tab]')) {
      const active = [...form.querySelectorAll('[data-flow-tab]')].findIndex(item => item.classList.contains('active'));
      const direction = event.target.closest('[data-next-flow-tab]') ? 1 : -1;
      const target = form.querySelectorAll('[data-flow-tab]')[Math.max(0, Math.min(5, active + direction))];
      if (target) activateTab(target.dataset.flowTab, true);
    }
  });

  function updateScope() {
    const selected = new Set([...form.querySelectorAll('[data-city-choice]:checked')].map(item => item.value));
    form.querySelectorAll('[data-device-city]').forEach(item => { item.hidden = selected.size > 0 && !selected.has(item.dataset.deviceCity); });
  }
  form.querySelector('[data-city-scope]')?.addEventListener('change', updateScope);
  updateScope();

  function updateConditionalSettings() {
    form.querySelectorAll('[data-consent-detail]').forEach(block => {
      const toggle = form.querySelector(`[data-consent-toggle="${block.dataset.consentDetail}"]`);
      block.hidden = !toggle?.checked;
    });
    const verificationMode = form.querySelector('[name="phone_verification_mode"]:checked')?.value || 'none';
    const verificationSettings = form.querySelector('[data-verification-settings]');
    if (verificationSettings) verificationSettings.hidden = verificationMode === 'none';
  }
  form.querySelectorAll('[data-consent-toggle], [name="phone_verification_mode"]').forEach(item => item.addEventListener('change', updateConditionalSettings));
  updateConditionalSettings();

  const requiredBindings = [
    ['Responsável', [['lead.name','Nome'],['lead.phone','WhatsApp'],['lead.city','Cidade']]],
    ['Pet', [['pet.name','Nome'],['pet.species','Espécie']]],
    ['Atendimento', [['visit.service_type','Serviço'],['visit.reason','Motivo']]],
  ];
  function renderRegistrationSummary() {
    const select = form.querySelector('[data-registration-questionnaire]');
    const target = form.querySelector('[data-registration-summary]');
    const edit = form.querySelector('[data-edit-registration]');
    const id = select?.value || '';
    if (edit) edit.href = id ? `/questionarios/${id}/editar` : '/questionarios/novo?objective=registration';
    if (!target) return;
    if (!id) { target.innerHTML = '<div class="diagnostic-empty"><strong>Selecione um cadastro</strong><p>O resumo dos dados aparecerá aqui.</p></div>'; return; }
    const summary = registrationSummaries[String(id)] || {published:false, bindings:{}, duplicates:[], incompatible:[]};
    const missingRequired = ['lead.name','lead.phone'].filter(binding => !summary.bindings[binding]);
    const groups = requiredBindings.map(([title, items]) => `<section><h3>${title}</h3>${items.map(([binding,label]) => `<span class="binding-status ${summary.bindings[binding] ? 'ok' : 'missing'}"><b>${summary.bindings[binding] ? '✓' : '○'}</b>${esc(label)}</span>`).join('')}</section>`).join('');
    const alerts = [];
    if (!summary.published) alerts.push('Questionário sem versão publicada.');
    if (missingRequired.length) alerts.push('Binding obrigatório ausente: Nome completo ou WhatsApp.');
    if (summary.duplicates?.length) alerts.push(`Binding duplicado: ${summary.duplicates.join(', ')}.`);
    if (summary.incompatible?.length) alerts.push(`Pergunta incompatível: ${summary.incompatible.join(', ')}.`);
    target.innerHTML = `<div class="registration-binding-grid">${groups}</div>${alerts.length ? `<div class="registration-alerts">${alerts.map(item => `<p>⚠ ${esc(item)}</p>`).join('')}</div>` : '<div class="registration-ok">✓ Cadastro publicado e bindings principais válidos.</div>'}`;
  }
  form.querySelector('[data-registration-questionnaire]')?.addEventListener('change', renderRegistrationSummary);
  renderRegistrationSummary();

  function currentDependency(card) { const select = field(card, 'depends_on_key'); return select?.value || select?.dataset.selectedKey || ''; }
  function updateVersions(card) {
    const questionnaireId = valueOf(card, 'questionnaire_id');
    const select = field(card, 'fixed_version_id');
    if (!select) return;
    const preserve = select.value || select.dataset.selected || '';
    const items = versions[String(questionnaireId)] || [];
    select.innerHTML = '<option value="">Selecione</option>' + items.map(item => `<option value="${item.id}">Versão ${item.number}</option>`).join('');
    if (preserve && !items.some(item => String(item.id) === String(preserve))) select.insertAdjacentHTML('beforeend', `<option value="${esc(preserve)}">Versão indisponível — escolha novamente</option>`);
    select.value = preserve; select.dataset.selected = preserve;
  }
  function updateConditionQuestions(card) {
    const select = field(card, 'condition_question_id');
    if (!select) return;
    const parent = cards().find(item => keyFor(item) === currentDependency(card));
    const parentQuestionnaire = valueOf(parent, 'questionnaire_id');
    const parentVersion = valueOf(parent, 'fixed_version_id');
    const source = valueOf(parent, 'version_mode') === 'fixed' && parentVersion ? (versionQuestions[String(parentVersion)] || []) : (definitions[String(parentQuestionnaire)] || []);
    const preserve = select.value || select.dataset.selected || '';
    select.innerHTML = '<option value="">Qualquer conclusão</option>' + source.map(item => `<option value="${item.id}">${esc(item.text)}</option>`).join('');
    if (preserve && !source.some(item => String(item.id) === String(preserve))) select.insertAdjacentHTML('beforeend', `<option value="${esc(preserve)}">Pergunta incompatível — escolha novamente</option>`);
    select.value = preserve; select.dataset.selected = preserve;
  }
  function momentLabel(card) {
    const trigger = valueOf(card, 'trigger');
    const mode = valueOf(card, 'schedule_mode');
    const amount = Number(valueOf(card, 'delay_value') || 0);
    const units = {minutes: amount === 1 ? 'minuto' : 'minutos', hours: amount === 1 ? 'hora' : 'horas', days: amount === 1 ? 'dia' : 'dias'};
    if (mode === 'fixed_datetime') return valueOf(card, 'fixed_scheduled_at') ? `Em ${new Date(valueOf(card, 'fixed_scheduled_at')).toLocaleString('pt-BR', {dateStyle:'short', timeStyle:'short'})}` : 'Data fixa pendente';
    if (trigger === 'before_confirmation') return 'Antes da confirmação';
    if (trigger === 'after_confirmation' && amount === 0) return 'Após confirmação';
    if (trigger === 'after_action' && amount === 0) return 'Após ação anterior';
    if (mode === 'next_allowed') return `Próximo dia útil${amount ? ` + ${amount} dias` : ''}`;
    if (amount === 0) return 'Agora';
    return `${amount} ${units[valueOf(card, 'delay_unit')] || 'dias'} depois`;
  }
  function updateCard(card) {
    const meta = questionnaireMeta[String(valueOf(card, 'questionnaire_id'))] || {};
    card.querySelector('[data-action-name]').textContent = cardName(card);
    card.querySelector('[data-action-moment]').textContent = momentLabel(card);
    card.querySelector('[data-action-questionnaire]').textContent = meta.name || 'Selecione um questionário';
    card.querySelector('[data-action-channel]').textContent = ({whatsapp:'WhatsApp',screen_identified:'Tela identificada',screen_anonymous:'Tela anônima'})[valueOf(card, 'channel')] || 'Canal pendente';
    card.querySelector('[data-action-scope]').textContent = field(card, 'per_pet')?.checked ? 'Por pet' : 'Por coleta';
    let conditionCount = 0; try { conditionCount = JSON.parse(valueOf(card,'conditions_json') || '[]').length || 0; } catch (_) {}
    const randomGroup = valueOf(card,'random_group').trim();
    card.querySelector('[data-action-condition-summary]').textContent = [conditionCount ? `${conditionCount} condição${conditionCount === 1 ? '' : 'ões'}` : 'Sem condição', randomGroup ? `Sorteio: ${randomGroup}` : ''].filter(Boolean).join(' · ');
    const active = field(card, 'active')?.checked;
    const badge = card.querySelector('[data-action-status]');
    badge.textContent = active ? 'Ativa' : 'Pausada'; badge.className = `status ${active ? 'active' : 'paused'}`;
  }
  function reindex(preserved = null) {
    const all = cards();
    const dependencies = preserved || new Map(all.map(card => [keyFor(card), currentDependency(card)]));
    all.forEach((card, index) => {
      const key = keyFor(card);
      card.querySelector('[data-action-number]').textContent = String(index + 1);
      card.querySelectorAll('[data-action-field]').forEach(control => { control.name = `action_${index}_${control.dataset.actionField}`; });
      const dependency = field(card, 'depends_on_key');
      const keep = dependencies.get(key) || dependency?.dataset.selectedKey || '';
      const previous = all.slice(0, index);
      if (dependency) {
        dependency.innerHTML = '<option value="">Selecione a ação anterior</option>' + previous.map((parent, parentIndex) => `<option value="${esc(keyFor(parent))}">${parentIndex + 1}. ${esc(cardName(parent))}</option>`).join('');
        if (keep && !previous.some(parent => keyFor(parent) === keep)) dependency.insertAdjacentHTML('beforeend', `<option value="${esc(keep)}">⚠ Dependência inválida — corrija</option>`);
        dependency.value = keep; dependency.dataset.selectedKey = keep;
      }
      updateVersions(card); updateConditionQuestions(card); updateCard(card);
      card.querySelector('[data-action-drag-handle]')?.setAttribute('aria-label', `Reordenar ação ${index + 1}: ${cardName(card)}`);
      card.querySelector('[data-move-action-up]')?.toggleAttribute('disabled', index === 0);
      card.querySelector('[data-move-action-down]')?.toggleAttribute('disabled', index === all.length - 1);
    });
    count.value = String(all.length);
    const preCount = all.filter(card => valueOf(card,'trigger') === 'before_confirmation').length;
    const preLabel = form.querySelector('[data-pre-confirmation-count]'); if (preLabel) preLabel.textContent = `${preCount} ${preCount === 1 ? 'etapa configurada' : 'etapas configuradas'}`;
    const command = form.querySelector('[data-journey-command-summary]');
    if (command) command.textContent = `${all.length} ${all.length === 1 ? 'ação' : 'ações'} · ${form.elements.status.value === 'active' ? 'ativo' : form.elements.status.value === 'draft' ? 'rascunho' : 'pausado'}`;
  }

  function optionsFrom(select) { return [...select.options].map(option => ({value:option.value, text:option.textContent, disabled:option.disabled})); }
  function copyOptions(source, target, value) {
    target.innerHTML = optionsFrom(source).map(item => `<option value="${esc(item.value)}" ${item.disabled ? 'disabled' : ''}>${esc(item.text)}</option>`).join('');
    target.value = value || '';
  }
  function selectedParentQuestions() {
    const dependency = proxy('depends_on_key')?.value || '';
    const parent = cards().find(item => keyFor(item) === dependency);
    if (!parent) return [];
    const fixed = valueOf(parent, 'fixed_version_id');
    return valueOf(parent, 'version_mode') === 'fixed' && fixed ? (versionQuestions[String(fixed)] || []) : (definitions[String(valueOf(parent, 'questionnaire_id'))] || []);
  }
  function questionsForSource(sourceKey) {
    if (sourceKey === 'registration') return definitions[String(form.elements.registration_questionnaire_id?.value || '')] || [];
    const source = cards().find(item => keyFor(item) === sourceKey);
    if (!source) return [];
    const fixed = valueOf(source, 'fixed_version_id');
    return valueOf(source, 'version_mode') === 'fixed' && fixed ? (versionQuestions[String(fixed)] || []) : (definitions[String(valueOf(source, 'questionnaire_id'))] || []);
  }
  function conditionSources() {
    const position = Math.max(0, cards().indexOf(editingCard));
    return [{key:'registration', label:'Cadastro estruturado'}, ...cards().slice(0, position).filter(item => valueOf(item,'channel') !== 'screen_anonymous').map((item,index) => ({key:keyFor(item), label:`${index + 1}. ${cardName(item)}`}))];
  }
  function parseConditions(card) {
    try {
      const parsed = JSON.parse(valueOf(card, 'conditions_json') || '[]');
      if (Array.isArray(parsed) && parsed.length) return parsed;
    } catch (_) {}
    if (valueOf(card,'condition_question_id')) return [{source_key:currentDependency(card) || 'registration', question_id:valueOf(card,'condition_question_id'), operator:valueOf(card,'condition_operator') || 'answered', value:valueOf(card,'condition_value')}];
    return [];
  }
  function conditionChoices(question) {
    if (!question) return [];
    if (question.type === 'yes_no' && !(question.options || []).length) return [{label:'Sim',value:'sim'},{label:'Não',value:'nao'}];
    return Array.isArray(question.options) ? question.options : [];
  }
  function refreshConditionRow(row, preserve = {}) {
    const source = row.querySelector('[data-condition-source]');
    const questionSelect = row.querySelector('[data-condition-question]');
    const operator = row.querySelector('[data-condition-operator]');
    const valueSlot = row.querySelector('[data-condition-value-slot]');
    const questions = questionsForSource(source.value);
    const questionValue = String(preserve.question_id ?? questionSelect.value ?? '');
    questionSelect.innerHTML = '<option value="">Selecione a pergunta</option>' + questions.map(question => `<option value="${esc(question.id)}">${esc(question.text)}</option>`).join('');
    questionSelect.value = questionValue;
    if (questionValue && !questions.some(question => String(question.id) === questionValue)) questionSelect.insertAdjacentHTML('beforeend', `<option value="${esc(questionValue)}" selected>⚠ Pergunta indisponível</option>`);
    const question = questions.find(item => String(item.id) === String(questionSelect.value));
    const choices = conditionChoices(question);
    const expected = String(preserve.value ?? valueSlot.querySelector('[data-condition-value]')?.value ?? '');
    const noValue = ['answered','not_answered'].includes(operator.value);
    valueSlot.hidden = noValue;
    if (noValue) { valueSlot.innerHTML = '<input type="hidden" value="" data-condition-value>'; return; }
    if (choices.length && ['equals','not_equals'].includes(operator.value)) {
      valueSlot.innerHTML = `<select data-condition-value><option value="">Selecione a opção</option>${choices.map(option => `<option value="${esc(option.value ?? option.label ?? '')}">${esc(option.label ?? option.value ?? '')}</option>`).join('')}</select>`;
    } else {
      valueSlot.innerHTML = '<input data-condition-value placeholder="Valor esperado">';
    }
    valueSlot.querySelector('[data-condition-value]').value = expected;
  }
  function addConditionRow(condition = {}) {
    const target = drawer.querySelector('[data-condition-list]');
    if (!target || target.children.length >= 10) return;
    const sources = conditionSources();
    const row = document.createElement('div'); row.className = 'multi-condition-row'; row.dataset.conditionRow = '1';
    row.innerHTML = `<label>Origem<select data-condition-source>${sources.map(item => `<option value="${esc(item.key)}">${esc(item.label)}</option>`).join('')}</select></label><label>Pergunta<select data-condition-question></select></label><label>Comparação<select data-condition-operator><option value="equals">Igual a</option><option value="not_equals">Diferente de</option><option value="contains">Contém</option><option value="not_contains">Não contém</option><option value="gte">Maior ou igual</option><option value="lte">Menor ou igual</option><option value="answered">Foi respondida</option><option value="not_answered">Não foi respondida</option></select></label><label data-condition-value-slot>Valor<input data-condition-value></label><button class="icon-button danger" type="button" data-remove-condition aria-label="Remover condição">×</button>`;
    target.append(row);
    row.querySelector('[data-condition-source]').value = condition.source_key || 'registration';
    row.querySelector('[data-condition-operator]').value = condition.operator || 'equals';
    refreshConditionRow(row, condition);
    drawer.querySelector('[data-condition-empty]').hidden = true;
  }
  function renderConditions(card) {
    const target = drawer.querySelector('[data-condition-list]'); if (!target) return;
    target.replaceChildren();
    parseConditions(card).forEach(addConditionRow);
    drawer.querySelector('[data-condition-empty]').hidden = target.children.length > 0;
  }
  function serializedConditions() {
    return [...drawer.querySelectorAll('[data-condition-row]')].map(row => ({
      source_key: row.querySelector('[data-condition-source]').value,
      question_id: row.querySelector('[data-condition-question]').value,
      operator: row.querySelector('[data-condition-operator]').value,
      value: row.querySelector('[data-condition-value]')?.value || '',
    })).filter(item => item.source_key && item.question_id && item.operator);
  }
  function refreshDrawerQuestions(preserve = '') {
    const select = proxy('condition_question_id'); if (!select) return;
    const items = selectedParentQuestions();
    select.innerHTML = '<option value="">Selecione</option>' + items.map(item => `<option value="${item.id}">${esc(item.text)}</option>`).join('');
    select.value = preserve;
  }
  function refreshDrawerMeta() {
    const id = proxy('questionnaire_id')?.value || '';
    const meta = questionnaireMeta[String(id)] || {};
    const opening = drawer.querySelector('[data-communication-opening]'); if (opening) opening.value = meta.opening_message || '';
    const attempts = drawer.querySelector('[data-communication-attempts]'); if (attempts) attempts.value = meta.max_attempts || '';
    const reminder = drawer.querySelector('[data-communication-reminder]'); if (reminder) reminder.value = meta.retry_hours || '';
    const edit = drawer.querySelector('[data-edit-action-questionnaire]'); if (edit) edit.href = id ? `/questionarios/${id}/editar` : '#';
  }
  function updateDrawerVisibility() {
    const trigger = proxy('trigger')?.value;
    if (trigger === 'before_confirmation') {
      proxy('channel').value = 'screen_identified';
      proxy('require_confirmation').checked = false;
      proxy('schedule_mode').value = 'immediate';
      proxy('delay_value').value = '0';
    }
    const timing = proxy('schedule_mode')?.value || 'immediate';
    drawer.querySelector('[data-proxy-dependency]').hidden = trigger !== 'after_action';
    drawer.querySelectorAll('[data-proxy-delay]').forEach(item => item.hidden = timing === 'immediate' || timing === 'fixed_datetime');
    drawer.querySelector('[data-proxy-hour]').hidden = !['day_hour','next_allowed'].includes(timing);
    drawer.querySelector('[data-proxy-fixed-at]').hidden = timing !== 'fixed_datetime';
    drawer.querySelector('[data-proxy-version-fixed]').hidden = proxy('version_mode')?.value !== 'fixed';
    drawer.querySelector('[data-whatsapp-settings]').hidden = proxy('channel')?.value !== 'whatsapp';
    drawer.querySelector('[data-pet-context]').hidden = !proxy('per_pet')?.checked;
  }
  function openDrawer(card) {
    editingCard = card;
    updateVersions(card); updateConditionQuestions(card);
    ['name','questionnaire_id','version_mode','trigger','delay_value','delay_unit','send_hour','fixed_scheduled_at','channel','condition_logic','random_group','random_weight'].forEach(name => {
      const target = proxy(name), source = field(card, name); if (!target || !source) return;
      if (name === 'schedule_mode') return;
      target.value = source.value;
    });
    ['per_pet','active','require_confirmation'].forEach(name => { if (proxy(name)) proxy(name).checked = field(card, name)?.checked || false; });
    copyOptions(field(card, 'fixed_version_id'), proxy('fixed_version_id'), valueOf(card, 'fixed_version_id'));
    copyOptions(field(card, 'depends_on_key'), proxy('depends_on_key'), currentDependency(card));
    const schedule = valueOf(card, 'schedule_mode') || 'exact_interval';
    proxy('schedule_mode').value = schedule === 'exact_interval' && Number(valueOf(card, 'delay_value')) === 0 ? 'immediate' : schedule;
    if (!proxy('schedule_mode').value) proxy('schedule_mode').value = 'immediate';
    renderConditions(card);
    const randomGroups = [...new Set(cards().map(item => valueOf(item,'random_group').trim()).filter(Boolean))];
    const dataList = drawer.querySelector('#journey-random-groups'); if (dataList) dataList.innerHTML = randomGroups.map(group => `<option value="${esc(group)}"></option>`).join('');
    drawer.querySelector('[data-drawer-title]').textContent = cardName(card);
    refreshDrawerMeta(); updateDrawerVisibility();
    drawer.hidden = false; drawer.setAttribute('aria-hidden', 'false'); backdrop.hidden = false; document.body.classList.add('journey-drawer-open');
    requestAnimationFrame(() => drawer.classList.add('open'));
    proxy('name')?.focus();
  }
  function closeDrawer() {
    if (!drawer || drawer.hidden) return;
    drawer.classList.remove('open'); drawer.setAttribute('aria-hidden', 'true'); backdrop.hidden = true; document.body.classList.remove('journey-drawer-open');
    setTimeout(() => { drawer.hidden = true; }, 180);
    const returnCard = editingCard; editingCard = null; returnCard?.focus();
  }
  function applyDrawer() {
    if (!editingCard) return;
    ['name','questionnaire_id','version_mode','fixed_version_id','trigger','depends_on_key','delay_value','delay_unit','send_hour','fixed_scheduled_at','channel','condition_logic','random_group','random_weight'].forEach(name => {
      const source = field(editingCard, name), target = proxy(name); if (source && target) source.value = target.value;
    });
    ['per_pet','active','require_confirmation'].forEach(name => { if (field(editingCard, name) && proxy(name)) field(editingCard, name).checked = proxy(name).checked; });
    const timing = proxy('schedule_mode').value || 'immediate';
    field(editingCard, 'schedule_mode').value = timing === 'immediate' ? 'exact_interval' : timing;
    if (timing === 'immediate') field(editingCard, 'delay_value').value = '0';
    field(editingCard, 'conditions_json').value = JSON.stringify(serializedConditions());
    field(editingCard, 'condition_question_id').value = ''; field(editingCard, 'condition_operator').value = ''; field(editingCard, 'condition_value').value = '';
    field(editingCard, 'depends_on_key').dataset.selectedKey = field(editingCard, 'depends_on_key').value;
    field(editingCard, 'fixed_version_id').dataset.selected = field(editingCard, 'fixed_version_id').value;
    reindex(); markDirty(); closeDrawer();
  }
  drawer?.addEventListener('change', event => {
    if (event.target.matches('[data-proxy-field="questionnaire_id"]')) {
      const source = field(editingCard, 'fixed_version_id');
      const items = versions[String(event.target.value)] || [];
      const target = proxy('fixed_version_id'); target.innerHTML = '<option value="">Selecione</option>' + items.map(item => `<option value="${item.id}">Versão ${item.number}</option>`).join('');
      if (source) source.dataset.selected = ''; refreshDrawerMeta();
    }
    updateDrawerVisibility();
  });
  drawer?.querySelector('[data-add-condition]')?.addEventListener('click', () => addConditionRow());
  drawer?.querySelector('[data-condition-list]')?.addEventListener('click', event => {
    const button = event.target.closest('[data-remove-condition]'); if (!button) return;
    button.closest('[data-condition-row]')?.remove();
    drawer.querySelector('[data-condition-empty]').hidden = drawer.querySelectorAll('[data-condition-row]').length > 0;
  });
  drawer?.querySelector('[data-condition-list]')?.addEventListener('change', event => {
    const row = event.target.closest('[data-condition-row]'); if (!row) return;
    if (event.target.matches('[data-condition-source]')) refreshConditionRow(row, {question_id:'', value:''});
    else if (event.target.matches('[data-condition-question], [data-condition-operator]')) refreshConditionRow(row, {question_id:row.querySelector('[data-condition-question]').value, value:row.querySelector('[data-condition-value]')?.value || ''});
  });
  form.querySelectorAll('[data-close-action]').forEach(button => button.addEventListener('click', closeDrawer));
  drawer?.querySelector('[data-apply-action]')?.addEventListener('click', applyDrawer);
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && editingCard) closeDrawer(); });

  function moveCard(card, direction) {
    const dependencies = new Map(cards().map(item => [keyFor(item), currentDependency(item)]));
    if (direction < 0 && card.previousElementSibling) list.insertBefore(card, card.previousElementSibling);
    else if (direction > 0 && card.nextElementSibling) list.insertBefore(card.nextElementSibling, card);
    else return;
    reindex(dependencies); markDirty(); announce(`${cardName(card)} movida para a posição ${cards().indexOf(card) + 1}.`);
  }
  list.addEventListener('click', event => {
    const card = event.target.closest('[data-flow-action]'); if (!card) return;
    if (event.target.closest('[data-remove-action]')) {
      const dependencies = new Map(cards().map(item => [keyFor(item), currentDependency(item)])); const name = cardName(card); card.remove(); reindex(dependencies); markDirty(); announce(`${name} removida. Dependências afetadas foram sinalizadas.`);
    } else if (event.target.closest('[data-move-action-up]')) moveCard(card, -1);
    else if (event.target.closest('[data-move-action-down]')) moveCard(card, 1);
    else if (event.target.closest('[data-edit-action]') || !event.target.closest('button')) openDrawer(card);
  });
  list.addEventListener('keydown', event => {
    const handle = event.target.closest('[data-action-drag-handle]');
    if (handle && ['ArrowUp','ArrowDown'].includes(event.key)) { event.preventDefault(); moveCard(handle.closest('[data-flow-action]'), event.key === 'ArrowUp' ? -1 : 1); handle.focus(); }
    else if (event.target.matches('[data-flow-action]') && ['Enter',' '].includes(event.key)) { event.preventDefault(); openDrawer(event.target); }
  });
  list.addEventListener('pointerdown', event => { const card = event.target.closest('[data-action-drag-handle]')?.closest('[data-flow-action]'); if (card) card.draggable = true; });
  list.addEventListener('dragstart', event => { const card = event.target.closest('[data-flow-action]'); if (!card?.draggable) { event.preventDefault(); return; } draggedCard = card; card.classList.add('is-dragging'); event.dataTransfer.effectAllowed = 'move'; });
  list.addEventListener('dragover', event => { if (!draggedCard) return; event.preventDefault(); const target = event.target.closest('[data-flow-action]'); if (!target || target === draggedCard) return; const rect = target.getBoundingClientRect(); list.insertBefore(draggedCard, event.clientY < rect.top + rect.height / 2 ? target : target.nextSibling); });
  list.addEventListener('dragend', () => { if (!draggedCard) return; const moved = draggedCard; moved.classList.remove('is-dragging'); moved.draggable = false; draggedCard = null; reindex(); markDirty(); announce(`${cardName(moved)} movida para a posição ${cards().indexOf(moved) + 1}.`); });
  form.querySelector('[data-add-flow-action]')?.addEventListener('click', () => { const card = template.content.firstElementChild.cloneNode(true); card.dataset.itemKey = newKey(); list.append(card); keyFor(card); reindex(); markDirty(); openDrawer(card); });
  form.querySelector('[data-add-pre-confirmation]')?.addEventListener('click', () => {
    const card = template.content.firstElementChild.cloneNode(true); card.dataset.itemKey = newKey(); list.append(card); keyFor(card);
    field(card,'name').value = 'Etapa inicial'; field(card,'trigger').value = 'before_confirmation'; field(card,'channel').value = 'screen_identified'; field(card,'delay_value').value = '0'; field(card,'schedule_mode').value = 'exact_interval'; field(card,'require_confirmation').checked = false;
    reindex(); markDirty(); activateTab('acoes'); openDrawer(card);
  });

  function fieldFor(error) {
    const card = error.item_key ? cards().find(item => keyFor(item) === error.item_key) : null;
    if (card) return field(card, error.field) || card;
    return form.querySelector(`[name="${CSS.escape(error.field)}"]`) || form.querySelector(`#${CSS.escape(error.section || '')}`);
  }
  function clearErrors() {
    form.querySelectorAll('.field-error').forEach(item => item.classList.remove('field-error'));
    form.querySelectorAll('.editor-inline-error').forEach(item => item.remove());
    form.querySelectorAll('[data-action-error]').forEach(item => { item.hidden = true; item.innerHTML = ''; });
    form.querySelectorAll('[data-flow-action].has-error').forEach(item => item.classList.remove('has-error'));
    form.querySelectorAll('[data-tab-state]').forEach(item => item.classList.remove('error'));
    form.querySelector('[data-error-summary]')?.remove();
  }
  function showErrors(errors, createSummary = true) {
    clearErrors(); if (!errors.length) return;
    if (createSummary) {
      const box = document.createElement('div'); box.className = 'editor-error-summary'; box.dataset.errorSummary = '1'; box.tabIndex = -1; box.setAttribute('role','alert');
      box.innerHTML = `<strong>Revise ${errors.length} ${errors.length === 1 ? 'campo' : 'campos'} antes de salvar.</strong><ul>${errors.map(item => `<li><button type="button" data-error-jump data-section="${esc(item.section)}" data-item-key="${esc(item.item_key || '')}" data-field="${esc(item.field)}">${esc(item.message)}</button></li>`).join('')}</ul>`;
      form.querySelector('.journey-workspace').prepend(box);
    }
    errors.forEach(error => {
      form.querySelector(`[data-tab-state="${error.section}"]`)?.classList.add('error');
      const card = error.item_key ? cards().find(item => keyFor(item) === error.item_key) : null;
      if (card) { const area = card.querySelector('[data-action-error]'); area.hidden = false; area.insertAdjacentHTML('beforeend', `<p>${esc(error.message)}</p>`); card.classList.add('has-error'); }
      const target = fieldFor(error); if (target && !target.closest('[hidden]')) { target.classList.add('field-error'); const message = document.createElement('small'); message.className = 'editor-inline-error'; message.textContent = error.message; (target.closest('label') || target).appendChild(message); }
    });
  }
  function jumpToError(error) {
    activateTab(error.section === 'revisao' ? 'revisao' : error.section, false);
    const card = error.item_key ? cards().find(item => keyFor(item) === error.item_key) : null;
    if (card) { activateTab('acoes'); openDrawer(card); setTimeout(() => { const target = proxy(error.field); target?.classList.add('field-error'); target?.focus(); }, 40); }
    else { const target = fieldFor(error); if (target) { const details = target.closest('details'); if (details) details.open = true; target.scrollIntoView({behavior:'smooth', block:'center'}); target.focus?.({preventScroll:true}); } }
  }
  form.addEventListener('click', event => { const button = event.target.closest('[data-error-jump]'); if (button) jumpToError({section:button.dataset.section, item_key:button.dataset.itemKey, field:button.dataset.field}); });

  function validate() {
    const errors = [], add = (section, fieldName, message, itemKey = '') => errors.push({section, field:fieldName, message, item_key:itemKey});
    if (!form.elements.name.value.trim()) add('identificacao','name','Informe o nome do fluxo.');
    if (!form.querySelectorAll('input[name^="profile_"]:checked').length) add('identificacao','profiles','Selecione Totem ou Entrevistador.');
    if (!form.elements.welcome_title.value.trim()) add('identificacao','welcome_title','Informe o título de boas-vindas.');
    if (!form.elements.welcome_text.value.trim()) add('identificacao','welcome_text','Informe o texto de apresentação.');
    if (!form.elements.closing_title.value.trim()) add('identificacao','closing_title','Informe o título de encerramento.');
    if (!form.elements.closing_text.value.trim()) add('identificacao','closing_text','Informe a mensagem de encerramento.');
    const registrationId = form.elements.registration_questionnaire_id.value;
    if (!registrationId) add('coleta','registration_questionnaire_id','Selecione um questionário de Cadastro estruturado.');
    else {
      const summary = registrationSummaries[String(registrationId)] || {};
      if (!summary.published) add('coleta','registration_questionnaire_id','Publique uma versão do Cadastro estruturado.');
      if (!summary.bindings?.['lead.name'] || !summary.bindings?.['lead.phone']) add('coleta','registration_questionnaire_id','O Cadastro estruturado precisa conter Nome completo e WhatsApp.');
      if (summary.duplicates?.length) add('coleta','registration_questionnaire_id','O Cadastro estruturado possui bindings duplicados.');
      if (summary.incompatible?.length) add('coleta','registration_questionnaire_id','O Cadastro estruturado possui pergunta incompatível com o binding.');
    }
    const maxPets = Number(form.elements.max_pets.value); if (!Number.isInteger(maxPets) || maxPets < 1 || maxPets > 20) add('coleta','max_pets','O máximo de pets deve ficar entre 1 e 20.');
    if (form.elements.consent_research_enabled.checked && !form.elements.consent_research_text.value.trim()) add('consentimento','consent_research_text','Informe o texto para pesquisas.');
    if (form.elements.consent_marketing_enabled.checked && !form.elements.consent_marketing_text.value.trim()) add('consentimento','consent_marketing_text','Informe o texto para campanhas.');
    if (form.elements.consent_terms_enabled.checked && !form.elements.consent_terms_version.value.trim()) add('consentimento','consent_terms_version','Informe a versão dos termos.');
    const verification = form.querySelector('[name="phone_verification_mode"]:checked')?.value;
    const timeout = Number(form.elements.phone_verification_timeout.value); if (verification !== 'none' && (!Number.isInteger(timeout) || timeout < 30 || timeout > 1800)) add('confirmacao','phone_verification_timeout','O tempo de espera deve ficar entre 30 e 1800 segundos.');
    const all = cards(); if (!all.length) add('acoes','actions_count','Adicione pelo menos uma ação ao fluxo.');
    const byKey = new Map(all.map((card,index) => [keyFor(card), {card,index}])); const dependencyMap = new Map();
    all.forEach((card,index) => {
      const key = keyFor(card), get = name => field(card,name), meta = questionnaireMeta[String(valueOf(card,'questionnaire_id'))] || {};
      if (!cardName(card,'').trim()) add('acoes','name',`Informe o nome da ação ${index + 1}.`,key);
      if (!get('questionnaire_id').value) add('acoes','questionnaire_id',`Selecione o questionário da ação ${index + 1}.`,key); else if (!meta.published) add('acoes','questionnaire_id','Publique uma versão deste questionário antes de usá-lo.',key);
      if (get('version_mode').value === 'fixed' && !get('fixed_version_id').value) add('acoes','fixed_version_id','Escolha uma versão publicada.',key);
      const delay = Number(get('delay_value').value); if (!Number.isInteger(delay) || delay < 0) add('acoes','delay_value','O atraso não pode ser negativo.',key);
      const hour = Number(get('send_hour').value); if (!Number.isInteger(hour) || hour < 0 || hour > 23) add('acoes','send_hour','A hora preferencial deve ficar entre 0 e 23.',key);
      if (get('schedule_mode').value === 'fixed_datetime') { const fixed = new Date(get('fixed_scheduled_at').value); if (!get('fixed_scheduled_at').value || Number.isNaN(fixed.getTime())) add('acoes','fixed_scheduled_at','Informe uma data e hora válidas.',key); }
      if (get('per_pet').checked && get('channel').value.startsWith('screen_')) add('acoes','per_pet','Ações por pet devem usar o WhatsApp.',key);
      if (get('channel').value === 'whatsapp' && meta.response_mode === 'anonymous') add('acoes','channel','Pesquisas anônimas não podem ser enviadas pelo WhatsApp.',key);
      if (get('trigger').value === 'before_confirmation') {
        if (get('channel').value !== 'screen_identified') add('acoes','channel','Etapas antes da confirmação devem usar Tela identificada.',key);
        if (Number(get('delay_value').value || 0) > 0 || get('schedule_mode').value === 'fixed_datetime') add('acoes','delay_value','Etapas antes da confirmação precisam acontecer imediatamente.',key);
        if (get('require_confirmation').checked) add('acoes','require_confirmation','Esta etapa acontece antes da confirmação.',key);
      }
      let conditions = []; try { conditions = JSON.parse(get('conditions_json').value || '[]'); } catch (_) { add('acoes','conditions_json','As condições estão inválidas; abra a ação e revise.',key); }
      if (!Array.isArray(conditions) || conditions.length > 10) add('acoes','conditions_json','Use no máximo 10 condições válidas.',key);
      else conditions.forEach(condition => {
        const source = condition?.source_key === 'registration' ? {index:-1} : byKey.get(condition?.source_key);
        if (!source || source.index >= index) add('acoes','conditions_json','A condição só pode usar uma resposta anterior.',key);
        if (!condition?.question_id || !condition?.operator) add('acoes','conditions_json','Complete a origem, pergunta e comparação da condição.',key);
        if (!['answered','not_answered'].includes(condition?.operator) && !String(condition?.value || '').trim()) add('acoes','conditions_json','Selecione ou informe o valor esperado.',key);
      });
      const group = get('random_group').value.trim(), weight = Number(get('random_weight').value || 0);
      if (group && (!Number.isInteger(weight) || weight < 1 || weight > 100)) add('acoes','random_weight','O peso do sorteio deve ficar entre 1 e 100.',key);
      if (get('trigger').value !== 'after_action') return;
      const parentKey = get('depends_on_key').value; dependencyMap.set(key,parentKey); const parent = byKey.get(parentKey);
      if (!parentKey) add('acoes','depends_on_key','Escolha uma ação anterior como dependência.',key); else if (parentKey === key) add('acoes','depends_on_key','Uma ação não pode depender dela mesma.',key); else if (!parent) add('acoes','depends_on_key','A ação usada como dependência foi removida.',key); else if (parent.index >= index) add('acoes','depends_on_key','A dependência precisa estar antes desta ação.',key);
      if (get('channel').value.startsWith('screen_') && parent && !valueOf(parent.card,'channel').startsWith('screen_')) add('acoes','channel','Uma ação condicional na tela precisa depender de outra ação exibida na tela.',key);
      if (get('channel').value.startsWith('screen_') && (Number(get('delay_value').value || 0) > 0 || get('schedule_mode').value === 'fixed_datetime')) add('acoes','delay_value','A continuação condicional na tela precisa acontecer imediatamente.',key);
      if (parent && field(parent.card,'per_pet').checked && !get('per_pet').checked) add('acoes','per_pet','Uma ação geral não pode depender de uma ação por pet.',key);
      const question = get('condition_question_id').value, operator = get('condition_operator').value, expected = get('condition_value').value.trim();
      if (question && !operator) add('acoes','condition_operator','Escolha como avaliar esta resposta.',key);
      if (question && operator && !['answered','not_answered'].includes(operator) && !expected) add('acoes','condition_value','Informe o valor esperado da condição.',key);
      if (!question && (operator || expected)) add('acoes','condition_question_id','Selecione a pergunta usada pela condição.',key);
    });
    const randomGroups = new Map();
    all.forEach(card => { const group=valueOf(card,'random_group').trim(); if(group){ if(!randomGroups.has(group)) randomGroups.set(group,[]); randomGroups.get(group).push(card); } });
    randomGroups.forEach((members,group) => { const signatures=new Set(members.map(card => `${valueOf(card,'trigger')}|${currentDependency(card)}`)); if(signatures.size>1) members.forEach(card => add('acoes','random_group',`As opções do sorteio “${group}” precisam usar o mesmo gatilho e dependência.`,keyFor(card))); });
    if (!form.elements.consent_research_enabled.checked && all.some(card => field(card,'active').checked && valueOf(card,'channel') === 'whatsapp')) add('consentimento','consent_research_enabled','Ative o consentimento para pesquisas ou remova as ações de WhatsApp.');
    const visiting = new Set(), visited = new Set(), cycle = new Set();
    function visit(key,path=[]) { if (visited.has(key)) return; if (visiting.has(key)) { path.slice(Math.max(0,path.indexOf(key))).forEach(item => cycle.add(item)); return; } visiting.add(key); const parent = dependencyMap.get(key); if (parent && byKey.has(parent)) visit(parent,[...path,key]); visiting.delete(key); visited.add(key); }
    dependencyMap.forEach((_,key) => visit(key)); cycle.forEach(key => add('acoes','depends_on_key','As dependências formam um ciclo.',key));
    return errors;
  }

  function renderReview() {
    const errors = validate();
    const warnings = [];
    cards().forEach((card,index) => { const meta = questionnaireMeta[String(valueOf(card,'questionnaire_id'))] || {}; if (valueOf(card,'channel') === 'whatsapp' && !meta.opening_message?.trim()) warnings.push({section:'acoes', item_key:keyFor(card), field:'questionnaire_id', message:`Ação ${index + 1}: mensagem inicial ausente no questionário.`}); });
    const groupCounts = new Map(); cards().forEach(card => { const group=valueOf(card,'random_group').trim(); if(group) groupCounts.set(group,(groupCounts.get(group)||0)+1); });
    groupCounts.forEach((amount,group) => { if(amount<2) warnings.push({section:'acoes',field:'random_group',message:`O sorteio “${group}” possui somente uma opção.`}); });
    const diagnostics = form.querySelector('[data-review-diagnostics]');
    const consentNames = [['consent_research_enabled','Pesquisas'],['consent_marketing_enabled','Campanhas'],['consent_terms_enabled','Termos']].filter(([name]) => form.elements[name].checked).map(([,label]) => label);
    const confirmation = ({none:'Não confirmar',send_continue:'Enviar e continuar',future_only:'Antes das ações dependentes',required:'Confirmar antes da jornada'})[form.querySelector('[name="phone_verification_mode"]:checked')?.value] || 'Pendente';
    const overview = form.querySelector('[data-review-overview]');
    const preCount=cards().filter(card=>valueOf(card,'trigger')==='before_confirmation').length;
    overview.innerHTML = `<article><small>Cadastro</small><strong>${esc(form.elements.registration_questionnaire_id.selectedOptions[0]?.textContent || 'Não definido')}</strong></article><article><small>Antes do WhatsApp</small><strong>${preCount} etapa${preCount===1?'':'s'}</strong></article><article><small>Confirmação</small><strong>${esc(confirmation)}</strong></article><article><small>Jornada</small><strong>${cards().length} ações · ${groupCounts.size} sorteio${groupCounts.size===1?'':'s'}</strong></article>`;
    const items = [...errors.map(item => ({...item, level:'error'})), ...warnings.map(item => ({...item, level:'warning'}))];
    diagnostics.innerHTML = items.length ? `<h3>Diagnósticos</h3>${items.map(item => `<button type="button" class="review-diagnostic ${item.level}" data-error-jump data-section="${esc(item.section)}" data-item-key="${esc(item.item_key || '')}" data-field="${esc(item.field)}"><span>${item.level === 'error' ? '×' : '!'}</span><div><strong>${esc(item.message)}</strong><small>${item.level === 'error' ? 'Corrija antes de ativar.' : 'Recomendação de comunicação.'}</small></div></button>`).join('')}` : '<div class="review-ready"><span>✓</span><div><strong>Jornada pronta</strong><p>Cadastro, cronologia, dependências, condições e publicações estão consistentes.</p></div></div>';
    showErrors(errors, false);
    form.querySelector('[data-tab-state="revisao"]')?.classList.toggle('error', errors.length > 0);
    return errors;
  }
  form.querySelector('[data-run-review]')?.addEventListener('click', renderReview);

  function minutesFor(card) {
    const amount = Number(valueOf(card,'delay_value') || 0), unit = valueOf(card,'delay_unit');
    return unit === 'minutes' ? amount : unit === 'hours' ? amount * 60 : amount * 1440;
  }
  function labScenario() {
    const elapsed = Number(form.querySelector('[data-lab-time]').value), confirmed = form.querySelector('[data-lab-confirmation]').value === 'yes', condition = form.querySelector('[data-lab-condition]').value === 'yes', pets = Math.max(0, Number(form.querySelector('[data-lab-pets]').value) || 0);
    return {elapsed_minutes:elapsed, confirmed, condition_matches:condition, pets};
  }
  function renderServerSimulation(result) {
    const rows = (result.actions || []).map(item => `<li class="${item.ready ? 'ready' : 'waiting'}"><span>${item.ready ? '✓' : '○'}</span><div><strong>${esc(item.name)}</strong><small>${item.ready ? `${item.execution_count} execução${item.execution_count === 1 ? '' : 'ões'} liberada${item.execution_count === 1 ? '' : 's'} · versão ${item.version_number || '—'}` : esc(item.reason)}</small></div><button class="btn ghost compact" type="button" data-test-lab-action="${item.action_id}">Testar isolada</button></li>`).join('');
    form.querySelector('[data-lab-result]').innerHTML = `<div class="lab-result-head"><strong>${result.isolated_action_id ? 'Teste isolado da ação' : 'Resultado completo do cenário'}</strong><span>Simulação segura · 0 gravações</span></div><ul>${rows || '<li>Nenhuma ação encontrada.</li>'}</ul>`;
  }
  async function requestServerSimulation(actionId = '') {
    const flowId = form.dataset.flowId; if (!flowId) return false;
    const target = form.querySelector('[data-lab-result]'); target.innerHTML='<p>Calculando jornada congelada no servidor…</p>';
    const csrf = document.cookie.split('; ').find(item => item.startsWith('escutapet_v2_csrf='))?.split('=').slice(1).join('=') || '';
    const url = actionId ? `/api/fluxos/${flowId}/laboratorio/acoes/${actionId}/simular` : `/api/fluxos/${flowId}/laboratorio/simular`;
    try { const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},credentials:'same-origin',body:JSON.stringify(labScenario())}); if(!response.ok) throw new Error(`HTTP ${response.status}`); renderServerSimulation(await response.json()); return true; }
    catch { target.innerHTML='<p class="notice-box danger">Não foi possível executar o laboratório no servidor. A prévia local foi usada.</p>'; return false; }
  }
  async function runSimulation() {
    if (await requestServerSimulation()) return;
    const {elapsed_minutes:elapsed, confirmed, condition_matches:condition, pets} = labScenario();
    const executed = new Set(), randomChosen = new Set(), rows = [];
    cards().forEach(card => {
      const key = keyFor(card), active = field(card,'active').checked, parent = currentDependency(card), trigger = valueOf(card,'trigger');
      let reason = '', ready = active;
      if (!active) { ready = false; reason = 'ação pausada'; }
      if (ready && (field(card,'require_confirmation').checked || trigger === 'after_confirmation') && !confirmed) { ready = false; reason = 'aguardando confirmação'; }
      if (ready && trigger === 'after_action' && !executed.has(parent)) { ready = false; reason = 'aguardando ação anterior'; }
      let conditionCount = 0; try { conditionCount = JSON.parse(valueOf(card,'conditions_json') || '[]').length || 0; } catch (_) {}
      if (ready && (valueOf(card,'condition_question_id') || conditionCount) && !condition) { ready = false; reason = 'condição não atendida'; }
      if (ready && valueOf(card,'schedule_mode') === 'fixed_datetime') { const due = new Date(valueOf(card,'fixed_scheduled_at')).getTime(), simulated = Date.now() + elapsed * 60000; if (!due || due > simulated) { ready = false; reason = 'data fixa ainda não alcançada'; } }
      else if (ready && minutesFor(card) > elapsed) { ready = false; reason = 'prazo ainda não alcançado'; }
      if (ready && field(card,'per_pet').checked && pets === 0) { ready = false; reason = 'nenhum pet na coleta'; }
      const randomGroup = valueOf(card,'random_group').trim();
      if (ready && randomGroup && randomChosen.has(`${trigger}|${currentDependency(card)}|${randomGroup}`)) { ready = false; reason = `outro caminho do sorteio “${randomGroup}” foi escolhido`; }
      if (ready && randomGroup) randomChosen.add(`${trigger}|${currentDependency(card)}|${randomGroup}`);
      if (ready) executed.add(key);
      const amount = ready ? (field(card,'per_pet').checked ? pets : 1) : 0;
      rows.push(`<li class="${ready ? 'ready' : 'waiting'}"><span>${ready ? '✓' : '○'}</span><div><strong>${esc(cardName(card))}</strong><small>${ready ? `${amount} execução${amount === 1 ? '' : 'ões'} liberada${amount === 1 ? '' : 's'}` : esc(reason)}</small></div>${valueOf(card,'questionnaire_id') ? `<a href="/questionarios/${valueOf(card,'questionnaire_id')}/testar">Testar ação</a>` : ''}</li>`);
    });
    form.querySelector('[data-lab-result]').innerHTML = `<strong>Resultado do cenário</strong><ul>${rows.join('')}</ul>`;
  }
  form.querySelector('[data-run-simulation]')?.addEventListener('click', runSimulation);
  form.querySelector('[data-lab-result]')?.addEventListener('click', event => { const button=event.target.closest('[data-test-lab-action]'); if(button) requestServerSimulation(button.dataset.testLabAction); });

  function captureRecoveryData() {
    reindex();
    const fields = {};
    const excluded = new Set(['submission_token','base_revision','editor_recovery_source','actions_count']);
    [...form.elements].forEach(control => {
      if (!control.name || excluded.has(control.name) || control.name.startsWith('action_') || control.type === 'submit' || control.type === 'button') return;
      if (control.type === 'checkbox') {
        if (['city_ids','device_ids'].includes(control.name)) { if (!Array.isArray(fields[control.name])) fields[control.name] = []; if (control.checked) fields[control.name].push(control.value); }
        else fields[control.name] = control.checked;
      } else if (control.type === 'radio') { if (control.checked) fields[control.name] = control.value; }
      else fields[control.name] = control.value;
    });
    const actions = cards().map(card => Object.fromEntries([...card.querySelectorAll('[data-action-field]')].map(control => [control.dataset.actionField, control.type === 'checkbox' ? control.checked : control.value])));
    return {fields, actions};
  }
  function restoreRecoveryData(data) {
    if (!data || typeof data !== 'object') return;
    Object.entries(data.fields || {}).forEach(([name,value]) => {
      const controls = [...form.querySelectorAll(`[name="${CSS.escape(name)}"]`)];
      controls.forEach(control => {
        if (control.type === 'checkbox') control.checked = Array.isArray(value) ? value.map(String).includes(String(control.value)) : Boolean(value);
        else if (control.type === 'radio') control.checked = String(control.value) === String(value);
        else control.value = value ?? '';
      });
    });
    if (Array.isArray(data.actions)) {
      list.replaceChildren();
      data.actions.forEach(item => {
        const card = template.content.firstElementChild.cloneNode(true);
        card.dataset.itemKey = item.item_key || newKey();
        card.querySelectorAll('[data-action-field]').forEach(control => { const value = item[control.dataset.actionField]; if (control.type === 'checkbox') control.checked = Boolean(value); else if (value !== undefined && value !== null) { control.value = String(value); control.dataset.selected = String(value); control.dataset.selectedKey = String(value); } });
        list.append(card);
      });
    }
    reindex(); updateScope(); updateConditionalSettings(); renderReview(); markDirty();
  }
  window.EditorRecoveryAdapter = {
    capture: captureRecoveryData,
    restore: restoreRecoveryData,
    summary: data => ({Nome:data?.fields?.name || 'Sem nome', Status:data?.fields?.status || 'rascunho', Ações:data?.actions?.length || 0, Cadastro:data?.fields?.registration_questionnaire_id || 'não definido'}),
    prepareDuplicate: () => { cards().forEach(card => { field(card,'id').value=''; const key=newKey(); card.dataset.itemKey=key; field(card,'item_key').value=key; }); if (form.elements.name && !form.elements.name.value.startsWith('Cópia de ')) form.elements.name.value=`Cópia de ${form.elements.name.value}`; reindex(); },
  };

  form.addEventListener('input', event => { if (!event.target.closest('[data-action-drawer]')) markDirty(); });
  form.addEventListener('change', event => { if (!event.target.closest('[data-action-drawer]')) markDirty(); updateConditionalSettings(); });
  form.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    reindex(); setStatus('Validando', 'validating'); const errors = validate();
    if (errors.length) { event.preventDefault(); showErrors(errors); setStatus('Erro ao salvar', 'error'); jumpToError(errors[0]); return; }
    form.dispatchEvent(new CustomEvent('editor:submitting'));
    submitting = true; dirty = false; form.querySelectorAll('[type="submit"]').forEach(button => { button.disabled = true; button.textContent = 'Salvando…'; }); setStatus('Salvando', 'saving');
  });
  form.addEventListener('keydown', event => { if (submitting && event.key === 'Enter') event.preventDefault(); });
  window.addEventListener('beforeunload', event => { if (dirty && !submitting) { event.preventDefault(); event.returnValue = ''; } });

  reindex();
  if (serverErrors.length) requestAnimationFrame(() => { showErrors(serverErrors); jumpToError(serverErrors[0]); });
})();
