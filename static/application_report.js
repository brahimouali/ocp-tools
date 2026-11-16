for (const button of document.querySelectorAll('.presence-status.present')) {
  const popup = document.getElementById(button.getAttribute('aria-describedby'));
  let timer;
  function hide() {
    clearTimeout(timer);
    popup.hidePopover();
    button.setAttribute('aria-expanded', 'false');
  }
  function show() {
    clearTimeout(timer);
    for (const other of document.querySelectorAll('.namespace-popup:popover-open')) {
      if (other !== popup) {
        other.hidePopover();
        other.previousElementSibling.setAttribute('aria-expanded', 'false');
      }
    }
    popup.showPopover();
    button.setAttribute('aria-expanded', 'true');
    const rect = button.getBoundingClientRect();
    const left = Math.max(12, Math.min(rect.left, innerWidth - popup.offsetWidth - 12));
    const top = rect.bottom + 8 + popup.offsetHeight <= innerHeight - 12
      ? rect.bottom + 8 : Math.max(12, rect.top - popup.offsetHeight - 8);
    popup.style.left = `${left}px`;
    popup.style.top = `${top}px`;
  }
  function scheduleHide() {
    timer = setTimeout(hide, 150);
  }
  button.addEventListener('mouseenter', show);
  button.addEventListener('focus', show);
  button.addEventListener('click', show);
  button.addEventListener('mouseleave', scheduleHide);
  button.addEventListener('blur', scheduleHide);
  popup.addEventListener('mouseenter', () => clearTimeout(timer));
  popup.addEventListener('mouseleave', scheduleHide);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hide(); });
  document.addEventListener('pointerdown', event => {
    if (!button.contains(event.target) && !popup.contains(event.target)) hide();
  });
  window.addEventListener('resize', hide);
  window.addEventListener('scroll', event => {
    if (!popup.contains(event.target)) hide();
  }, true);
}
