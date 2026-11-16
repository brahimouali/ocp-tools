for (const form of document.querySelectorAll('.csv-import')) {
  const input = form.querySelector('input[type=file]');
  const result = form.nextElementSibling;
  let pending;
  async function preview(event) {
    event?.preventDefault();
    pending?.abort();
    if (!input.files.length) {
      result.replaceChildren();
      return;
    }
    const controller = new AbortController();
    pending = controller;
    result.textContent = 'Chargement de l’aperçu…';
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: new FormData(form),
        headers: {'X-Requested-With': 'fetch'}, signal: controller.signal
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Import impossible. Vérifiez le fichier (maximum 5 Mo) et rechargez la page si nécessaire.');
      }
      const data = await response.json();
      if (pending === controller) result.innerHTML = data.html;
    } catch (error) {
      if (error.name === 'AbortError' || pending !== controller) return;
      const message = document.createElement('p');
      message.className = 'import-error';
      message.textContent = error.message;
      result.replaceChildren(message);
    }
  }
  input.addEventListener('change', preview);
  form.addEventListener('submit', preview);
}
