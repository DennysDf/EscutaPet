(() => {
  const root = document.documentElement;
  const sidebar = document.querySelector('#sidebar');
  const overlay = document.querySelector('[data-sidebar-overlay]');
  const menuToggle = document.querySelector('[data-menu-toggle]');
  const sidebarCollapse = document.querySelector('[data-sidebar-collapse]');
  const closeSidebar = () => {
    sidebar?.classList.remove('open');
    overlay?.classList.remove('show');
    menuToggle?.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('navigation-open');
  };
  menuToggle?.addEventListener('click', () => {
    const opened = sidebar?.classList.toggle('open') || false;
    overlay?.classList.toggle('show', opened);
    menuToggle.setAttribute('aria-expanded', String(opened));
    document.body.classList.toggle('navigation-open', opened);
  });
  overlay?.addEventListener('click', closeSidebar);
  document.querySelectorAll('.nav-list a').forEach(link => link.addEventListener('click', closeSidebar));
  sidebarCollapse?.addEventListener('click', () => {
    root.classList.toggle('sidebar-collapsed');
    const collapsed = root.classList.contains('sidebar-collapsed');
    localStorage.setItem('escutapet:sidebar', collapsed ? 'collapsed' : 'expanded');
    sidebarCollapse.setAttribute('aria-expanded', String(!collapsed));
    sidebarCollapse.setAttribute('aria-label', collapsed ? 'Expandir menu' : 'Recolher menu');
    sidebarCollapse.setAttribute('title', collapsed ? 'Expandir menu' : 'Recolher menu');
  });
  if (sidebarCollapse) sidebarCollapse.setAttribute('aria-expanded', String(!root.classList.contains('sidebar-collapsed')));

  const resolvedTheme = preference => preference === 'system'
    ? (matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light')
    : preference;
  const applyTheme = preference => {
    root.dataset.themePreference = preference;
    root.dataset.theme = resolvedTheme(preference);
    localStorage.setItem('escutapet:theme', preference);
  };
  document.querySelector('[data-theme-toggle]')?.addEventListener('click', () => {
    applyTheme(root.dataset.theme === 'dark' ? 'light' : 'dark');
    syncPreferences();
  });

  const userButton = document.querySelector('[data-user-menu]');
  const userPanel = document.querySelector('[data-user-menu-panel]');
  userButton?.addEventListener('click', event => {
    event.stopPropagation();
    userPanel.hidden = !userPanel.hidden;
    userButton.setAttribute('aria-expanded', String(!userPanel.hidden));
  });
  document.addEventListener('click', event => {
    if (userPanel && !userPanel.hidden && !userPanel.contains(event.target)) {
      userPanel.hidden = true;
      userButton?.setAttribute('aria-expanded', 'false');
    }
  });
  addEventListener('resize', () => {
    if (innerWidth >= 768) closeSidebar();
  });

  const drawer = document.querySelector('[data-preferences]');
  const preferencesPanel = drawer?.querySelector('.preferences-panel');
  const openPreferencesButton = document.querySelector('[data-open-preferences]');
  let preferencesReturnFocus = null;
  const closePreferences = () => {
    if (!drawer || drawer.hidden) return;
    drawer.hidden = true;
    openPreferencesButton?.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('preferences-open');
    preferencesReturnFocus?.focus();
    preferencesReturnFocus = null;
  };
  const openPreferences = event => {
    if (!drawer) return;
    preferencesReturnFocus = event?.currentTarget || document.activeElement;
    drawer.hidden = false;
    openPreferencesButton?.setAttribute('aria-expanded', 'true');
    document.body.classList.add('preferences-open');
    syncPreferences();
    drawer.querySelector('[data-close-preferences]')?.focus();
  };
  openPreferencesButton?.addEventListener('click', openPreferences);
  document.querySelectorAll('[data-close-preferences]').forEach(button => button.addEventListener('click', closePreferences));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && drawer && !drawer.hidden) {
      event.preventDefault();
      closePreferences();
    } else if (event.key === 'Escape' && sidebar?.classList.contains('open')) {
      event.preventDefault();
      closeSidebar();
      menuToggle?.focus();
    } else if (event.key === 'Escape' && userPanel && !userPanel.hidden) {
      event.preventDefault();
      userPanel.hidden = true;
      userButton?.setAttribute('aria-expanded', 'false');
      userButton?.focus();
    }
    if (event.key === 'Tab' && drawer && !drawer.hidden && preferencesPanel) {
      const focusable = [...preferencesPanel.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]')];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
  const defaults = {theme: root.dataset.themePreference || 'system', fontScale: 'normal', density: 'comfortable', contrast: 'normal', motion: 'on'};
  const stored = key => localStorage.getItem(`escutapet:${key}`) || defaults[key];
  const setPreference = (key, value) => {
    localStorage.setItem(`escutapet:${key}`, value);
    if (key === 'theme') applyTheme(value);
    else root.dataset[key] = value;
    syncPreferences();
  };
  const syncPreferences = () => {
    document.querySelectorAll('[data-preference]').forEach(group => {
      const key = group.dataset.preference;
      group.querySelectorAll('[data-value]').forEach(button => button.classList.toggle('active', button.dataset.value === stored(key)));
    });
    document.querySelectorAll('[data-preference-toggle]').forEach(input => {
      const key = input.dataset.preferenceToggle;
      input.checked = key === 'contrast' ? stored(key) === 'high' : stored(key) === 'reduced';
    });
  };
  ['fontScale', 'density', 'contrast', 'motion'].forEach(key => { root.dataset[key] = stored(key); });
  document.querySelectorAll('[data-preference] [data-value]').forEach(button => button.addEventListener('click', () => {
    setPreference(button.closest('[data-preference]').dataset.preference, button.dataset.value);
  }));
  document.querySelectorAll('[data-preference-toggle]').forEach(input => input.addEventListener('change', () => {
    const key = input.dataset.preferenceToggle;
    setPreference(key, input.checked ? (key === 'contrast' ? 'high' : 'reduced') : (key === 'contrast' ? 'normal' : 'on'));
  }));
  syncPreferences();

  document.querySelectorAll('[data-copy]').forEach(button => {
    button.addEventListener('click', async () => {
      const input = button.parentElement?.querySelector('input');
      if (!input) return;
      try { await navigator.clipboard.writeText(input.value); button.textContent = 'Copiado'; }
      catch { input.select(); document.execCommand('copy'); button.textContent = 'Copiado'; }
      setTimeout(() => button.textContent = 'Copiar', 1400);
    });
  });

  const observerLinks = [...document.querySelectorAll('.editor-nav a')];
  if (observerLinks.length) {
    const sections = observerLinks.map(link => document.querySelector(link.getAttribute('href'))).filter(Boolean);
    const observer = new IntersectionObserver(entries => {
      entries.filter(entry => entry.isIntersecting).forEach(entry => {
        observerLinks.forEach(link => link.classList.toggle('active', link.getAttribute('href') === `#${entry.target.id}`));
      });
    }, {rootMargin: '-25% 0px -65% 0px'});
    sections.forEach(section => observer.observe(section));
  }

  const offlineBanner = document.querySelector('[data-offline-banner]');
  const updateConnection = () => { if (offlineBanner) offlineBanner.hidden = navigator.onLine; };
  addEventListener('online', updateConnection);
  addEventListener('offline', updateConnection);
  updateConnection();

  const messageType = document.querySelector('[data-message-type]');
  const composeExtras = document.querySelectorAll('[data-compose-extra]');
  const syncCompose = () => composeExtras.forEach(item => {
    item.hidden = item.dataset.composeExtra !== messageType?.value;
    item.querySelectorAll('input').forEach(input => input.disabled = item.hidden);
  });
  messageType?.addEventListener('change', syncCompose);
  syncCompose();

  document.querySelectorAll('[data-endpoint-config]').forEach(group => {
    const radios = [...group.querySelectorAll('input[name="send_endpoint_mode"]')];
    const autoField = group.querySelector('[data-auto-endpoint]');
    const manualField = group.querySelector('[data-manual-endpoint]');
    const manualInput = manualField?.querySelector('input');
    const syncEndpointMode = () => {
      const manual = radios.find(radio => radio.checked)?.value === 'manual';
      if (autoField) autoField.hidden = manual;
      if (manualField) manualField.hidden = !manual;
      if (manualInput) {
        manualInput.disabled = !manual;
        manualInput.required = manual;
      }
    };
    radios.forEach(radio => radio.addEventListener('change', syncEndpointMode));
    syncEndpointMode();
  });

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js').catch(() => {});
})();
