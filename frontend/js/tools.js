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

    const files = {};
    if (file) files.file = file;
    const extra = form.querySelector('input[type=file][data-extra]');
    if (extra?.files?.length) files[extra.dataset.extra] = extra.files[0];

    await withBusy(button, async () => {
      const r = await post(endpoint, fields, files);
      if (form.dataset.render === 'frames') {
        showFrameGrid('Split into frames', r.frames, r.zip_url);
      } else {
        showResult(r, form.dataset.label || 'Done');
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
  await withBusy(button, async () => {
    const r = await post(endpoint, { ...fields, preserve_transparency: preserveTransparency, job: state.job });
    showResult(r, 'Done');
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
