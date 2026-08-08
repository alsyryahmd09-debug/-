(function loadSiteScript() {
  const load = () => {
    if (document.querySelector('script[src="/scripts/main.js"]')) return;

    const script = document.createElement('script');
    script.src = '/scripts/main.js';
    document.head.appendChild(script);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load, { once: true });
  } else {
    load();
  }
})();
