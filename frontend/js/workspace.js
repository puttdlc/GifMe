// The sticky bar showing the file every tool is currently working on, plus
// the result panel. Uploading once and chaining tools is the whole point.

import { post } from './api.js';
import { downloadWithProgress } from './download.js';
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

  $('#ws-download').addEventListener('click', () => {
    if (!state.url) return;
    downloadWithProgress(state.url, state.name);
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
  $('#ws-download').disabled = false;
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
    const video = el('video', { src: bust, controls: '', autoplay: '', loop: '', muted: '' });
    // A video created via document.createElement doesn't reliably honour the
    // "muted" attribute alone (that only sets defaultMuted) - both the
    // input preview (workspace bar) and the output preview (result panel)
    // go through here, so setting the actual property covers both.
    video.muted = true;
    video.defaultMuted = true;
    return video;
  }
  return el('img', { src: bust, alt: name, class: small ? 'thumb' : '' });
}

// A colored "X% smaller/bigger" (or "about the same size") node comparing
// the file going into a tool against what came out of it - green shrank,
// red grew, gray is close enough not to matter. Every tab's result gets
// this, not just Optimize, so it's generic over any before/after size pair.
function sizeChangeNode(beforeBytes, afterBytes) {
  if (!beforeBytes || !afterBytes) return null;
  const pct = ((beforeBytes - afterBytes) / beforeBytes) * 100;
  const abs = Math.abs(pct);
  if (abs < 1) return el('span', { class: 'size-delta unchanged' }, 'about the same size');
  const cls = pct > 0 ? 'smaller' : 'bigger';
  return el('span', { class: `size-delta ${cls}` }, `${abs.toFixed(1)}% ${cls}`);
}

// Show a finished operation. It stays a side-by-side result until the user
// explicitly promotes it to the working file with "Set as input".
// `opts.beforeBytes` is the input file's size, for tools the backend doesn't
// already report an original_bytes/saved_percent pair for.
export function showResult(result, label = 'Done', opts = {}) {
  const body = $('#result-body');
  body.innerHTML = '';
  const notes = [];
  if (result.meta?.width) notes.push(`${result.meta.width}×${result.meta.height}`);
  if (result.meta?.nb_frames > 1) notes.push(`${result.meta.nb_frames} frames`);
  notes.push(bytes(result.size_bytes));
  if (result.frame_count) notes.push(`${result.frame_count} frames used`);

  const delta = sizeChangeNode(result.original_bytes ?? opts.beforeBytes, result.size_bytes);

  const useBtn = el('button', { class: 'button' }, 'Set as input');
  useBtn.addEventListener('click', async () => {
    const r = await withBusy(useBtn, () => post('/api/set-input', { job: result.job, name: result.name }));
    if (!r) return;
    setCurrent(r);
    useBtn.disabled = true;
    useBtn.textContent = 'In use as input';
    toast(`${result.name} is now the working file`);
  });

  const summary = el('span', { class: 'muted' }, notes.join(' · '));
  if (delta) summary.append(' · ', delta);

  const downloadBtn = el('button', { class: 'button', type: 'button' }, `Download ${result.name}`);
  downloadBtn.addEventListener('click', () => downloadWithProgress(result.url, result.name));

  body.append(
    el('div', { class: 'result-head' },
      el('strong', {}, label),
      summary),
    previewNode(result.url, result.name),
    el('div', { class: 'result-actions' },
      downloadBtn,
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
    const zipBtn = el('button', { class: 'button', type: 'button' }, 'Download all as .zip');
    zipBtn.addEventListener('click', () => downloadWithProgress(zipUrl, 'frames.zip'));
    body.append(el('div', { class: 'result-actions' }, zipBtn));
  }
  const grid = el('div', { class: 'frame-grid' });
  frames.forEach(f => grid.append(el('a', { class: 'frame-cell', href: f.url, download: f.name },
    el('span', { class: 'frame-index' }, String(f.index)),
    el('img', { src: f.thumb, alt: f.name }),
    el('span', { class: 'frame-meta' }, `${(f.delay_ms / 10).toFixed(0)} cs`))));
  body.append(grid);
}
