// Thin wrapper over the API: every call returns parsed JSON or throws a
// message the UI can show verbatim.

export async function post(endpoint, fields = {}, files = {}) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) {
    if (v === undefined || v === null || v === '') continue;
    fd.append(k, v);
  }
  for (const [k, v] of Object.entries(files)) {
    if (!v) continue;
    if (v instanceof FileList || Array.isArray(v)) {
      Array.from(v).forEach(f => fd.append(k, f));
    } else {
      fd.append(k, v);
    }
  }
  const res = await fetch(endpoint, { method: 'POST', body: fd });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}

export async function get(endpoint) {
  const res = await fetch(endpoint);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

// Pull the values of every named control inside a container, normalising
// checkboxes so an unchecked box sends "false" instead of being dropped.
export function readFields(scope) {
  const out = {};
  scope.querySelectorAll('[name]').forEach(el => {
    if (el.type === 'checkbox') out[el.name] = el.checked ? 'true' : 'false';
    else if (el.type === 'radio') { if (el.checked) out[el.name] = el.value; }
    else if (el.type === 'file') { /* handled by the caller */ }
    else if (el.value !== '') out[el.name] = el.value;
  });
  return out;
}
