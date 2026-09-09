// Wires up every tool panel. Panels declare their endpoint in the markup and
// their fields by `name`, so most of them need no bespoke code here.

import { get, post, readFields } from './api.js';
import { createCropper } from './cropper.js';
import { state, subscribe } from './state.js';
import { linkDelayFps } from './timing.js';
import { showFrameGrid, showResult, upload } from './workspace.js';
import { $, $$, bytes, el, toast, withBusy } from './ui.js';

export function initTools() {
  $$('.tool-form').forEach(bindForm);
  bindRotate();
  bindRegionTools();
  bindAnalyzer();
  bindSpeedHints();
  bindEffectPresets();
  bindOptimizeMethod();
  bindAutoUse();
  loadFonts();
}

// "Blur", "Sharpen" and "Pixelate" in the effect preset list are really just
// their matching adjustment slider at a default amount, applied server-side
// whenever that slider is left at 0. Move the slider to match so the panel
// shows what will actually happen, instead of leaving it sitting at 0.
const PRESET_SLIDER_DEFAULTS = {
  blur: { blur: 4 },
  sharpen: { sharpen: 1 },
  pixelate: { pixelate: 12 },
};

function bindEffectPresets() {
  const select = $('#panel-effects select[name=name]');
  if (!select) return;
  select.addEventListener('change', () => {
    const defaults = PRESET_SLIDER_DEFAULTS[select.value] || {};
    ['blur', 'sharpen', 'pixelate'].forEach(name => {
      const slider = select.form.querySelector(`input[type=range][name=${name}]`);
      if (!slider) return;
      slider.value = name in defaults ? defaults[name] : 0;
      slider.dispatchEvent(new Event('input', { bubbles: true }));
    });
  });
}

const OPTIMIZE_HINTS = {
  lossy: 'Lossy compression uses gifsicle to fuzz pixel data for a smaller file.',
  colors: 'Colour reduction re-quantizes every frame against one shared, smaller palette.',
  drop: 'Dropping frames shortens playback but keeps colours and pixels untouched.',
  transparency: 'Strips redundant transparency/extension data that gifsicle otherwise keeps.',
  colormap: 'Forces every frame onto one shared colour table instead of per-frame tables. Set max colours to 256 to shrink the file without a visible quality loss.',
  combined: 'Runs lossy compression, colour reduction and transparency stripping together.',
  auto: 'Tries every method above, weakest first, keeping whichever attempt is smallest, until the target size is hit or three attempts in a row help not at all.',
};

// The Optimize tab's method dropdown only shows the fields that method
// actually uses, so switching between lossy/colour/drop/transparency/combined
// doesn't leave unrelated controls sitting on screen.
function bindOptimizeMethod() {
  const select = $('#panel-optimize select[name=method]');
  if (!select) return;
  const fields = $$('#panel-optimize .opt-field');
  const hint = $('#optimize-hint');

  const apply = () => {
    const method = select.value;
    fields.forEach(field => {
      field.hidden = !field.dataset.methods.split(',').includes(method);
    });
    if (hint) hint.textContent = OPTIMIZE_HINTS[method] || '';
    resetAutoProgress();
  };

  select.addEventListener('change', apply);
  apply();
}

const AUTO_CATEGORIES = ['lossy', 'colors', 'colormap', 'drop'];

// The "Use:" checkboxes let the automated run skip specific compression
// families entirely. At least one has to stay checked - unchecking the last
// remaining box would leave the algorithm nothing to try - so block that
// instead of only catching it once the run is already started.
function bindAutoUse() {
  const boxes = $$('#panel-optimize .auto-use input[type=checkbox]');
  if (!boxes.length) return;
  boxes.forEach(box => box.addEventListener('change', () => {
    if (!box.checked && boxes.every(b => !b.checked)) {
      box.checked = true;
      toast('At least one compression method has to stay in use.', 'error');
    }
  }));
}

