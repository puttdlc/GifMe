// Entry point: tabs, dependency banner, and module wiring.

import { get, post } from './api.js';
import { initMaker } from './maker.js';
import { clearCurrent, setCurrent, state } from './state.js';
import { initTools } from './tools.js';
import { initWorkspace, setUploaderVisible } from './workspace.js';
import { $, $$, bytes, el, initSliders, toast, withBusy } from './ui.js';

function initTabs() {
  const buttons = $$('#tabs button');
  buttons.forEach(btn => btn.addEventListener('click', () => {
    buttons.forEach(b => b.classList.remove('active'));
    $$('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    $(`#panel-${btn.dataset.tab}`).classList.add('active');
    setUploaderVisible(btn.dataset.tab !== 'make');
    location.hash = btn.dataset.tab;
  }));

  const wanted = location.hash.slice(1);
  const target = buttons.find(b => b.dataset.tab === wanted);
  if (target) target.click();
}

const ENGINE_LABELS = {
  ffmpeg: 'ffmpeg', ffprobe: 'ffprobe', pillow: 'Pillow', gifsicle: 'gifsicle',
  imagemagick: 'ImageMagick', avif: 'AVIF (avifenc)', jxl: 'JPEG XL (cjxl)',
};

async function initHealth() {
  const box = $('#health');
  const panel = $('#health-panel');

  box.addEventListener('click', () => { panel.hidden = !panel.hidden; });
  document.addEventListener('click', (e) => {
    if (!panel.hidden && !e.target.closest('#health-wrap')) panel.hidden = true;
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') panel.hidden = true;
  });

  try {
    const h = await get('/api/health');
    const entries = Object.entries(h);
    const missing = entries.filter(([, info]) => !info.available).map(([n]) => n);
    if (!missing.length) {
      box.textContent = '✓ all engines available';
      box.className = 'ok';
    } else {
      box.className = 'warn';
      box.textContent = `optional engines missing: ${missing.join(', ')}`;
    }
    panel.innerHTML = '';
    entries.forEach(([name, info]) => {
      panel.append(el('div', { class: `health-row ${info.available ? 'ok' : ''}` },
        el('span', { class: 'name' }, el('span', { class: 'dot' }), ENGINE_LABELS[name] || name),
        el('span', { class: 'ver' }, info.available ? (info.version || 'available') : 'not found')));
    });
  } catch {
    box.textContent = '⚠ backend unreachable';
    box.className = 'warn';
    panel.innerHTML = '';
  }
}

// The output-folder chip: file count + total size of everything GifMe has
// ever written to disk, with buttons to reveal or wipe that folder. Also
// what gates the "recover latest" button next to it - it only makes sense
// to offer once there's actually something in the folder to grab.
async function refreshWorkdirStats() {
  const label = $('#workdir-stats');
  const recoverBtn = $('#recover-job');
  try {
    const { count, size_bytes, path } = await get('/api/workdir');
    label.textContent = `${count} file${count === 1 ? '' : 's'}, ${bytes(size_bytes)}`;
    if (path) $('#workdir-open').title = path;
    recoverBtn.disabled = count === 0;
  } catch {
    label.textContent = '';
    recoverBtn.disabled = true;
  }
}

function initWorkdir() {
  $('#workdir-open').addEventListener('click', async () => {
    try {
      const r = await post('/api/workdir/open', {});
      // Headless setups (containers, remote dev environments) have no GUI to
      // open a file manager in at all - that's not an error, just tell them
      // where the folder is instead (it's also always in this button's title).
      if (!r.opened) {
        toast(r.docker
          ? `Running in Docker, so this can't open a folder on your machine - it's at ${r.path} on the host`
          : `No file manager available here - output folder: ${r.path}`);
      }
    } catch (e) {
      toast(e.message || String(e), 'error');
    }
  });

  $('#workdir-clear').addEventListener('click', async () => {
    // Two prompts: first, only if a file is actively being worked on, ask
    // whether to take it down too; then a final go/no-go on the wipe itself.
    let keepCurrent = false;
    if (state.job) {
      keepCurrent = !confirm('Delete the current working input as well? OK removes it too, Cancel keeps it.');
    }
    if (!confirm('Proceed with clearing the output folder? This cannot be undone.')) return;

    try {
      await post('/api/workdir/clear', keepCurrent ? { keep_job: state.job } : {});
      if (!keepCurrent) clearCurrent();
      toast(keepCurrent ? 'Output folder cleared - current file kept' : 'Output folder cleared');
      refreshWorkdirStats();
    } catch (e) {
      toast(e.message || String(e), 'error');
    }
  });

  refreshWorkdirStats();
  setInterval(refreshWorkdirStats, 15000);
}

// A page refresh wipes the in-memory `state` (job/file/etc), but the actual
// files are still sitting in the output folder on the backend. This button
// is the recovery path: enabled whenever the output folder holds anything
// at all (see refreshWorkdirStats above), it grabs whichever file was most
// recently touched anywhere in there and loads it as the working input -
// no need for the browser to have remembered which job it was.
function initRecovery() {
  const btn = $('#recover-job');
  btn.addEventListener('click', () => withBusy(btn, async () => {
    try {
      const r = await get('/api/workdir/latest');
      setCurrent(r);
      toast(`Loaded ${r.name} as the working input`);
    } catch (e) {
      toast(e.message || 'Nothing to recover - the output folder is empty', 'error');
      refreshWorkdirStats();
    }
  }));
}

initTabs();
setUploaderVisible($('#tabs button.active').dataset.tab !== 'make');
initHealth();
initWorkdir();
initWorkspace();
initMaker();
initTools();
initRecovery();
initSliders();
