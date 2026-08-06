(() => {
  const modal = document.querySelector('[data-schedule-test-modal]');
  if (!modal) return;
  const open = () => { modal.hidden = false; document.body.classList.add('modal-open'); requestAnimationFrame(() => modal.querySelector('select')?.focus()); };
  const close = () => { modal.hidden = true; document.body.classList.remove('modal-open'); };
  document.querySelectorAll('[data-open-schedule-test]').forEach(button => button.addEventListener('click', open));
  modal.querySelectorAll('[data-close-schedule-test]').forEach(button => button.addEventListener('click', close));
  modal.addEventListener('click', event => { if (event.target === modal) close(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !modal.hidden) close(); });
})();
