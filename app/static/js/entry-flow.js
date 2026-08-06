(() => {
  const root = document.querySelector('[data-entry-flow]');
  if (!root) return;
  const form = root.querySelector('form');
  const steps = [...root.querySelectorAll('[data-step]')];
  const list = root.querySelector('[data-pet-list]');
  const template = document.querySelector('#pet-card-template');
  const maxPets = Number(root.dataset.maxPets || 10);
  let current = 0;

  const showStep = (index) => {
    current = Math.max(0, Math.min(steps.length - 1, index));
    steps.forEach((step, i) => step.classList.toggle('active', i === current));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const renumber = () => {
    if (!list) return;
    [...list.querySelectorAll('.pet-entry-card')].forEach((card, index) => {
      card.querySelector('.pet-number').textContent = String(index + 1);
      const remove = card.querySelector('[data-remove-pet]');
      remove.hidden = list.children.length === 1;
    });
  };

  const addPet = (data = {}) => {
    if (!list || !template) return;
    if (list.children.length >= maxPets) return;
    const card = template.content.firstElementChild.cloneNode(true);
    const values = {
      'pet.name': data.name || '',
      'pet.species': data.species || '',
      'visit.reason': data.reason || '',
      'visit.service_type': data.service_type || '',
      'visit.service_status': data.service_status || '',
      'visit.description': data.description || '',
    };
    card.querySelectorAll('[data-binding]').forEach(control => {
      if (Object.prototype.hasOwnProperty.call(values, control.dataset.binding)) control.value = values[control.dataset.binding];
    });
    card.querySelector('[data-remove-pet]').addEventListener('click', () => {
      card.remove();
      if (!list.children.length) addPet();
      renumber();
    });
    list.appendChild(card);
    renumber();
  };

  const stepValid = () => {
    const controls = [...steps[current].querySelectorAll('input,select,textarea')].filter(el => !el.disabled && el.offsetParent !== null);
    for (const control of controls) {
      if (!control.checkValidity()) {
        control.reportValidity();
        return false;
      }
    }
    if (list && steps[current].querySelector('[data-pet-list]')) {
      const noPet = root.querySelector('[data-no-pet]');
      const names = list ? [...list.querySelectorAll('[data-binding="pet.name"]')].filter(el => el.value.trim()) : [];
      if (!names.length && !(noPet && noPet.checked)) {
        alert('Adicione pelo menos um pet ou marque a opção sem pet.');
        return false;
      }
    }
    return true;
  };

  root.addEventListener('click', (event) => {
    const next = event.target.closest('[data-next-step]');
    const prev = event.target.closest('[data-prev-step]');
    const add = event.target.closest('[data-add-pet]');
    if (next) { event.preventDefault(); if (stepValid()) showStep(current + 1); }
    if (prev) { event.preventDefault(); showStep(current - 1); }
    if (add) { event.preventDefault(); addPet(); }
  });

  const noPet = root.querySelector('[data-no-pet]');
  if (noPet) noPet.addEventListener('change', () => {
    list?.querySelectorAll('input,select,textarea').forEach(el => el.disabled = noPet.checked);
    const addButton = root.querySelector('[data-add-pet]'); if (addButton) addButton.disabled = noPet.checked;
    list?.classList.toggle('muted', noPet.checked);
  });

  const lookup = root.querySelector('[data-lookup-lead]');
  if (lookup) lookup.addEventListener('click', async () => {
    const phone = form.querySelector('[data-binding="lead.phone"]')?.value.trim() || '';
    const message = root.querySelector('[data-lookup-message]');
    if (!phone) { message.textContent = 'Informe o WhatsApp primeiro.'; return; }
    lookup.disabled = true;
    message.textContent = 'Procurando cadastro…';
    try {
      const response = await fetch(`/api/leads/buscar?phone=${encodeURIComponent(phone)}`);
      const data = await response.json();
      if (!data.found) { message.textContent = 'Nenhum cadastro anterior encontrado.'; return; }
      const name = form.querySelector('[data-binding="lead.name"]'); if (name) name.value = data.lead.name || '';
      const city = form.querySelector('[data-binding="lead.city"]'); if (city) city.value = String(data.lead.city_id || '');
      const neighborhood = form.querySelector('[data-binding="lead.neighborhood"]'); if (neighborhood) neighborhood.value = data.lead.neighborhood || '';
      if (list) list.innerHTML = '';
      (data.lead.pets || []).forEach(addPet);
      if (list && !list.children.length) addPet();
      message.textContent = data.lead.number_validated ? 'Cadastro encontrado; WhatsApp já confirmado.' : 'Cadastro encontrado; confira os dados.';
    } catch (_) {
      message.textContent = 'Não foi possível consultar agora.';
    } finally { lookup.disabled = false; }
  });

  form.addEventListener('submit', (event) => {
    if (!stepValid()) event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    if (!event.defaultPrevented && button) { button.disabled = true; button.textContent = 'Salvando…'; }
  });

  if (list && template) addPet();
  showStep(0);
})();
