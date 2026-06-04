/** Lembretes de vencimento no navegador (Notification API). */
(function () {
  const STORAGE_KEY = 'theoos_notify_last';
  const TAG = 'theoos-vencimento';

  function todayKey() {
    return new Date().toISOString().slice(0, 10);
  }

  function alreadyNotifiedToday() {
    try {
      return localStorage.getItem(STORAGE_KEY) === todayKey();
    } catch {
      return false;
    }
  }

  function markNotifiedToday() {
    try {
      localStorage.setItem(STORAGE_KEY, todayKey());
    } catch (_) {}
  }

  function setStatus(msg, isError) {
    const el = document.getElementById('notify-status');
    if (!el) return;
    el.textContent = msg;
    el.style.color = isError ? 'var(--danger)' : 'var(--success)';
    el.hidden = false;
  }

  async function fetchVencimentos() {
    const r = await fetch('/api/vencimentos', { credentials: 'same-origin' });
    if (!r.ok) return null;
    return r.json();
  }

  function showNotifications(data) {
    if (!data?.enabled || (!data.contas?.length && !data.receber?.length)) return;

    const lines = [];
    data.contas.slice(0, 5).forEach((c) => {
      lines.push(`Pagar: ${c.nome} — R$ ${c.valor.toFixed(2)} (${c.quando})`);
    });
    data.receber.slice(0, 3).forEach((r) => {
      lines.push(`Receber: ${r.nome} — R$ ${r.valor.toFixed(2)}`);
    });
    if (!lines.length) return;

    const body = lines.join('\n');
    const n = new Notification('ThéoOS — Vencimentos', {
      body,
      tag: TAG,
      icon: '/static/icons/icon-192.svg',
    });
    n.onclick = () => {
      window.focus();
      window.location.href = '/contas';
    };
    markNotifiedToday();
  }

  async function runCheck() {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;
    if (alreadyNotifiedToday()) return;
    const data = await fetchVencimentos();
    if (!data) return;
    showNotifications(data);
  }

  async function requestPermission() {
    if (!window.isSecureContext) {
      const msg =
        'Notificações exigem conexão segura. Use https:// ou acesse por localhost (127.0.0.1). Em rede local (http://IP) o navegador bloqueia.';
      setStatus(msg, true);
      alert(msg);
      return false;
    }

    if (!('Notification' in window)) {
      const msg = 'Este navegador não suporta notificações.';
      setStatus(msg, true);
      alert(msg);
      return false;
    }

    if (Notification.permission === 'granted') {
      setStatus('Notificações já estão permitidas neste dispositivo.', false);
      localStorage.removeItem(STORAGE_KEY);
      await runCheck();
      return true;
    }

    if (Notification.permission === 'denied') {
      const msg =
        'Permissão bloqueada. No Chrome/Edge: clique no cadeado na barra de endereço → Notificações → Permitir, e recarregue a página.';
      setStatus(msg, true);
      alert(msg);
      return false;
    }

    let p = 'default';
    try {
      p = await Notification.requestPermission();
    } catch (err) {
      const msg = 'Não foi possível pedir permissão: ' + (err.message || err);
      setStatus(msg, true);
      alert(msg);
      return false;
    }

    if (p === 'granted') {
      setStatus('Permitido! Você receberá avisos de vencimento (máx. 1x por dia).', false);
      localStorage.removeItem(STORAGE_KEY);
      await runCheck();
      return true;
    }

    if (p === 'denied') {
      const msg = 'Permissão negada. Ajuste nas configurações do site no navegador.';
      setStatus(msg, true);
      alert(msg);
      return false;
    }

    setStatus('Permissão não confirmada. Clique de novo e escolha Permitir.', true);
    return false;
  }

  window.TheoOSNotify = { requestPermission, runCheck };

  document.addEventListener('click', (e) => {
    if (!e.target.closest('#btn-enable-notify')) return;
    e.preventDefault();
    requestPermission();
  });

  if ('Notification' in window && Notification.permission === 'granted') {
    window.addEventListener('load', () => setTimeout(runCheck, 2000));
  }
})();
