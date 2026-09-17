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

(() => {
  const form = document.querySelector('.console-directory-form');
  const selectAll = form?.querySelector('[data-directory-select-all]');
  if (!selectAll) return;
  const rows = [...form.querySelectorAll('input[name="market_ids"]:not(:disabled)')];
  const update = () => {
    const selected = rows.filter(row => row.checked).length;
    selectAll.disabled = rows.length === 0;
    selectAll.checked = rows.length > 0 && selected === rows.length;
    selectAll.indeterminate = selected > 0 && selected < rows.length;
  };
  selectAll.addEventListener('change', () => {
    for (const row of rows) row.checked = selectAll.checked;
    update();
  });
  for (const row of rows) row.addEventListener('change', update);
  update();
})();
