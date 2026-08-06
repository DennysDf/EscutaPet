(() => {
  const form = document.querySelector('#questionnaire-form');
  const list = document.querySelector('#questions-list');
  const detail = document.querySelector('#question-editor-panel');
  const hidden = document.querySelector('#questions-json');
  const empty = document.querySelector('[data-empty-question]');
  const status = document.querySelector('[data-save-status]');
  const live = document.querySelector('[data-reorder-live]');
  if (!form || !list || !detail || !hidden) return;

  const segments = window.QUESTION_EDITOR_SEGMENTS || [];
  const version = window.QUESTION_EDITOR_VERSION || {current: 0, next: 1, active: 0};
  let initial = [], serverErrors = [], impacts = {};
  try { initial = JSON.parse(document.querySelector('#initial-questions')?.textContent || '[]'); } catch { initial = []; }
  try { serverErrors = JSON.parse(document.querySelector('#editor-errors')?.textContent || '[]'); } catch { serverErrors = []; }
  try { impacts = JSON.parse(document.querySelector('#question-impacts')?.textContent || '{}'); } catch { impacts = {}; }

  const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const normalize = value => String(value || '').trim().toLocaleLowerCase('pt-BR').replace(/\s+/g, ' ');
  const clientKey = prefix => `${prefix}:${crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
  const typeLabels = {
    choice: 'Escolha única', multiple_choice: 'Múltipla escolha', score: 'Nota numérica', yes_no: 'Sim ou não', stars: 'Estrelas', text: 'Texto', photo: 'Foto', audio: 'Áudio', video: 'Vídeo', document: 'Documento', location: 'Localização', contact: 'Contato', multiple_files: 'Mídia ou arquivo',
  };
  const typeOptions = Object.entries(typeLabels).map(([value, label]) => `<option value="${value}">${label}</option>`).join('');
  const mediaTypes = new Set(['photo','audio','video','document','location','contact','multiple_files']);
  const conditionOperators = {
    choice: [['equals','é igual a'],['not_equals','é diferente de'],['answered','foi respondida'],['not_answered','não foi respondida']],
    multiple_choice: [['equals','contém a opção'],['not_equals','não contém a opção'],['answered','foi respondida'],['not_answered','não foi respondida']],
    yes_no: [['equals','é igual a'],['not_equals','é diferente de'],['answered','foi respondida'],['not_answered','não foi respondida']],
    text: [['equals','texto é igual a'],['not_equals','texto é diferente de'],['contains','texto contém'],['not_contains','texto não contém'],['answered','foi respondida'],['not_answered','não foi respondida']],
    score: [['gte','nota maior ou igual a'],['lte','nota menor ou igual a'],['between','nota entre'],['answered','foi respondida'],['not_answered','não foi respondida']],
    stars: [['gte','nota maior ou igual a'],['lte','nota menor ou igual a'],['between','nota entre'],['answered','foi respondida'],['not_answered','não foi respondida']],
    default: [['equals','é igual a'],['not_equals','é diferente de'],['answered','foi respondida'],['not_answered','não foi respondida']],
  };
  const numericConditionOperators = new Set(['gte','lte','between']);
  const sectionTabs = {identity:'general', questions:'questions', trigger:'logic', audience:'channels', actions:'segments', publication:'publication'};
  let selectedCard = null;
  let dirty = form.dataset.serverError === '1';
  let submitting = false;
  let draggedQuestion = null;

  const setStatus = (text, kind = '') => { if (status) { status.textContent = text; status.dataset.state = kind; } };
  const announce = text => { if (live) live.textContent = text; };
  function markDirty() { if (!submitting) { dirty = true; setStatus('Alterações não salvas', 'dirty'); updatePublicationSummary(); } }
  if (form.dataset.saved === '1') setStatus(`Salvo às ${new Date().toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'})}`, 'saved');
  else if (dirty) setStatus('Erro ao salvar', 'error');

  const segmentOptions = selected => `<option value="">Nenhum segmento</option>${segments.map(item => `<option value="${item.id}" ${String(item.id) === String(selected || '') ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}`;
  const bindingOptions = selected => [
    ['', 'Pesquisa complementar (não altera o cadastro)'], ['lead.name', 'Responsável · Nome completo'],
    ['lead.phone', 'Responsável · WhatsApp'], ['lead.city', 'Responsável · Cidade'],
    ['lead.neighborhood', 'Responsável · Bairro'], ['pet.name', 'Pet · Nome'],
    ['pet.species', 'Pet · Espécie'], ['visit.reason', 'Atendimento · Motivo'],
    ['visit.service_type', 'Atendimento · Serviço'], ['visit.service_status', 'Atendimento · Situação'],
    ['visit.description', 'Atendimento · Detalhes'],
  ].map(([value, label]) => `<option value="${value}" ${value === (selected || '') ? 'selected' : ''}>${label}</option>`).join('');

  function normalizedQuestion(data = {}) {
    const settings = data.settings && typeof data.settings === 'object' ? {...data.settings} : {};
    if (settings.visibility && typeof settings.visibility === 'object') settings.visibility = {...settings.visibility};
    return {
      ...data,
      id: Number(data.id || 0) || null,
      item_key: data.item_key || (data.id ? `question:${data.id}` : clientKey('question:new')),
      archived: Boolean(data.archived),
      replacement_question_id: Number(data.replacement_question_id || 0) || null,
      text: String(data.text || ''), type: data.type || 'text', required: data.required !== false,
      help_text: String(data.help_text || ''), options: Array.isArray(data.options) ? data.options.map(option => ({...option, id: option.id || clientKey('option')})) : [],
      min_score: data.min_score ?? 0, max_score: data.max_score ?? 10, low_score_threshold: data.low_score_threshold ?? '',
      segment_low_id: data.segment_low_id || null, segment_high_id: data.segment_high_id || null,
      whatsapp_response_mode: data.whatsapp_response_mode || 'auto', data_binding: data.data_binding || '', settings,
    };
  }

  function impactRows(card) { return impacts[String(card?._data?.id || card?.dataset.questionId)] || []; }
  function createImpactDialog() {
    const dialog = document.createElement('dialog');
    dialog.className = 'impact-dialog';
    dialog.innerHTML = '<form method="dialog"><div data-impact-content></div><div class="dialog-actions"><button class="btn ghost" value="cancel">Cancelar</button><button class="btn primary" value="confirm" data-impact-confirm>Continuar alteração</button></div></form>';
    document.body.append(dialog); return dialog;
  }
  async function confirmImpact(card, mode = 'edit') {
    saveCurrent();
    const uses = impactRows(card);
    if (!uses.length) return {confirmed:true, replacementId:''};
    const dialog = createImpactDialog();
    const links = uses.map(use => `<li><strong>${esc(use.flow_name)}</strong> · ${esc(use.action_name)} · operador <code>${esc(use.operator)}</code> <a href="/fluxos/${use.flow_id}/editar#acoes" target="_blank" rel="noopener">Abrir fluxo</a></li>`).join('');
    let replacement = '';
    const candidates = [...list.children].filter(item => item !== card && item._data?.id && !item._data.archived);
    const replacementHtml = mode === 'archive' ? `<label>Substituir nas ações por<select data-impact-replacement required><option value="">Selecione outra pergunta ativa</option>${candidates.map(item => `<option value="${item._data.id}">${esc(item._data.text || 'Pergunta sem texto')}</option>`).join('')}</select></label><p class="dialog-hint">A pergunta antiga será arquivada somente depois que as condições forem redirecionadas.</p>` : '';
    dialog.querySelector('[data-impact-content]').innerHTML = `<h2>Esta pergunta é usada em ${uses.length} ${uses.length === 1 ? 'ação' : 'ações'}</h2><p>Alterar tipo, opções, valor interno ou remover a pergunta pode mudar a jornada.</p><ul class="impact-list">${links}</ul>${replacementHtml}`;
    const confirmed = await new Promise(resolve => {
      dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'));
      dialog.querySelector('[data-impact-confirm]').addEventListener('click', event => {
        replacement = dialog.querySelector('[data-impact-replacement]')?.value || '';
        if (mode === 'archive' && !replacement) { event.preventDefault(); dialog.querySelector('[data-impact-replacement]')?.focus(); }
      });
      dialog.showModal();
    });
    dialog.remove(); return {confirmed, replacementId:replacement};
  }

  function optionData(row) {
    const label = row.querySelector('.option-label').value.trim();
    const value = row.querySelector('.option-value').value.trim();
    return {...(row._optionData || {}), id:row.dataset.optionId, label, value:value || label, segment_id:Number(row.querySelector('.option-segment').value || 0) || null, creates_alert:row.querySelector('.option-alert').checked};
  }
  function optionRow(data = {}) {
    const row = document.createElement('div');
    row.className = 'option-row'; row.dataset.optionRow = '1'; row.dataset.optionId = String(data.id || clientKey('option')); row._optionData = {...data, id:row.dataset.optionId};
    row.innerHTML = `<button type="button" class="option-drag-handle" title="Arrastar opção" aria-label="Reordenar opção">⋮⋮</button><label>Texto<input class="option-label" placeholder="Ex.: Muito bom" value="${esc(data.label || '')}"></label><label data-advanced-only>Valor interno<input class="option-value" placeholder="muito_bom" value="${esc(data.value || '')}"></label><label data-advanced-only>Segmento<select class="option-segment">${segmentOptions(data.segment_id || (data.segment_ids || [])[0])}</select></label><label class="mini-check" data-advanced-only title="Criar alerta"><input type="checkbox" class="option-alert" ${data.creates_alert ? 'checked' : ''}><span>Alerta</span></label><div class="option-order-buttons"><button type="button" data-option-up title="Mover opção para cima">↑</button><button type="button" data-option-down title="Mover opção para baixo">↓</button><button type="button" data-duplicate-option title="Duplicar opção">⧉</button><button type="button" class="remove-option" title="Remover opção">×</button></div>`;
    const move = direction => {
      const parent = row.closest('[data-options-list]'); if (!parent) return;
      if (direction < 0 && row.previousElementSibling) parent.insertBefore(row, row.previousElementSibling);
      else if (direction > 0 && row.nextElementSibling) parent.insertBefore(row.nextElementSibling, row); else return;
      markDirty(); announce('Opção reordenada.');
    };
    row.querySelector('[data-option-up]').addEventListener('click', () => move(-1));
    row.querySelector('[data-option-down]').addEventListener('click', () => move(1));
    row.querySelector('.remove-option').addEventListener('click', () => { row.remove(); markDirty(); });
    row.querySelector('[data-duplicate-option]').addEventListener('click', () => { const duplicate = optionRow({...optionData(row), id:clientKey('option')}); row.after(duplicate); markDirty(); duplicate.querySelector('.option-label').focus(); });
    row.querySelector('.option-drag-handle').addEventListener('keydown', event => { if (!['ArrowUp','ArrowDown'].includes(event.key)) return; event.preventDefault(); move(event.key === 'ArrowUp' ? -1 : 1); });
    row.querySelector('.option-drag-handle').addEventListener('pointerdown', () => { row.draggable = true; });
    row.addEventListener('dragstart', event => { if (!row.draggable) { event.preventDefault(); return; } event.stopPropagation(); row.classList.add('is-dragging'); });
    row.addEventListener('dragover', event => { const parent = row.closest('[data-options-list]'); const dragged = parent?.querySelector('.option-row.is-dragging'); if (!dragged || dragged === row) return; event.preventDefault(); event.stopPropagation(); const rect = row.getBoundingClientRect(); parent.insertBefore(dragged, event.clientY < rect.top + rect.height / 2 ? row : row.nextSibling); });
    row.addEventListener('dragend', event => { event.stopPropagation(); row.classList.remove('is-dragging'); row.draggable = false; markDirty(); announce('Opção reordenada.'); });
    return row;
  }

  function questionCard(data = {}) {
    const card = document.createElement('article');
    card.className = 'question-card'; card._data = normalizedQuestion(data);
    card.dataset.questionId = card._data.id || ''; card.dataset.itemKey = card._data.item_key; card.dataset.archived = card._data.archived ? '1' : '0'; card.dataset.replacementQuestionId = card._data.replacement_question_id || '';
    card.innerHTML = `<button type="button" class="drag-handle" data-question-drag-handle title="Arrastar para reordenar. Use as setas do teclado." aria-label="Reordenar pergunta">⋮⋮</button><button type="button" class="question-card-select" data-select-question><span class="question-number">1</span><span class="question-card-copy"><strong>${esc(card._data.text || 'Pergunta sem texto')}</strong><small><b>${esc(typeLabels[card._data.type] || card._data.type)}</b><i>${card._data.required ? 'Obrigatória' : 'Opcional'}</i><i data-dependency-indicator ${card._data.data_binding || impactRows(card).length ? '' : 'hidden'}>Vínculo</i></small></span><span class="question-error-badge" data-question-error hidden>!</span></button><div class="question-card-actions"><button type="button" data-up title="Mover para cima" aria-label="Mover pergunta para cima">↑</button><button type="button" data-down title="Mover para baixo" aria-label="Mover pergunta para baixo">↓</button><button type="button" data-remove title="Arquivar pergunta" aria-label="Arquivar pergunta">×</button></div>`;
    card.querySelector('[data-select-question]').addEventListener('click', () => selectCard(card));
    card.querySelector('[data-up]').addEventListener('click', () => moveQuestion(card, -1));
    card.querySelector('[data-down]').addEventListener('click', () => moveQuestion(card, 1));
    card.querySelector('[data-remove]').addEventListener('click', async () => {
      if (card._data.archived) { card._data.archived = false; card._data.replacement_question_id = null; }
      else if (card._data.id) { const decision = await confirmImpact(card, 'archive'); if (!decision.confirmed) return; card._data.archived = true; card._data.replacement_question_id = Number(decision.replacementId || 0) || null; }
      else { if (selectedCard === card) selectedCard = null; card.remove(); renderPlaceholder(); renumber(); markDirty(); return; }
      updateCard(card); if (selectedCard === card) renderDetail(card); renumber(); markDirty();
    });
    card.querySelector('[data-question-drag-handle]').addEventListener('keydown', event => { if (!['ArrowUp','ArrowDown'].includes(event.key)) return; event.preventDefault(); moveQuestion(card, event.key === 'ArrowUp' ? -1 : 1); });
    card.querySelector('[data-question-drag-handle]').addEventListener('pointerdown', () => { card.draggable = true; });
    return card;
  }

  function updateCard(card) {
    const data = card._data;
    card.dataset.archived = data.archived ? '1' : '0'; card.dataset.replacementQuestionId = data.replacement_question_id || '';
    card.classList.toggle('question-archived', data.archived);
    card.querySelector('.question-card-copy strong').textContent = data.text || 'Pergunta sem texto';
    const parts = card.querySelectorAll('.question-card-copy small > *');
    parts[0].textContent = typeLabels[data.type] || data.type; parts[1].textContent = data.required ? 'Obrigatória' : 'Opcional';
    const dependency = card.querySelector('[data-dependency-indicator]');
    const dependencyLabels = [];
    if (data.data_binding || impactRows(card).length) dependencyLabels.push('Vínculo');
    if (data.settings?.visibility?.enabled) dependencyLabels.push('Condição');
    dependency.textContent = dependencyLabels.join(' · '); dependency.hidden = !dependencyLabels.length;
    const remove = card.querySelector('[data-remove]'); remove.textContent = data.archived ? '↺' : '×'; remove.title = data.archived ? 'Restaurar pergunta' : 'Arquivar pergunta';
  }

  function renderPlaceholder() {
    detail.innerHTML = '<div class="question-detail-placeholder"><span>←</span><h3>Selecione uma pergunta</h3><p>A configuração completa aparecerá aqui sem ocupar toda a página.</p></div>';
    document.querySelector('.questions-workspace')?.classList.remove('detail-open');
  }

  function typeSpecificMarkup(data) {
    const s = data.settings || {};
    if (data.type === 'text') return `<div class="type-specific-grid"><label>Formato<select data-setting="text_format"><option value="short" ${s.text_format !== 'long' ? 'selected' : ''}>Resposta curta</option><option value="long" ${s.text_format === 'long' ? 'selected' : ''}>Resposta longa</option></select></label><label>Limite de caracteres<input type="number" min="1" data-setting="max_length" value="${esc(s.max_length || '')}" placeholder="Sem limite"></label><label class="span-2">Placeholder<div class="placeholder-enabled-field"><input data-setting="placeholder" value="${esc(s.placeholder || '')}" placeholder="Texto mostrado antes da resposta"><button type="button" class="placeholder-insert-button" data-open-placeholder aria-label="Inserir variável no placeholder" title="Inserir variável">{{…}}</button></div></label><label data-advanced-only>Validação<select data-setting="validation"><option value="none">Nenhuma</option><option value="email" ${s.validation === 'email' ? 'selected' : ''}>E-mail</option><option value="phone" ${s.validation === 'phone' ? 'selected' : ''}>Telefone</option><option value="number" ${s.validation === 'number' ? 'selected' : ''}>Número</option></select></label></div>`;
    if (['choice','multiple_choice'].includes(data.type)) return `<div class="type-specific-grid">${data.type === 'multiple_choice' ? `<label>Mínimo de escolhas<input type="number" min="0" data-setting="min_selections" value="${esc(s.min_selections ?? (data.required ? 1 : 0))}"></label><label>Máximo de escolhas<input type="number" min="1" data-setting="max_selections" value="${esc(s.max_selections || Math.max(1, data.options.length))}"></label>` : ''}<label data-advanced-only>Apresentação<select data-setting="presentation"><option value="auto">Automática</option><option value="buttons" ${s.presentation === 'buttons' ? 'selected' : ''}>Botões</option><option value="list" ${s.presentation === 'list' ? 'selected' : ''}>Lista</option><option value="select" ${s.presentation === 'select' ? 'selected' : ''}>Seletor</option></select></label><label class="check-card compact" data-advanced-only><input type="checkbox" data-setting="allow_other" ${s.allow_other ? 'checked' : ''}><span><strong>Permitir “Outro”</strong></span></label><label class="check-card compact" data-advanced-only><input type="checkbox" data-setting="shuffle_options" ${s.shuffle_options ? 'checked' : ''}><span><strong>Embaralhar opções</strong></span></label></div>`;
    if (data.type === 'score') return `<div class="type-specific-grid"><label>Mínimo<input type="number" class="min-score" value="${esc(data.min_score)}"></label><label>Máximo<input type="number" class="max-score" value="${esc(data.max_score)}"></label><label>Rótulo inicial<input data-setting="min_label" value="${esc(s.min_label || '')}" placeholder="Pouco satisfeito"></label><label>Rótulo final<input data-setting="max_label" value="${esc(s.max_label || '')}" placeholder="Muito satisfeito"></label><label data-advanced-only>Visualização<select data-setting="score_visualization"><option value="numbers">Números</option><option value="slider" ${s.score_visualization === 'slider' ? 'selected' : ''}>Controle deslizante</option></select></label></div>`;
    if (data.type === 'stars') return `<div class="type-specific-grid"><label>Quantidade de estrelas<input type="number" min="2" max="10" class="max-score" data-setting="star_count" value="${esc(s.star_count || data.max_score || 5)}"></label><input type="hidden" class="min-score" value="1"><label>Rótulo inicial<input data-setting="min_label" value="${esc(s.min_label || '')}" placeholder="Ruim"></label><label>Rótulo final<input data-setting="max_label" value="${esc(s.max_label || '')}" placeholder="Excelente"></label></div>`;
    if (mediaTypes.has(data.type)) return `<div class="type-specific-grid"><label>Formato esperado<input data-setting="media_formats" value="${esc(s.media_formats || typeLabels[data.type])}" ${data.type !== 'multiple_files' ? 'readonly' : ''}></label><label>Tamanho máximo (MB)<input type="number" min="1" data-setting="max_size_mb" value="${esc(s.max_size_mb || 50)}"></label><label>Quantidade máxima<input type="number" min="1" data-setting="max_files" value="${esc(s.max_files || 1)}"></label><label class="check-card compact"><input type="checkbox" data-setting="caption_enabled" ${s.caption_enabled ? 'checked' : ''}><span><strong>Aceitar legenda</strong></span></label>${data.type === 'location' ? `<label class="check-card compact"><input type="checkbox" data-setting="allow_manual_address" ${s.allow_manual_address ? 'checked' : ''}><span><strong>Permitir endereço manual</strong></span></label><label class="span-2">Texto explicativo<input data-setting="explanatory_text" value="${esc(s.explanatory_text || '')}" placeholder="Explique como compartilhar a localização"></label>` : ''}</div>`;
    return '<div class="notice-box">Este tipo não precisa de configurações adicionais.</div>';
  }

  function previousQuestionCards(card) {
    const cards = [...list.children];
    return cards.slice(0, Math.max(0, cards.indexOf(card))).filter(item => !item._data.archived);
  }

  function conditionSource(card, sourceKey) {
    return previousQuestionCards(card).find(item => item._data.item_key === sourceKey || `question:${item._data.id}` === sourceKey) || null;
  }

  function conditionValueMarkup(source, operator, value, valueMax) {
    if (['answered','not_answered'].includes(operator)) return '<p class="condition-value-note">Esta regra não precisa de um valor.</p>';
    if (operator === 'between') return `<div class="condition-value-range"><label>Nota mínima<input type="number" step="0.1" class="condition-value" value="${esc(value || '')}" placeholder="Mínimo"></label><label>Nota máxima<input type="number" step="0.1" class="condition-value-max" value="${esc(valueMax || '')}" placeholder="Máximo"></label></div>`;
    if (numericConditionOperators.has(operator)) return `<label>Nota<input type="number" step="0.1" class="condition-value" value="${esc(value || '')}" placeholder="Digite a nota"></label>`;
    if (source?._data.type === 'yes_no') return `<label>Resposta<select class="condition-value"><option value="sim" ${normalize(value) === 'sim' ? 'selected' : ''}>Sim</option><option value="não" ${['não','nao'].includes(normalize(value)) ? 'selected' : ''}>Não</option></select></label>`;
    if (['choice','multiple_choice'].includes(source?._data.type)) {
      const rows = source._data.options || [];
      return `<label>Resposta<select class="condition-value"><option value="">Selecione...</option>${rows.filter(item => item.label).map(item => { const optionValue = String(item.value || item.label); return `<option value="${esc(optionValue)}" ${normalize(optionValue) === normalize(value) ? 'selected' : ''}>${esc(item.label)}</option>`; }).join('')}</select></label>`;
    }
    return `<label>Resposta esperada<input class="condition-value" value="${esc(value || '')}" placeholder="Digite o texto para comparar"></label>`;
  }

  function conditionMarkup(card, data) {
    const rule = data.settings?.visibility || {};
    const previous = previousQuestionCards(card);
    const sourceKey = String(rule.source_item_key || (rule.source_question_id ? `question:${rule.source_question_id}` : ''));
    const source = conditionSource(card, sourceKey);
    const effectiveKey = source ? source._data.item_key : '';
    const operators = conditionOperators[source?._data.type] || conditionOperators.default;
    const operator = operators.some(item => item[0] === rule.operator) ? rule.operator : operators[0][0];
    return `<section class="question-condition-card ${rule.enabled ? 'enabled' : ''}" data-question-condition>
      <div class="question-condition-head"><div><strong>Exibição condicional</strong><small>Mostre esta pergunta somente conforme uma resposta anterior.</small></div><label class="switch-label"><input type="checkbox" class="condition-enabled" ${rule.enabled ? 'checked' : ''} ${previous.length ? '' : 'disabled'}> Ativar condição</label></div>
      ${previous.length ? `<div class="question-condition-fields" ${rule.enabled ? '' : 'hidden'}><label>Pergunta anterior<select class="condition-source"><option value="">Selecione...</option>${previous.map((item,index) => `<option value="${esc(item._data.item_key)}" ${item._data.item_key === effectiveKey ? 'selected' : ''}>${index + 1}. ${esc(item._data.text || 'Pergunta sem texto')}</option>`).join('')}</select></label><label>Regra<select class="condition-operator">${operators.map(item => `<option value="${item[0]}" ${item[0] === operator ? 'selected' : ''}>${item[1]}</option>`).join('')}</select></label><div data-condition-value>${conditionValueMarkup(source, operator, rule.value || '', rule.value_max || '')}</div></div>` : '<p class="condition-unavailable">Adicione uma pergunta antes desta para criar uma condição.</p>'}
    </section>`;
  }

  function refreshConditionEditor(card, preserveValue = true) {
    const box = detail.querySelector('[data-question-condition]'); if (!box) return;
    const sourceKey = box.querySelector('.condition-source')?.value || '';
    const source = conditionSource(card, sourceKey);
    const currentOperator = box.querySelector('.condition-operator')?.value || 'equals';
    const currentValue = preserveValue ? box.querySelector('.condition-value')?.value || '' : '';
    const currentValueMax = preserveValue ? box.querySelector('.condition-value-max')?.value || '' : '';
    const operators = conditionOperators[source?._data.type] || conditionOperators.default;
    const operator = operators.some(item => item[0] === currentOperator) ? currentOperator : operators[0][0];
    const operatorSelect = box.querySelector('.condition-operator');
    if (operatorSelect) operatorSelect.innerHTML = operators.map(item => `<option value="${item[0]}" ${item[0] === operator ? 'selected' : ''}>${item[1]}</option>`).join('');
    const target = box.querySelector('[data-condition-value]'); if (target) target.innerHTML = conditionValueMarkup(source, operator, currentValue, currentValueMax);
  }

  function renderDetail(card) {
    if (!card || !card.isConnected) { renderPlaceholder(); return; }
    const data = card._data;
    if (data.archived) {
      detail.innerHTML = `<div class="question-detail-placeholder archived"><span>↺</span><h3>Pergunta marcada para arquivamento</h3><p>Ela continuará no histórico. Restaure para voltar a editar.</p><button type="button" class="btn secondary" data-restore-question>Restaurar pergunta</button></div>`;
      detail.querySelector('[data-restore-question]').addEventListener('click', () => card.querySelector('[data-remove]').click()); return;
    }
    detail.innerHTML = `<div class="question-detail-head"><button type="button" class="btn ghost back-to-outline" data-back-outline>← Perguntas</button><div><span class="eyebrow">PERGUNTA <b data-selected-position></b></span><h3>${esc(data.text || 'Pergunta sem texto')}</h3></div>${impactRows(card).length ? `<button type="button" class="impact-badge" data-show-impact>Usada em ${impactRows(card).length} ação(ões)</button>` : ''}</div><div class="question-detail-form">
      <div class="question-basic-grid"><label class="span-2">Texto da pergunta<div class="placeholder-enabled-field"><textarea class="question-text" rows="3" placeholder="O que você deseja perguntar?">${esc(data.text)}</textarea><button type="button" class="placeholder-insert-button" data-open-placeholder aria-label="Inserir variável na pergunta" title="Inserir variável">{{…}}</button></div></label><label>Tipo<select class="question-type">${typeOptions}</select></label><label class="required-line"><input type="checkbox" class="question-required" ${data.required ? 'checked' : ''}> Obrigatória</label></div>
      <div class="type-specific" data-type-specific>${typeSpecificMarkup(data)}</div>
      <div class="options-editor" data-options-editor ${['choice','multiple_choice'].includes(data.type) ? '' : 'hidden'}><div class="options-editor-title"><div><strong>Opções de resposta</strong><small>Valores internos e regras permanecem ligados à identidade de cada opção.</small></div><button type="button" class="btn ghost" data-add-option>+ Opção</button></div><div data-options-list></div></div>
      ${conditionMarkup(card, data)}
      <details class="question-advanced advanced-disclosure"><summary>Configurações avançadas desta pergunta</summary><div class="form-grid"><label class="span-2">Texto auxiliar<div class="placeholder-enabled-field"><input class="question-help" value="${esc(data.help_text)}" placeholder="Orientação opcional para quem responde"><button type="button" class="placeholder-insert-button" data-open-placeholder aria-label="Inserir variável no texto auxiliar" title="Inserir variável">{{…}}</button></div></label><label>Resposta no WhatsApp<select class="whatsapp-response-mode"><option value="auto">Automático</option><option value="buttons">Botões Z-API</option><option value="option_list">Lista Z-API</option><option value="numbered_text">Texto numerado</option><option value="text">Texto livre</option></select></label><label class="registration-binding">Usar resposta como<select class="question-binding">${bindingOptions(data.data_binding)}</select></label><label>Nota baixa até<input type="number" step="0.1" class="low-threshold" value="${esc(data.low_score_threshold)}" placeholder="Sem regra"></label><label>Segmento nota baixa<select class="segment-low">${segmentOptions(data.segment_low_id)}</select></label><label>Segmento nota alta<select class="segment-high">${segmentOptions(data.segment_high_id)}</select></label><label class="span-2">Metadados internos<textarea data-setting="metadata" rows="2" placeholder="Observações técnicas ou JSON">${esc(data.settings.metadata || '')}</textarea></label><label class="span-2">Regras especiais<textarea data-setting="special_rules" rows="2" placeholder="Documente uma regra especial">${esc(data.settings.special_rules || '')}</textarea></label></div></details>
    </div>`;
    detail.querySelector('.question-type').value = data.type;
    detail.querySelector('.whatsapp-response-mode').value = data.whatsapp_response_mode;
    detail.querySelector('[data-selected-position]').textContent = [...list.children].indexOf(card) + 1;
    data.options.forEach(option => detail.querySelector('[data-options-list]').appendChild(optionRow(option)));
    if (['choice','multiple_choice'].includes(data.type) && !data.options.length) { detail.querySelector('[data-options-list]').append(optionRow(), optionRow()); }
    detail.querySelector('[data-add-option]')?.addEventListener('click', () => { detail.querySelector('[data-options-list]').appendChild(optionRow()); markDirty(); });
    detail.querySelector('.question-type').addEventListener('change', () => { saveCurrent(); renderDetail(card); updateCard(card); markDirty(); });
    detail.querySelector('[data-back-outline]').addEventListener('click', () => document.querySelector('.questions-workspace')?.classList.remove('detail-open'));
    detail.querySelector('[data-show-impact]')?.addEventListener('click', () => confirmImpact(card));
    detail.querySelector('.condition-enabled')?.addEventListener('change', event => { const fields = detail.querySelector('.question-condition-fields'); if (fields) fields.hidden = !event.target.checked; detail.querySelector('[data-question-condition]')?.classList.toggle('enabled', event.target.checked); markDirty(); });
    detail.querySelector('.condition-source')?.addEventListener('change', () => { refreshConditionEditor(card, false); markDirty(); });
    detail.querySelector('.condition-operator')?.addEventListener('change', () => { refreshConditionEditor(card, true); markDirty(); });
    let impactPrompting = false;
    detail.querySelector('.question-detail-form').addEventListener('focusin', async event => {
      if (!impactRows(card).length || card.dataset.impactApproved === '1' || impactPrompting) return;
      impactPrompting = true; const target = event.target; target.blur(); const decision = await confirmImpact(card, 'edit');
      if (decision.confirmed) { card.dataset.impactApproved = '1'; target.focus(); }
      impactPrompting = false;
    });
  }

  function saveCurrent() {
    if (!selectedCard || !selectedCard.isConnected || selectedCard._data.archived) return;
    const panel = detail.querySelector('.question-detail-form'); if (!panel) return;
    const data = selectedCard._data;
    data.text = panel.querySelector('.question-text')?.value.trim() || '';
    data.type = panel.querySelector('.question-type')?.value || data.type;
    data.required = Boolean(panel.querySelector('.question-required')?.checked);
    data.help_text = panel.querySelector('.question-help')?.value.trim() || '';
    data.options = ['choice','multiple_choice'].includes(data.type) ? [...panel.querySelectorAll('[data-option-row]')].map(optionData) : data.options;
    data.min_score = panel.querySelector('.min-score')?.value ?? data.min_score;
    data.max_score = panel.querySelector('.max-score')?.value ?? data.max_score;
    data.low_score_threshold = panel.querySelector('.low-threshold')?.value ?? data.low_score_threshold;
    data.segment_low_id = Number(panel.querySelector('.segment-low')?.value || 0) || null;
    data.segment_high_id = Number(panel.querySelector('.segment-high')?.value || 0) || null;
    data.whatsapp_response_mode = panel.querySelector('.whatsapp-response-mode')?.value || 'auto';
    data.data_binding = panel.querySelector('.question-binding')?.value || '';
    panel.querySelectorAll('[data-setting]').forEach(field => { data.settings[field.dataset.setting] = field.type === 'checkbox' ? field.checked : field.value; });
    const conditionEnabled = Boolean(panel.querySelector('.condition-enabled')?.checked);
    if (conditionEnabled) {
      const sourceKey = panel.querySelector('.condition-source')?.value || '';
      const source = conditionSource(selectedCard, sourceKey);
      const conditionOperator = panel.querySelector('.condition-operator')?.value || 'equals';
      data.settings.visibility = {enabled:true, source_item_key:sourceKey, source_question_id:source?._data.id || null, operator:conditionOperator, value:panel.querySelector('.condition-value')?.value || ''};
      if (conditionOperator === 'between') data.settings.visibility.value_max = panel.querySelector('.condition-value-max')?.value || '';
    } else delete data.settings.visibility;
    if (data.type === 'stars') { data.min_score = 1; data.max_score = data.settings.star_count || data.max_score; }
    updateCard(selectedCard);
  }

  function selectCard(card) {
    if (selectedCard !== card) saveCurrent();
    selectedCard = card; [...list.children].forEach(item => item.classList.toggle('is-selected', item === card));
    renderDetail(card); document.querySelector('.questions-workspace')?.classList.add('detail-open');
  }
  function addQuestion(data = {}, shouldFocus = true) {
    saveCurrent(); const card = questionCard(data); list.appendChild(card); renumber(); selectCard(card); markDirty();
    if (shouldFocus) detail.querySelector('.question-text')?.focus();
    return card;
  }
  function moveQuestion(card, direction) {
    saveCurrent();
    if (direction < 0 && card.previousElementSibling) list.insertBefore(card, card.previousElementSibling);
    else if (direction > 0 && card.nextElementSibling) list.insertBefore(card.nextElementSibling, card); else return;
    renumber(); selectCard(card); markDirty(); announce(`Pergunta movida para a posição ${[...list.children].indexOf(card) + 1}.`);
  }
  function renumber() {
    [...list.children].forEach((card, index) => { card.querySelector('.question-number').textContent = index + 1; card.querySelector('[data-question-drag-handle]').setAttribute('aria-label', `Reordenar pergunta ${index + 1}`); card.querySelector('[data-up]').disabled = index === 0; card.querySelector('[data-down]').disabled = index === list.children.length - 1; });
    const activeCount = [...list.children].filter(card => !card._data.archived).length;
    empty.hidden = activeCount > 0; document.querySelector('[data-question-count]').textContent = activeCount; updatePublicationSummary();
  }

  document.querySelectorAll('[data-add-question]').forEach(button => button.addEventListener('click', () => addQuestion({type:'text'})));
  initial.forEach(item => { const card = questionCard(item); list.appendChild(card); });
  renumber(); if (list.firstElementChild) selectCard(list.firstElementChild); else renderPlaceholder();

  list.addEventListener('dragstart', event => { const card = event.target.closest('.question-card'); if (!card || !card.draggable) { event.preventDefault(); return; } saveCurrent(); draggedQuestion = card; card.classList.add('is-dragging'); event.dataTransfer.effectAllowed = 'move'; });
  list.addEventListener('dragover', event => { if (!draggedQuestion) return; event.preventDefault(); const target = event.target.closest('.question-card'); if (!target || target === draggedQuestion) return; const rect = target.getBoundingClientRect(); list.insertBefore(draggedQuestion, event.clientY < rect.top + rect.height / 2 ? target : target.nextSibling); });
  list.addEventListener('dragend', () => { if (!draggedQuestion) return; const moved = draggedQuestion; moved.classList.remove('is-dragging'); moved.draggable = false; draggedQuestion = null; renumber(); selectCard(moved); markDirty(); announce(`Pergunta movida para a posição ${[...list.children].indexOf(moved) + 1}.`); });

  function collectQuestions() { saveCurrent(); return [...list.children].map(card => ({...card._data, replacement_question_id:card._data.replacement_question_id || null})); }

  function openTab(name) {
    const target = form.querySelector(`[data-editor-tab="${name}"]`);
    if (!target || target.hidden) return;
    form.querySelectorAll('[data-editor-tab]').forEach(button => { const active = button === target; button.classList.toggle('active', active); button.setAttribute('aria-selected', String(active)); });
    form.querySelectorAll('[data-editor-panel]').forEach(panel => { const active = panel.dataset.editorPanel === name; panel.hidden = !active; panel.classList.toggle('active', active); });
    history.replaceState(null, '', `#${target.dataset.editorTab}`);
  }
  form.querySelectorAll('[data-editor-tab]').forEach(button => button.addEventListener('click', () => openTab(button.dataset.editorTab)));
  document.querySelectorAll('[data-tab-link]').forEach(link => link.addEventListener('click', () => openTab(link.dataset.tabLink)));

  function setEditorMode(mode) {
    saveCurrent();
    form.dataset.editMode = mode;
    form.querySelectorAll('[data-editor-mode]').forEach(button => button.classList.toggle('active', button.dataset.editorMode === mode));
    form.querySelectorAll('[data-editor-tab][data-advanced-only]').forEach(button => { button.hidden = mode !== 'advanced'; });
    if (mode === 'simple' && form.querySelector('[data-editor-panel].active')?.hasAttribute('data-advanced-only')) openTab('general');
    if (selectedCard) renderDetail(selectedCard);
  }
  form.querySelectorAll('[data-editor-mode]').forEach(button => button.addEventListener('click', () => setEditorMode(button.dataset.editorMode)));
  setEditorMode('simple');

  function clearErrors() {
    form.querySelectorAll('.field-error').forEach(item => item.classList.remove('field-error'));
    form.querySelectorAll('.editor-inline-error').forEach(item => item.remove());
    form.querySelectorAll('[data-question-error]').forEach(item => { item.hidden = true; });
    document.querySelector('[data-error-summary]')?.remove();
  }
  function cardFor(error) { return error.item_key ? [...list.children].find(card => card._data.item_key === error.item_key) : null; }
  function fieldFor(error) {
    const card = cardFor(error);
    if (card) {
      if (selectedCard !== card) selectCard(card);
      if (['data_binding','low_score_threshold','segment_low_id','segment_high_id'].includes(error.field)) detail.querySelector('.question-advanced')?.setAttribute('open', '');
      const map = {text:'.question-text',type:'.question-type',data_binding:'.question-binding',options:'[data-options-editor]',min_score:'.min-score',max_score:'.max-score',low_score_threshold:'.low-threshold',min_selections:'[data-setting="min_selections"]',max_selections:'[data-setting="max_selections"]',condition_source:'.condition-source',condition_operator:'.condition-operator',condition_value:'.condition-value',replacement_question_id:'[data-remove]'};
      if (error.field.startsWith('option_label_')) return detail.querySelectorAll('.option-label')[Number(error.field.split('_').pop())] || card;
      if (error.field.startsWith('option_value_')) return detail.querySelectorAll('.option-value')[Number(error.field.split('_').pop())] || card;
      return detail.querySelector(map[error.field] || `[data-field="${error.field}"]`) || card;
    }
    return form.querySelector(`[name="${CSS.escape(error.field)}"]`) || form.querySelector(`[data-field-group="${CSS.escape(error.field)}"]`) || document.querySelector(`#${error.section}`);
  }
  function showErrors(errors) {
    clearErrors(); if (!errors.length) return;
    const firstSection = sectionTabs[errors[0].section] || 'general';
    if (['logic','segments'].includes(firstSection)) setEditorMode('advanced');
    openTab(firstSection);
    const box = document.createElement('div'); box.className = 'editor-error-summary'; box.dataset.errorSummary = '1'; box.tabIndex = -1; box.setAttribute('role','alert');
    box.innerHTML = `<strong>Revise ${errors.length} ${errors.length === 1 ? 'campo' : 'campos'} antes de salvar.</strong><ul>${errors.map(item => `<li><a href="#${esc(item.section)}">${esc(item.message)}</a></li>`).join('')}</ul>`;
    form.querySelector('.questionnaire-tabpanels').before(box);
    errors.forEach(error => { const card = cardFor(error); if (card) card.querySelector('[data-question-error]').hidden = false; const target = fieldFor(error); if (!target) return; target.classList.add('field-error'); const message = document.createElement('small'); message.className = 'editor-inline-error'; message.textContent = error.message; (target.closest('label') || target).appendChild(message); });
    const first = fieldFor(errors[0]); (first || box).scrollIntoView({behavior:'smooth', block:'center'}); box.focus({preventScroll:true});
  }

  function validate(questions) {
    const errors = []; const add = (section, field, message, item_key = '') => errors.push({section, field, message, item_key});
    if (!form.elements.name.value.trim()) add('identity','name','Informe o nome do questionário.');
    const selectedChannels = [...form.querySelectorAll('input[name="channels"]:checked')].map(item => item.value);
    if (!selectedChannels.length) add('audience','channels','Selecione pelo menos um canal.');
    if (form.elements.response_mode.value === 'anonymous' && selectedChannels.includes('whatsapp')) add('audience','channels','Pesquisas anônimas não podem usar WhatsApp.');
    if (selectedChannels.includes('whatsapp') && !form.elements.opening_message.value.trim()) add('audience','opening_message','Informe a mensagem de abertura do WhatsApp.');
    if (!form.elements.closing_message.value.trim()) add('audience','closing_message','Informe a mensagem de encerramento.');
    if (form.elements.audience_type.value === 'segment' && !form.elements.target_segment_id.value) add('audience','target_segment_id','Selecione um segmento ativo para esta pesquisa.');
    const randomPercent = Number(form.elements.random_percent.value), sendHour = Number(form.elements.send_hour.value);
    if (!Number.isInteger(randomPercent) || randomPercent < 1 || randomPercent > 100) add('audience','random_percent','A amostra deve ficar entre 1% e 100%.');
    if (!Number.isInteger(sendHour) || sendHour < 0 || sendHour > 23) add('trigger','send_hour','A hora preferencial deve ficar entre 0 e 23.');
    if (Number(form.elements.delay_value.value) < 0) add('trigger','delay_value','O tempo de espera não pode ser negativo.');
    const recurrence = form.elements.recurrence_days.value;
    if (recurrence !== '' && (!Number.isInteger(Number(recurrence)) || Number(recurrence) < 1)) add('actions','recurrence_days','A recorrência deve ser de pelo menos um dia.');
    if (Number(form.elements.max_attempts.value) < 1) add('actions','max_attempts','Informe pelo menos uma tentativa.');
    if (Number(form.elements.retry_hours.value) < 1) add('actions','retry_hours','O intervalo deve ser de pelo menos uma hora.');
    const active = questions.filter(item => !item.archived); if (!active.length) add('questions','questions_json','Adicione pelo menos uma pergunta ativa.');
    const bindings = [], questionKeys = new Set(), optionKeys = new Set();
    const priorQuestions = new Map();
    questions.forEach((item, index) => {
      if (questionKeys.has(item.item_key)) add('questions','item_key','Duas perguntas estão usando a mesma identidade interna.',item.item_key); questionKeys.add(item.item_key);
      if (item.archived) { if ((impacts[String(item.id)] || []).length && !item.replacement_question_id) add('questions','replacement_question_id',`Esta pergunta é utilizada em ${impacts[String(item.id)].length} ações. Escolha uma substituta.`,item.item_key); return; }
      if (!item.text) add('questions','text',`A pergunta ${index + 1} está sem texto.`,item.item_key);
      const rule = item.settings?.visibility;
      if (rule?.enabled) {
        const source = priorQuestions.get(rule.source_item_key) || priorQuestions.get(`question:${rule.source_question_id}`);
        if (!source) add('questions','condition_source','Escolha uma pergunta anterior do mesmo questionário para a condição.',item.item_key);
        if (!['answered','not_answered','equals','not_equals','contains','not_contains','gte','lte','between'].includes(rule.operator)) add('questions','condition_operator','Escolha uma regra válida para a condição.',item.item_key);
        if (numericConditionOperators.has(rule.operator)) {
          if (source && !['score','stars'].includes(source.type)) add('questions','condition_source','Condições numéricas só podem usar uma pergunta de nota ou estrelas como origem.',item.item_key);
          if (rule.value === '' || rule.value === undefined || rule.value === null || Number.isNaN(Number(rule.value))) add('questions','condition_value','Informe um número para esta condição.',item.item_key);
          if (rule.operator === 'between') {
            if (rule.value_max === '' || rule.value_max === undefined || rule.value_max === null || Number.isNaN(Number(rule.value_max))) add('questions','condition_value','Informe o valor máximo da faixa.',item.item_key);
            else if (Number(rule.value_max) < Number(rule.value)) add('questions','condition_value','O valor máximo deve ser maior ou igual ao mínimo.',item.item_key);
          }
        } else if (!['answered','not_answered'].includes(rule.operator) && !String(rule.value || '').trim()) add('questions','condition_value','Informe ou selecione a resposta que libera esta pergunta.',item.item_key);
        if (source && ['equals','not_equals'].includes(rule.operator) && ['choice','multiple_choice','yes_no'].includes(source.type)) {
          const allowed = source.type === 'yes_no' ? ['sim','não','nao'] : (source.options || []).map(option => normalize(option.value || option.label));
          if (!allowed.includes(normalize(rule.value))) add('questions','condition_value','Selecione uma resposta disponível na pergunta anterior.',item.item_key);
        }
      }
      if (item.data_binding) bindings.push([item.data_binding,item.item_key]);
      if (['choice','multiple_choice'].includes(item.type)) {
        const filled = item.options.filter(option => option.label), labels = new Set(), values = new Set();
        item.options.forEach((option, optionIndex) => { if (optionKeys.has(option.id)) add('questions',`option_label_${optionIndex}`,'Duas opções estão usando a mesma identidade interna.',item.item_key); optionKeys.add(option.id); if (!option.label) add('questions',`option_label_${optionIndex}`,`Preencha o texto da opção ${optionIndex + 1}.`,item.item_key); const label = normalize(option.label), value = normalize(option.value || option.label); if (label && labels.has(label)) add('questions',`option_label_${optionIndex}`,`A opção "${option.label}" está duplicada.`,item.item_key); if (value && values.has(value)) add('questions',`option_value_${optionIndex}`,`O valor interno "${option.value || option.label}" está duplicado.`,item.item_key); labels.add(label); values.add(value); });
        if (filled.length < 2) add('questions','options',`A pergunta ${index + 1} precisa de pelo menos duas opções preenchidas.`,item.item_key);
        if (item.type === 'multiple_choice') { const min = Number(item.settings.min_selections ?? (item.required ? 1 : 0)), max = Number(item.settings.max_selections || item.options.length); if (!Number.isInteger(min) || min < 0) add('questions','min_selections','O mínimo de escolhas não pode ser negativo.',item.item_key); if (!Number.isInteger(max) || max < 1 || min > max) add('questions','max_selections','Revise o máximo de escolhas.',item.item_key); }
      }
      if (['score','stars'].includes(item.type)) { const min=Number(item.min_score), max=Number(item.max_score), low=item.low_score_threshold === '' ? null : Number(item.low_score_threshold); if (!(max > min)) add('questions','max_score','O máximo precisa ser maior que o mínimo.',item.item_key); if (low !== null && !(low >= min && low <= max)) add('questions','low_score_threshold','A nota baixa precisa ficar dentro da escala.',item.item_key); }
      priorQuestions.set(item.item_key, item); if (item.id) priorQuestions.set(`question:${item.id}`, item);
    });
    const scoreRanges = active.filter(item => ['score','stars'].includes(item.type) && Number(item.max_score) > Number(item.min_score)).map(item => [Number(item.min_score),Number(item.max_score)]);
    if (form.elements.alert_enabled.checked && scoreRanges.length) { const threshold=Number(form.elements.alert_threshold.value), min=Math.min(...scoreRanges.map(item=>item[0])), max=Math.max(...scoreRanges.map(item=>item[1])); if (!Number.isFinite(threshold) || threshold < min || threshold > max) add('actions','alert_threshold','A nota de alerta precisa ficar dentro da escala das perguntas.'); }
    if (form.elements.objective.value === 'registration') { const media = ['photo','audio','video','document','location','contact','multiple_files']; questions.forEach(item => { if (!item.archived && media.includes(item.type)) add('questions','type','O Cadastro estruturado na tela ainda não aceita perguntas de mídia.',item.item_key); }); bindings.forEach(([binding,key]) => { if (bindings.filter(item => item[0] === binding).length > 1) add('questions','data_binding','Cada campo do cadastro pode ser usado apenas uma vez.',key); }); if (form.elements.status.value === 'active') [['lead.name','Nome completo'],['lead.phone','WhatsApp']].forEach(([value,label]) => { if (!bindings.some(item => item[0] === value)) add('questions','data_binding',`O cadastro ativo precisa conter o vínculo "${label}".`); }); }
    return errors;
  }

  const templates = {
    satisfaction: {name:'Pesquisa de satisfação', objective:'satisfaction', questions:[{text:'De 0 a 10, qual a sua satisfação geral?',type:'score',min_score:0,max_score:10,low_score_threshold:6},{text:'O que mais influenciou sua nota?',type:'choice',options:[{label:'Atendimento',value:'atendimento'},{label:'Tempo de espera',value:'espera'},{label:'Estrutura',value:'estrutura'}]},{text:'Como podemos melhorar?',type:'text',required:false,settings:{text_format:'long',max_length:500}}]},
    registration: {name:'Cadastro de responsável e pets',objective:'registration',channels:['kiosk','interviewer'],questions:[{text:'Nome completo',type:'text',data_binding:'lead.name'},{text:'WhatsApp',type:'text',data_binding:'lead.phone',settings:{validation:'phone'}},{text:'Cidade',type:'text',required:false,data_binding:'lead.city'},{text:'Nome do pet',type:'text',required:false,data_binding:'pet.name'},{text:'Espécie do pet',type:'choice',required:false,data_binding:'pet.species',options:[{label:'Cachorro',value:'dog'},{label:'Gato',value:'cat'},{label:'Outro',value:'other'}]}]},
    followup: {name:'Acompanhamento pós-atendimento',objective:'followup',questions:[{text:'Como o pet está depois do atendimento?',type:'choice',options:[{label:'Melhorou',value:'better'},{label:'Está igual',value:'same'},{label:'Piorou',value:'worse',creates_alert:true}]},{text:'Precisa que nossa equipe entre em contato?',type:'yes_no'},{text:'Conte o que aconteceu desde o atendimento.',type:'text',required:false,settings:{text_format:'long'}}]},
    anonymous: {name:'Pesquisa anônima',objective:'satisfaction',anonymous:true,channels:['kiosk','interviewer'],questions:[{text:'Como você avalia sua experiência?',type:'stars',min_score:1,max_score:5,settings:{star_count:5,min_label:'Ruim',max_label:'Excelente'}},{text:'Deixe uma sugestão.',type:'text',required:false,settings:{text_format:'long'}}]},
    blank: {name:'Novo questionário',objective:'satisfaction',questions:[{text:'',type:'text'}]},
  };
  function applyTemplate(name) {
    const model = templates[name]; if (!model) return;
    list.replaceChildren(); selectedCard = null;
    form.elements.name.value = model.name; form.elements.objective.value = model.objective; form.elements.response_mode.value = model.anonymous ? 'anonymous' : 'identified';
    const selectedChannels = model.channels || ['whatsapp']; form.querySelectorAll('input[name="channels"]').forEach(input => { input.checked = selectedChannels.includes(input.value); });
    model.questions.forEach(question => list.appendChild(questionCard(normalizedQuestion(question))));
    renumber(); if (list.firstElementChild) selectCard(list.firstElementChild); responseModeUI(); objectiveUI(); updateTitle(); markDirty();
    document.querySelector('[data-template-dialog]')?.close(); openTab('questions');
  }
  document.querySelectorAll('[data-questionnaire-template]').forEach(button => button.addEventListener('click', () => applyTemplate(button.dataset.questionnaireTemplate)));
  const templateDialog = document.querySelector('[data-template-dialog]'); if (!initial.length && templateDialog?.showModal) requestAnimationFrame(() => templateDialog.showModal());

  function previewQuestionMarkup(item, mode) {
    const options = (item.options || []).slice(0, 5);
    if (mode === 'whatsapp') { const choices = options.length ? `<div class="preview-wa-options">${options.map((option, index) => `<span>${index + 1}. ${esc(option.label)}</span>`).join('')}</div>` : '<span class="preview-input">Digite uma resposta…</span>'; return `<article class="preview-wa-bubble"><strong>${esc(item.text || 'Pergunta sem texto')}</strong>${choices}</article>`; }
    const controls = ['choice','multiple_choice'].includes(item.type) ? options.map(option => `<span class="preview-option">${item.type === 'multiple_choice' ? '□' : '○'} ${esc(option.label)}</span>`).join('') : ['score','stars'].includes(item.type) ? '<div class="preview-score"><b>1</b><b>2</b><b>3</b><b>4</b><b>5</b></div>' : '<span class="preview-input">Digite sua resposta…</span>';
    return `<article class="preview-question"><small>${esc(typeLabels[item.type] || item.type)}</small><strong>${esc(item.text || 'Pergunta sem texto')}</strong>${controls}</article>`;
  }
  function renderPreview(mode = 'web') { const questions = collectQuestions().filter(item => !item.archived); const title = form.elements.name.value || 'Questionário sem nome'; const body = questions.length ? questions.map(item => previewQuestionMarkup(item, mode)).join('') : '<p>Nenhuma pergunta adicionada.</p>'; document.querySelector('[data-preview-stage]').dataset.mode = mode; document.querySelector('[data-preview-stage]').innerHTML = `<div class="preview-device"><header><span>EscutaPet</span><strong>${esc(title)}</strong></header><main>${body}</main><footer>Prévia sem envio de respostas</footer></div>`; }
  const previewDialog = document.querySelector('[data-preview-dialog]');
  document.querySelectorAll('[data-open-preview]').forEach(button => button.addEventListener('click', () => { renderPreview('web'); previewDialog.showModal(); }));
  document.querySelector('[data-close-preview]')?.addEventListener('click', () => previewDialog.close());
  document.querySelectorAll('[data-preview-mode]').forEach(button => button.addEventListener('click', () => { document.querySelectorAll('[data-preview-mode]').forEach(item => item.classList.toggle('active', item === button)); renderPreview(button.dataset.previewMode); }));

  const placeholderDialog = document.querySelector('[data-placeholder-dialog]');
  let placeholderTarget = null;
  form.addEventListener('click', event => {
    const button = event.target.closest('[data-open-placeholder]'); if (!button) return;
    placeholderTarget = button.closest('.placeholder-enabled-field')?.querySelector('input,textarea');
    if (!placeholderTarget || !placeholderDialog?.showModal) return;
    const anonymous = form.elements.response_mode?.value === 'anonymous';
    placeholderDialog.querySelectorAll('[data-placeholder-identified]').forEach(section => { section.hidden = anonymous; });
    placeholderDialog.showModal();
  });
  placeholderDialog?.querySelectorAll('[data-close-placeholder]').forEach(button => button.addEventListener('click', () => placeholderDialog.close()));
  placeholderDialog?.addEventListener('click', event => {
    const button = event.target.closest('[data-placeholder-value]'); if (!button || !placeholderTarget) return;
    const token = button.dataset.placeholderValue || '';
    const start = Number.isInteger(placeholderTarget.selectionStart) ? placeholderTarget.selectionStart : placeholderTarget.value.length;
    const end = Number.isInteger(placeholderTarget.selectionEnd) ? placeholderTarget.selectionEnd : start;
    placeholderTarget.setRangeText(token, start, end, 'end');
    placeholderTarget.dispatchEvent(new Event('input', {bubbles:true}));
    placeholderDialog.close(); placeholderTarget.focus();
  });

  function updatePublicationSummary() { const count = [...list.children].filter(card => !card._data.archived).length; const channels = [...form.querySelectorAll('input[name="channels"]:checked')].map(input => input.nextElementSibling?.querySelector('strong')?.textContent || input.value); const target = document.querySelector('[data-publication-summary]'); if (target) target.innerHTML = `<div><small>Nome</small><strong>${esc(form.elements.name.value || 'Não informado')}</strong></div><div><small>Perguntas</small><strong>${count}</strong></div><div><small>Canais</small><strong>${esc(channels.join(', ') || 'Nenhum')}</strong></div><div><small>Modo</small><strong>${form.dataset.editMode === 'advanced' ? 'Avançado' : 'Simples'}</strong></div>`; }
  function updateTitle() { document.querySelector('[data-editor-title]').textContent = form.elements.name.value || 'Questionário sem nome'; updatePublicationSummary(); }
  form.querySelector('[data-questionnaire-name]')?.addEventListener('input', updateTitle); updateTitle();

  const responseMode = form.querySelector('[data-response-mode]'), whatsapp = form.querySelector('input[name="channels"][value="whatsapp"]'), warning = form.querySelector('[data-anonymous-warning]');
  function responseModeUI() { const anonymous = responseMode?.value === 'anonymous'; if (warning) warning.hidden = !anonymous; if (whatsapp) whatsapp.disabled = false; }
  responseMode?.addEventListener('change', responseModeUI); responseModeUI();
  const audience = form.querySelector('[data-audience-select]'), target = form.querySelector('[data-segment-target]'); const audienceUI = () => { if (target) target.hidden = audience?.value !== 'segment'; }; audience?.addEventListener('change', audienceUI); audienceUI();
  const triggerRadios = [...form.querySelectorAll('input[name="trigger_type"]')], delayBlock = form.querySelector('[data-delay-block]'); const triggerUI = () => { const value = triggerRadios.find(item => item.checked)?.value; if (delayBlock) delayBlock.classList.toggle('is-delay', ['after_registration','recurring'].includes(value)); }; triggerRadios.forEach(item => item.addEventListener('change', triggerUI)); triggerUI();
  const objective = form.querySelector('select[name="objective"]'), registrationHelp = form.querySelector('[data-registration-help]'); function objectiveUI() { if (registrationHelp) registrationHelp.hidden = objective?.value !== 'registration'; } objective?.addEventListener('change', objectiveUI); objectiveUI();

  form.addEventListener('input', markDirty); form.addEventListener('change', markDirty);
  function captureRecoveryData() {
    const fields = {};
    const excluded = new Set(['questions_json','submission_token','base_revision','editor_recovery_source','editor_action']);
    [...form.elements].forEach(control => {
      if (!control.name || excluded.has(control.name) || control.type === 'submit' || control.type === 'button') return;
      if (control.type === 'checkbox') { if (control.name === 'channels') { if (!Array.isArray(fields.channels)) fields.channels=[]; if (control.checked) fields.channels.push(control.value); } else fields[control.name]=control.checked; }
      else if (control.type === 'radio') { if (control.checked) fields[control.name]=control.value; }
      else fields[control.name]=control.value;
    });
    return {fields, questions:collectQuestions()};
  }
  function restoreRecoveryData(data) {
    if (!data || typeof data !== 'object') return;
    Object.entries(data.fields || {}).forEach(([name,value]) => [...form.querySelectorAll(`[name="${CSS.escape(name)}"]`)].forEach(control => { if (control.type === 'checkbox') control.checked=Array.isArray(value) ? value.map(String).includes(String(control.value)) : Boolean(value); else if (control.type === 'radio') control.checked=String(control.value)===String(value); else control.value=value ?? ''; }));
    if (Array.isArray(data.questions)) { list.replaceChildren(); selectedCard=null; data.questions.forEach(item => list.appendChild(questionCard(normalizedQuestion(item)))); renumber(); if (list.firstElementChild) selectCard(list.firstElementChild); }
    responseModeUI(); audienceUI(); triggerUI(); objectiveUI(); updateTitle(); markDirty();
  }
  window.EditorRecoveryAdapter = {
    capture:captureRecoveryData,
    restore:restoreRecoveryData,
    summary:data => ({Nome:data?.fields?.name || 'Sem nome', Status:data?.fields?.status || 'rascunho', Perguntas:data?.questions?.filter(item=>!item.archived).length || 0, Canais:(data?.fields?.channels || []).join(', ') || 'nenhum'}),
    prepareDuplicate:() => { saveCurrent(); [...list.children].forEach(card => { card._data={...card._data,id:'',item_key:clientKey('question:new'),replacement_question_id:null,options:(card._data.options || []).map(option=>({...option,id:clientKey('option:new')}))}; }); if (form.elements.name && !form.elements.name.value.startsWith('Cópia de ')) form.elements.name.value=`Cópia de ${form.elements.name.value}`; renumber(); },
  };
  form.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    setStatus('Validando', 'validating'); const questions = collectQuestions(); hidden.value = JSON.stringify(questions); const errors = validate(questions);
    if (errors.length) { event.preventDefault(); showErrors(errors); setStatus('Erro ao salvar', 'error'); return; }
    const action = event.submitter?.value || 'publish';
    if (action === 'publish' && !confirm(`Publicar a versão ${version.next}?\n\nVersão atual: ${version.current || 'nenhuma'}\nPesquisas ativas ou agendadas: ${version.active}\n\nAs pesquisas iniciadas continuam usando a versão anterior.`)) { event.preventDefault(); return; }
    form.dispatchEvent(new CustomEvent('editor:submitting'));
    submitting = true; dirty = false; form.querySelectorAll('[type="submit"]').forEach(button => { button.disabled = true; button.dataset.originalText = button.textContent; button.textContent = 'Salvando…'; }); setStatus('Salvando', 'saving');
  });
  form.addEventListener('keydown', event => { if (submitting && event.key === 'Enter') event.preventDefault(); });
  window.addEventListener('beforeunload', event => { if (dirty && !submitting) { event.preventDefault(); event.returnValue = ''; } });
  if (serverErrors.length) requestAnimationFrame(() => showErrors(serverErrors));
})();