function resetAutoProgress() {
  const panel = $('#auto-progress');
  if (!panel) return;
  $('#auto-stage').textContent = 'Ready';
  $('#auto-size').textContent = '';
  $('#auto-progress-fill').style.width = '0%';
  $('#auto-progress-fill').classList.remove('met', 'stalled');
  $('#auto-steps').innerHTML = '';
  const continueBtn = $('#auto-continue');
  continueBtn.hidden = true;
  continueBtn.onclick = null;
}

// Streams one automated-optimize request (initial or continuation) and
// updates the progress panel live as each newline-delimited JSON event
// arrives, so the UI shows which stage is running instead of going blank
// until the whole thing finishes. Returns the final "done" event.
async function streamAutoRequest(fd, ctx) {
  const { stage, size, fill, steps, originalBytes } = ctx;
  const res = await fetch('/api/optimize/auto', { method: 'POST', body: fd });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalEvent = null;

  const handleEvent = (evt) => {
    if (evt.done) {
      if (evt.error) throw new Error(evt.error);
      finalEvent = evt;
      return;
    }

    stage.textContent = `Step ${evt.step}/${evt.total}: ${evt.label}${evt.ok ? '' : ' (skipped)'}`;
    size.textContent = evt.size_bytes
      ? `${bytes(evt.best_bytes)} (best) - target ${bytes(evt.target_bytes)}`
      : `best so far: ${bytes(evt.best_bytes)} - target ${bytes(evt.target_bytes)}`;

    const base = originalBytes || evt.best_bytes;
    const denom = base - evt.target_bytes;
    const pct = denom > 0 ? ((base - evt.best_bytes) / denom) * 100 : 100;
    fill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
    fill.classList.toggle('met', evt.target_met);
    fill.classList.toggle('stalled', evt.stalled && !evt.target_met);

    const status = !evt.ok ? 'error' : evt.improved ? 'improved' : 'no-gain';
    steps.append(el('li', { class: `auto-step ${status}` },
      el('span', { class: 'auto-step-label' }, evt.label),
      el('span', { class: 'auto-step-size' },
        evt.ok ? bytes(evt.size_bytes) : (evt.error || 'failed'))));
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (line.trim()) handleEvent(JSON.parse(line));
    }
  }
  if (buffer.trim()) handleEvent(JSON.parse(buffer));
  if (!finalEvent) throw new Error('The automated run ended without a result');
  return finalEvent;
}

// Paints the outcome of a (sub-)run and, if the backend says more untried
// methods are left, wires up "Continue anyway" to pick up right where this
// one stopped instead of starting over.
function renderAutoFinal(finalEvent, ctx) {
  const { stage, size, fill } = ctx;
  stage.textContent = finalEvent.target_met
    ? 'Target reached'
    : finalEvent.resumable
      ? 'Paused - no improvement for a while, but other methods are untried'
      : 'Stopped - every method has now been tried, closest result kept (target not reached)';
  fill.classList.toggle('met', finalEvent.target_met);
  fill.classList.toggle('stalled', !finalEvent.target_met);
  if (finalEvent.target_met) fill.style.width = '100%';
  size.textContent = `${bytes(finalEvent.size_bytes)} - target ${bytes(finalEvent.target_bytes)}`;
  showResult(finalEvent, 'Automated Target Size');

  const continueBtn = $('#auto-continue');
  continueBtn.hidden = !finalEvent.resumable;
  continueBtn.onclick = finalEvent.resumable
    ? () => withBusy(continueBtn, () => runAutoContinuation(ctx, finalEvent))
    : null;
}

// The backend only overrides its own stall check for the stages tried within
// a single call, so "Continue anyway" is a fresh request that resumes from
// the next untried stage, uses the previous best result as the size to beat
// (and the fallback if nothing here beats it either), and forces at least
// 5 more stages to run regardless of whether they help.
async function runAutoContinuation(ctx, prevFinal) {
  const fd = new FormData();
  fd.append('target_mb', String(ctx.targetMb));
  fd.append('ignore', ctx.ignored.join(','));
  fd.append('job', prevFinal.job);
  fd.append('resume_from', String(prevFinal.next_step));
  fd.append('baseline_name', prevFinal.name);
  fd.append('force_steps', '5');

  ctx.stage.textContent = 'Continuing…';
  const finalEvent = await streamAutoRequest(fd, ctx);
  renderAutoFinal(finalEvent, ctx);
}

