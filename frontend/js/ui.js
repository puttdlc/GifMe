// Small shared UI helpers.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  children.flat().forEach(c => node.append(c?.nodeType ? c : document.createTextNode(c)));
  return node;
}

export function bytes(n) {
  if (!n && n !== 0) return '-';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export function isVideoName(name = '') {
  return /\.(mp4|webm|mov|mkv|avi|m4v)$/i.test(name);
}

let toastTimer;
export function toast(message, kind = 'info') {
  let box = $('#toast');
  if (!box) {
    box = el('div', { id: 'toast' });
    document.body.append(box);
  }
  box.textContent = message;
  box.className = `show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.remove('show'), 4200);
}

// Wrap an async action with a busy state on its button, and route failures
// to a toast rather than the console.
export async function withBusy(button, fn) {
  const label = button?.textContent;
  if (button) { button.disabled = true; button.dataset.busy = '1'; button.textContent = 'Working…'; }
  try {
    return await fn();
  } catch (e) {
    toast(e.message || String(e), 'error');
    return null;
  } finally {
    if (button) { button.disabled = false; delete button.dataset.busy; button.textContent = label; }
  }
}

// Range inputs paired with an <output> show their live value.
export function initSliders(root = document) {
  root.querySelectorAll('label.slider').forEach(label => {
    const range = label.querySelector('input[type=range]');
    const out = label.querySelector('output');
    if (!range || !out) return;
    const sync = () => { out.textContent = range.value; };
    range.addEventListener('input', sync);
    sync();
  });
}
