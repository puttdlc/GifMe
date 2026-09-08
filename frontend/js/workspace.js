// The sticky bar showing the file every tool is currently working on, plus
// the result panel. Uploading once and chaining tools is the whole point.

import { post } from './api.js';
import { clearCurrent, setCurrent, state, subscribe } from './state.js';
import { $, bytes, el, isVideoName, toast, withBusy } from './ui.js';

// The GIF Maker builds from its own frame list, so the shared uploader would
// only be a second, confusing drop target on that tab.
export function setUploaderVisible(visible) {
  $('#ws-empty').classList.toggle('tab-hidden', !visible);
}

export function initWorkspace() {
  const input = $('#ws-file');
  const drop = $('#ws-drop');

  input.addEventListener('change', () => {
    if (input.files.length) upload(input.files[0]);
  });

  drop.addEventListener('click', (e) => {
    if (e.target.closest('label')) return;
    input.click();
  });

  ['dragover', 'dragenter'].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev =>
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', e => {
    const f = e.dataTransfer.files[0];
    if (f) upload(f);
  });

  $('#ws-reset').addEventListener('click', async (e) => {
    if (!state.job) return;
    await withBusy(e.target, async () => {
      const r = await post('/api/reset', { job: state.job });
      setCurrent({ ...r, meta: null });
      toast('Back to the file as uploaded');
    });
  });

  $('#ws-change').addEventListener('click', () => {
    clearCurrent();
    input.value = '';
  });

  subscribe(render);
}

export async function upload(file) {
  const btn = $('#ws-change');
  return withBusy(btn, async () => {
    const r = await post('/api/upload', {}, { file });
    setCurrent(r);
    showResult(r, 'Uploaded');
    return r;
  });
}

function render(s) {
  const bar = $('#workspace');
  const empty = $('#ws-empty');
  if (!s.job || !s.url) {
    bar.hidden = true;
    empty.hidden = false;
    return;
  }
  bar.hidden = false;
  empty.hidden = true;
  $('#ws-thumb').innerHTML = '';
  $('#ws-thumb').append(previewNode(s.url, s.name, true));
  $('#ws-name').textContent = s.name;
  $('#ws-facts').textContent = factLine(s.meta, s.sizeBytes);
  $('#ws-download').href = s.url;
  $('#ws-download').setAttribute('download', s.name);
}

function factLine(meta, size) {
  if (!meta) return bytes(size);
  const bits = [];
  if (meta.width) bits.push(`${meta.width}×${meta.height}`);
  if (meta.nb_frames > 1) bits.push(`${meta.nb_frames} frames`);
  if (meta.duration_s) bits.push(`${meta.duration_s}s`);
  if (meta.fps) bits.push(`${meta.fps} fps`);
  bits.push(bytes(meta.size_bytes ?? size));
  return bits.join(' · ');
}

function previewNode(url, name, small = false) {
  const bust = `${url}${url.includes('?') ? '&' : '?'}t=${Date.now()}`;
  if (isVideoName(name)) {
    return el('video', { src: bust, controls: '', autoplay: '', loop: '', muted: '' });
  }
  return el('img', { src: bust, alt: name, class: small ? 'thumb' : '' });
}

// Show a finished operation. It stays a side-by-side result until the user
// explicitly promotes it to the working file with "Set as input".
export function showResult(result, label = 'Done') {
  const body = $('#result-body');
  body.innerHTML = '';
  const notes = [];
  if (result.meta?.width) notes.push(`${result.meta.width}×${result.meta.height}`);
  if (result.meta?.nb_frames > 1) notes.push(`${result.meta.nb_frames} frames`);
  notes.push(bytes(result.size_bytes));
  if (result.saved_percent) notes.push(`${result.saved_percent}% smaller`);
  if (result.frame_count) notes.push(`${result.frame_count} frames used`);

  const useBtn = el('button', { class: 'button' }, 'Set as input');
  useBtn.addEventListener('click', async () => {
    const r = await withBusy(useBtn, () => post('/api/set-input', { job: result.job, name: result.name }));
    if (!r) return;
    setCurrent(r);
    useBtn.disabled = true;
    useBtn.textContent = 'In use as input';
    toast(`${result.name} is now the working file`);
  });

  body.append(
    el('div', { class: 'result-head' },
      el('strong', {}, label),
      el('span', { class: 'muted' }, notes.join(' · '))),
    previewNode(result.url, result.name),
    el('div', { class: 'result-actions' },
      el('a', { class: 'button', href: result.url, download: result.name }, `Download ${result.name}`),
      useBtn,
      el('span', { class: 'hint' }, 'Pick "Set as input" to keep editing this result - otherwise the next tool still works on the current input.')),
  );
  $('#result').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

export function showFrameGrid(title, frames, zipUrl) {
  const body = $('#result-body');
  body.innerHTML = '';
  body.append(el('div', { class: 'result-head' },
    el('strong', {}, title),
    el('span', { class: 'muted' }, `${frames.length} frames`)));
  if (zipUrl) {
    body.append(el('div', { class: 'result-actions' },
      el('a', { class: 'button', href: zipUrl, download: 'frames.zip' }, 'Download all as .zip')));
  }
  const grid = el('div', { class: 'frame-grid' });
  frames.forEach(f => grid.append(el('a', { class: 'frame-cell', href: f.url, download: f.name },
    el('span', { class: 'frame-index' }, String(f.index)),
    el('img', { src: f.thumb, alt: f.name }),
    el('span', { class: 'frame-meta' }, `${(f.delay_ms / 10).toFixed(0)} cs`))));
  body.append(grid);
}
