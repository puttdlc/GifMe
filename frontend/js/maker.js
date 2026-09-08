// The GIF Maker frame editor: thumbnails with per-frame delays, skip/copy,
// drag reordering, range toggles, and the GIF/effect options.

import { post } from './api.js';
import { setCurrent, state } from './state.js';
import { showResult } from './workspace.js';
import { MS_PER_CS, linkDelayFps } from './timing.js';
import { $, $$, el, toast, withBusy } from './ui.js';

let frames = [];
let job = null;
let serverCount = 0;
let gifTiming = null;          // the Delay time / Framerate pair in GIF options
let fadeTiming = null;

export function initMaker() {
  $('#maker-files').addEventListener('change', e => loadFrames(e.target.files, e.target));
  $('#maker-add').addEventListener('click', () => $('#maker-files').click());
  $('#maker-drop').addEventListener('click', () => $('#maker-files').click());

  ['dragover', 'dragenter'].forEach(ev => $('#maker-drop').addEventListener(ev, e => {
    e.preventDefault(); $('#maker-drop').classList.add('over');
  }));
  ['dragleave', 'drop'].forEach(ev => $('#maker-drop').addEventListener(ev, e => {
    e.preventDefault(); $('#maker-drop').classList.remove('over');
  }));
  $('#maker-drop').addEventListener('drop', e => loadFrames(e.dataTransfer.files));

  $('#range-skip').addEventListener('click', () => applyRange(true));
  $('#range-enable').addEventListener('click', () => applyRange(false));
  $('#nth-skip').addEventListener('click', () => applyEveryNth(true));
  $('#nth-enable').addEventListener('click', () => applyEveryNth(false));
  $('#maker-sort').addEventListener('click', () => { frames.sort(byName); renumber(); });
  $('#maker-reverse').addEventListener('click', () => { frames.reverse(); renumber(); });
  $('#maker-clear-skips').addEventListener('click', () => {
    frames.forEach(f => { f.skip = false; }); renumber();
  });
  $('#maker-clear').addEventListener('click', clearFrames);

  $('#pin-toggle').addEventListener('change', e => {
    $('#range-panel').classList.toggle('pinned', e.target.checked);
  });

  gifTiming = linkDelayFps($('#gif-delay'), $('#gif-fps'), {
    unitMs: MS_PER_CS,
    onChange: (ms) => {
      if (ms <= 0) return;
      frames.forEach(f => { f.delay_ms = ms; });
      renumber();
    },
  });
  fadeTiming = linkDelayFps($('#fx-fade-delay'), $('#fx-fade-fps'), { unitMs: MS_PER_CS });

  $('#fx-crossfade').addEventListener('change', e =>
    $('#crossfade-options').hidden = !e.target.checked);
  $('#fx-dispose').addEventListener('change', e =>
    $('#dispose-options').hidden = !e.target.checked);

  $('#maker-build').addEventListener('click', e => build(e.target));
}

const byName = (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true });

async function loadFrames(fileList, input) {
  if (!fileList?.length) return;
  await withBusy($('#maker-add'), async () => {
    const r = await post('/api/frames/load', { job: job || '', sort: 'name' },
                         { files: fileList });
    job = r.job;
    // Append only what is new, so local edits - copies, reordering, skips -
    // are not thrown away by a second upload.
    const added = r.frames.slice(serverCount);
    serverCount = r.frames.length;
    const startingFresh = frames.length === 0;
    seedDelays(added, startingFresh);
    frames = startingFresh ? r.frames.slice() : frames.concat(added);
    renumber();
    toast(`${added.length} frames added`);
  });
  if (input) input.value = '';
}

// Still images take their delay from the GIF options field; frames pulled out
// of a GIF or video keep the timing they already had, and the field follows
// them so the two never disagree.
function seedDelays(added, startingFresh) {
  const ms = gifTiming.delayMs() || 10 * MS_PER_CS;
  added.forEach(f => { if (f.still) f.delay_ms = ms; });

  const timed = added.filter(f => !f.still);
  if (startingFresh && timed.length) {
    const avg = timed.reduce((sum, f) => sum + f.delay_ms, 0) / timed.length;
    gifTiming.setDelayMs(Math.max(MS_PER_CS, avg));
  }
}

function clearFrames() {
  if (!frames.length) return;
  frames = [];
  job = null;
  serverCount = 0;
  renumber();
  toast('Frames cleared');
}