// Runs the automated "Target Size" method from scratch.
async function runAutoOptimize(form, fields) {
  const used = AUTO_CATEGORIES.filter(c => fields[`use_${c}`] === 'true');
  if (!used.length) {
    throw new Error('At least one compression method has to stay in use.');
  }
  const ignored = AUTO_CATEGORIES.filter(c => !used.includes(c));

  const targetMb = Number(fields.target_mb) || 1;
  const file = fileFrom(form);
  const fd = new FormData();
  fd.append('target_mb', String(targetMb));
  fd.append('ignore', ignored.join(','));
  if (fields.job) fd.append('job', fields.job);
  if (file) fd.append('file', file);

  resetAutoProgress();
  const ctx = {
    stage: $('#auto-stage'), size: $('#auto-size'), fill: $('#auto-progress-fill'),
    steps: $('#auto-steps'), originalBytes: file ? file.size : state.sizeBytes,
    targetMb, ignored,
  };
  ctx.stage.textContent = 'Starting…';

  const finalEvent = await streamAutoRequest(fd, ctx);
  renderAutoFinal(finalEvent, ctx);
}

// The Add Text tab offers whatever fonts this machine actually has.
async function loadFonts() {
  const select = $('#text-font');
  try {
    const { fonts } = await get('/api/fonts');
    fonts.forEach(f => select.append(el('option', { value: f.path }, f.name)));
  } catch {
    select.disabled = true;
  }
}

function fileFrom(form) {
  const input = form.querySelector('input[type=file]:not([data-extra])');
  return input?.files?.[0] || null;
}

function bindForm(form) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const endpoint = form.dataset.endpoint;
    const button = form.querySelector('button[type=submit]');
    const file = fileFrom(form);

    if (!file && !state.job) {
      return toast('Upload a file first', 'error');
    }
    const fields = readFields(form);
    if (state.job) fields.job = state.job;

    if (form.id === 'optimize-form' && fields.method === 'auto') {
      await withBusy(button, () => runAutoOptimize(form, fields));
      return;
    }

    const files = {};
    if (file) files.file = file;
    const extra = form.querySelector('input[type=file][data-extra]');
    if (extra?.files?.length) files[extra.dataset.extra] = extra.files[0];
    const beforeBytes = file ? file.size : state.sizeBytes;

    await withBusy(button, async () => {
      const r = await post(endpoint, fields, files);
      if (form.dataset.render === 'frames') {
        showFrameGrid('Split into frames', r.frames, r.zip_url);
      } else {
        showResult(r, form.dataset.label || 'Done', { beforeBytes });
      }
    });
  });
}

function bindRotate() {
  $$('#panel-rotate [data-degrees]').forEach(btn => {
    btn.addEventListener('click', () => runRotate(btn, { degrees: btn.dataset.degrees }));
  });
  $$('#panel-rotate [data-axis]').forEach(btn => {
    btn.addEventListener('click', () => runRotate(btn, { axis: btn.dataset.axis }, '/api/flip'));
  });
  $('#rotate-custom-run').addEventListener('click', (e) => {
    runRotate(e.target, {
      degrees: $('#rotate-degrees').value,
      background: $('#rotate-bg').value,
    });
  });
}

async function runRotate(button, fields, endpoint = '/api/rotate') {
  if (!state.job) return toast('Upload a file first', 'error');
  const preserveTransparency = $('#rotate-preserve-transparency').checked;
  const beforeBytes = state.sizeBytes;
  await withBusy(button, async () => {
    const r = await post(endpoint, { ...fields, preserve_transparency: preserveTransparency, job: state.job });
    showResult(r, 'Done', { beforeBytes });
  });
}

