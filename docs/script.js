(() => {
  const toggle = document.querySelector('.menu-toggle');
  const sidebar = document.querySelector('#sidebar');
  const links = [...document.querySelectorAll('.side-nav a')];
  const setMenu = (open) => {
    sidebar.classList.toggle('open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Закрыть навигацию' : 'Открыть навигацию');
  };
  toggle.addEventListener('click', () => setMenu(!sidebar.classList.contains('open')));
  links.forEach(link => link.addEventListener('click', () => setMenu(false)));
  document.addEventListener('keydown', event => { if (event.key === 'Escape') setMenu(false); });
  document.addEventListener('click', event => {
    if (sidebar.classList.contains('open') && !sidebar.contains(event.target) && !toggle.contains(event.target)) setMenu(false);
  });

  document.querySelectorAll('.copy-btn').forEach(button => {
    button.addEventListener('click', async () => {
      const text = button.closest('.codeblock').querySelector('code').textContent;
      const original = button.innerHTML;
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(text);
        } else {
          const input = document.createElement('textarea');
          input.value = text;
          input.setAttribute('readonly', '');
          input.style.position = 'fixed';
          input.style.opacity = '0';
          document.body.appendChild(input);
          input.select();
          const copied = document.execCommand('copy');
          input.remove();
          if (!copied) throw new Error('copy failed');
        }
        button.textContent = 'СКОПИРОВАНО ✓';
      } catch (_) {
        button.textContent = 'ВЫДЕЛИТЕ ТЕКСТ ВРУЧНУЮ';
      }
      setTimeout(() => { button.innerHTML = original; }, 2200);
    });
  });

  if ('IntersectionObserver' in window) {
    const sections = links.map(link => document.querySelector(link.getAttribute('href'))).filter(Boolean);
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        links.forEach(link => link.classList.toggle('active', link.getAttribute('href') === '#' + entry.target.id));
      });
    }, { rootMargin: '-15% 0px -75% 0px' });
    sections.forEach(section => observer.observe(section));
  }
})();