function renumber() {
  frames.forEach((f, i) => { f.index = i + 1; });
  renderFrames();
  const active = frames.filter(f => !f.skip).length;
  $('#maker-count').textContent = frames.length
    ? `${frames.length} frames loaded, ${active} in the GIF`
    : '';
  $('#maker-build').disabled = active === 0;
}

function renderFrames() {
  const list = $('#frame-list');
  list.innerHTML = '';
  $('#maker-toolbar').hidden = frames.length === 0;
  $('#maker-options').hidden = frames.length === 0;

  frames.forEach((f, i) => {
    const delayInput = el('input', {
      type: 'number', min: '1', class: 'frame-delay',
      value: String(Math.round(f.delay_ms / MS_PER_CS)),
    });
    const fpsInput = el('input', {
      type: 'number', min: '0.01', step: '0.01', class: 'frame-delay',
      value: f.delay_ms > 0 ? String(Number((1000 / f.delay_ms).toFixed(2))) : '',
    });
    linkDelayFps(delayInput, fpsInput, {
      unitMs: MS_PER_CS,
      onChange: (ms) => { f.delay_ms = ms || MS_PER_CS; },
    });

    const cell = el('div', {
      class: `frame${f.skip ? ' skipped' : ''}`, draggable: 'true', 'data-i': String(i),
    },
      el('span', { class: 'frame-index' }, String(f.index)),
      el('img', { src: f.thumb, alt: f.name, loading: 'lazy' }),
      el('label', { class: 'frame-delay-row' }, 'Delay:', delayInput),
      el('label', { class: 'frame-delay-row' }, 'FPS:', fpsInput),
      el('div', { class: 'frame-buttons' },
        el('button', {
          class: f.skip ? 'ghost' : 'danger small',
          onclick: () => { f.skip = !f.skip; renumber(); },
        }, f.skip ? 'use' : 'skip'),
        el('button', { class: 'small', onclick: () => copyFrame(i) }, 'copy'),
        el('button', { class: 'small ghost', onclick: () => { frames.splice(i, 1); renumber(); } }, '✕')),
    );

    cell.addEventListener('dragstart', e => e.dataTransfer.setData('text/plain', String(i)));
    cell.addEventListener('dragover', e => { e.preventDefault(); cell.classList.add('drop-target'); });
    cell.addEventListener('dragleave', () => cell.classList.remove('drop-target'));
    cell.addEventListener('drop', e => {
      e.preventDefault();
      cell.classList.remove('drop-target');
      const from = Number(e.dataTransfer.getData('text/plain'));
      if (Number.isNaN(from) || from === i) return;
      const [moved] = frames.splice(from, 1);
      frames.splice(i, 0, moved);
      renumber();
    });
    list.append(cell);
  });
}

function copyFrame(i) {
  frames.splice(i + 1, 0, { ...frames[i] });
  renumber();
}

function applyRange(skip) {
  const from = Number($('#range-from').value) || 1;
  const to = Number($('#range-to').value) || frames.length;
  frames.forEach((f, i) => {
    if (i + 1 >= from && i + 1 <= to) f.skip = skip;
  });
  renumber();
}

function applyEveryNth(skip) {
  const n = Math.max(2, Number($('#range-every').value) || 2);
  frames.forEach((f, i) => {
    if ((i + 1) % n === 0) f.skip = skip;
  });
  renumber();
}

async function build(button) {
  if (!frames.length) return toast('Upload some frames first', 'error');
  const payload = {
    frames: frames.map(f => ({ name: f.name, delay_ms: f.delay_ms, skip: f.skip })),
    delay_ms: gifTiming.delayMs() || 10 * MS_PER_CS,
    loop: Number($('#gif-loop').value) || 0,
    global_colormap: $('#gif-colormap').checked,
    converter: $('#gif-converter').value,
    dither: $('#gif-dither').checked,
    preserve_transparency: $('#gif-preserve-transparency').checked,
    crossfade: $('#fx-crossfade').checked,
    fade_steps: Number($('#fx-fade-steps').value) || 5,
    fade_delay_ms: fadeTiming.delayMs() || 6 * MS_PER_CS,
    dispose: $('#fx-dispose').checked,
    first_as_background: $('#fx-first-bg').checked,
    width: Number($('#gif-width').value) || 0,
    height: Number($('#gif-height').value) || 0,
  };
  await withBusy(button, async () => {
    const r = await post('/api/gif/build', { job, payload: JSON.stringify(payload) });
    showResult(r, 'GIF created');
  });
}
