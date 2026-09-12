// Thin wrapper over the API: every call returns parsed JSON or throws a
// message the UI can show verbatim.

import { progressBusy, progressEnd, progressSet, progressStart } from './progress.js';

// Uses XMLHttpRequest rather than fetch so upload progress is observable
// (fetch has no cross-browser way to report request-body progress) - that's
// what drives the "Uploading… NN%" state on the global progress bar. Once
// the upload finishes but before the response arrives, the bar switches to
// an indeterminate "Processing…" state, since that's the server doing the
// actual (potentially slow) ffmpeg/gifsicle/Pillow work.
export function post(endpoint, fields = {}, files = {}) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) {
    if (v === undefined || v === null || v === '') continue;
    fd.append(k, v);
  }
  let hasFiles = false;
  for (const [k, v] of Object.entries(files)) {
    if (!v) continue;
    if (v instanceof FileList || Array.isArray(v)) {
      if (v.length) hasFiles = true;
      Array.from(v).forEach(f => fd.append(k, f));
    } else {
      hasFiles = true;
      fd.append(k, v);
    }
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', endpoint);

    progressStart(hasFiles ? 'Uploading…' : 'Processing…');
    if (!hasFiles) progressBusy('Processing…');

    xhr.upload.addEventListener('progress', (e) => {
      if (!hasFiles || !e.lengthComputable) return;
      progressSet(e.loaded / e.total, `Uploading… ${Math.round((e.loaded / e.total) * 100)}%`);
    });
    xhr.upload.addEventListener('load', () => {
      if (hasFiles) progressBusy('Processing…');
    });

    xhr.addEventListener('load', () => {
      progressEnd();
      let body = {};
      try { body = JSON.parse(xhr.responseText || '{}'); } catch { /* non-JSON error page */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new Error(body.detail || `Request failed (${xhr.status})`));
    });
    xhr.addEventListener('error', () => {
      progressEnd();
      reject(new Error('Network error - is the server running?'));
    });
    xhr.addEventListener('abort', () => {
      progressEnd();
      reject(new Error('Request aborted'));
    });

    xhr.send(fd);
  });
}

export async function get(endpoint) {
  const res = await fetch(endpoint);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
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
