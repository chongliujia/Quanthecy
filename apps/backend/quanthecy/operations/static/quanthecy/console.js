(() => {
  const trigger = document.querySelector('.console-menu');
  const backdrop = document.querySelector('.console-backdrop');
  const sidebar = document.getElementById('console-sidebar');
  if (!trigger || !sidebar || !backdrop) return;
  const desktop = window.matchMedia('(min-width: 761px)');
  const close = () => {
    document.body.classList.remove('console-nav-open');
    trigger.setAttribute('aria-expanded', 'false');
    sidebar.inert = !desktop.matches;
  };
  close();
  trigger.addEventListener('click', () => {
    const open = document.body.classList.toggle('console-nav-open');
    trigger.setAttribute('aria-expanded', String(open));
    sidebar.inert = !open && !desktop.matches;
    if (open) sidebar.querySelector('a')?.focus();
  });
  backdrop.addEventListener('click', () => { close(); trigger.focus(); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && document.body.classList.contains('console-nav-open')) {
      close(); trigger.focus();
    }
  });
  desktop.addEventListener('change', close);
})();