// Crop and Censor both drag a box on the preview and keep the numeric
// fields in sync with it.
function bindRegionTools() {
  [
    { panel: '#panel-crop', prefix: 'crop' },
    { panel: '#panel-censor', prefix: 'censor' },
  ].forEach(({ panel, prefix }) => {
    const stage = $(`#${prefix}-stage`);
    const fields = ['x', 'y', 'w', 'h'].map(k => $(`#${prefix}-${k}`));

    const cropper = createCropper(stage, sel => {
      fields[0].value = sel.x; fields[1].value = sel.y;
      fields[2].value = sel.w; fields[3].value = sel.h;
    });

    fields.forEach(input => input.addEventListener('input', () => {
      cropper.setSelection({
        x: Number(fields[0].value) || 0, y: Number(fields[1].value) || 0,
        w: Number(fields[2].value) || 0, h: Number(fields[3].value) || 0,
      });
    }));

    const ratioSelect = $(`#${prefix}-ratio`);
    if (ratioSelect) {
      ratioSelect.addEventListener('change', () => {
        const [a, b] = ratioSelect.value.split(':').map(Number);
        cropper.setRatio(ratioSelect.value === 'free' ? 0 : a / b);
      });
    }

    subscribe(s => cropper.load(s.url, s.name));
  });
}

function bindAnalyzer() {
  $('#analyze-run').addEventListener('click', async (e) => {
    if (!state.job) return toast('Upload a file first', 'error');
    await withBusy(e.target, async () => {
      const info = await post('/api/analyze', { job: state.job });
      renderAnalysis(info);
    });
  });
}

function renderAnalysis(info) {
  const out = $('#analyze-output');
  out.innerHTML = '';
  const rows = [
    ['File', info.filename], ['Type', info.kind], ['Format', info.format],
    ['Dimensions', info.width ? `${info.width} × ${info.height}` : '-'],
    ['Frames', info.nb_frames ?? '-'],
    ['Duration', info.duration_s ? `${info.duration_s} s` : '-'],
    ['Frame rate', info.fps ? `${info.fps} fps` : '-'],
    ['Average delay', info.avg_delay_ms ? `${info.avg_delay_ms} ms` : '-'],
    ['Loop', info.loop === 0 ? 'forever' : (info.loop ?? '-')],
    ['Transparency', info.transparency ? 'yes' : 'no'],
    ['Colour mode', info.mode || info.codec || '-'],
    ['File size', bytes(info.size_bytes)],
  ].filter(([, v]) => v !== undefined && v !== null);

  const table = el('table', { class: 'facts' });
  rows.forEach(([k, v]) => table.append(el('tr', {}, el('th', {}, k), el('td', {}, String(v)))));
  out.append(table);

  if (info.frames?.length) {
    const ft = el('table', { class: 'facts frames' },
      el('tr', {}, el('th', {}, '#'), el('th', {}, 'Delay'), el('th', {}, 'Disposal'), el('th', {}, 'Size')));
    info.frames.forEach(f => ft.append(el('tr', {},
      el('td', {}, String(f.index)),
      el('td', {}, `${f.delay_ms} ms`),
      el('td', {}, String(f.disposal ?? '-')),
      el('td', {}, f.size.join(' × ')))));
    out.append(el('h4', {}, 'Per-frame breakdown'), ft);
  }
}

// Speed tab: keep the "resulting duration" hint honest as values change.
function bindSpeedHints() {
  // Both fields are submitted, so they have to agree; the backend reads the
  // frame rate first and they round back to the same delay either way.
  linkDelayFps($('#speed-delay'), $('#speed-fps'));

  const factor = $('#speed-factor');
  const hint = $('#speed-hint');
  const update = () => {
    const d = state.meta?.duration_s;
    const f = Number(factor.value) || 1;
    hint.textContent = d ? `${d}s → ${(d / f).toFixed(2)}s at ${f}×` : '';
  };
  factor.addEventListener('input', update);
  subscribe(update);
}
