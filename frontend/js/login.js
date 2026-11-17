// Login page: posts the credentials, then returns to the page that sent us here.

const form = document.getElementById('login-form');
const err = document.getElementById('login-err');
const btn = document.getElementById('login-btn');
const pw = document.getElementById('password');
const reveal = document.getElementById('reveal');

// Only same-site paths, so ?next= can't send someone to another site.
function nextUrl() {
  const n = new URLSearchParams(location.search).get('next') || '/';
  return /^\/(?![/\\])/.test(n) ? n : '/';
}

function showError(msg) {
  err.textContent = msg;
  err.hidden = false;
  form.classList.remove('shake');
  void form.offsetWidth; // restart the animation
  form.classList.add('shake');
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  btn.disabled = true;
  btn.textContent = 'Signing in…';
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: document.getElementById('username').value, password: pw.value }),
    });
    const body = await res.json().catch(() => ({}));
    if (res.ok) { location.replace(nextUrl()); return; }
    showError(body.detail || `Sign-in failed (${res.status})`);
    pw.select();
  } catch {
    showError('Network error - is the server running?');
  }
  btn.disabled = false;
  btn.textContent = 'Sign in';
});

form.addEventListener('input', () => { err.hidden = true; });

reveal.addEventListener('click', () => {
  const show = pw.type === 'password';
  pw.type = show ? 'text' : 'password';
  reveal.textContent = show ? 'Hide' : 'Show';
  reveal.setAttribute('aria-pressed', show);
  reveal.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  pw.focus();
});
