// Entry point: tabs, dependency banner, and module wiring.

import { get, post } from './api.js';
import { filesFromClipboard, pasteIntoHovered } from './filedrop.js';
import { initMaker, loadFrames } from './maker.js';
import { initResettable } from './reset.js';
import { clearCurrent, setCurrent, state } from './state.js';
import { initTools } from './tools.js';
import { initWorkspace, setUploaderVisible, upload } from './workspace.js';
import { $, $$, bytes, el, initCollapsibleFieldsets, initSliders, toast, withBusy } from './ui.js';

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

// A file dropped anywhere the app doesn't already have a dropzone - which,
// until now, meant *everywhere* outside the couple of small boxes that
// handle it - never reached any of GifMe's own code at all: with no
// listener calling preventDefault, the browser's own default action took
// over instead, navigating the tab away to show the raw file and silently
// wiping out the whole app. This is the safety net: dragover/drop are
// intercepted globally (only for an actual file drag - e.getFiles wouldn't
// exist for e.g. dragging selected text, which is left alone) so a miss
// never loses the app, and a drop that isn't already claimed by one of the
// specific dropzones (below, or the Overlay/Video to GIF fields in
// tools.js) still goes somewhere useful instead of nowhere: the GIF Maker's
// frame list while that tab is open, the shared workspace file otherwise -
// exactly as if it had landed squarely in the small box. A clipboard paste
// (Ctrl+V of an actual screenshot or copied image, not a link - see
// filedrop.js) falls back to the exact same place, for the same reason.
function isFileDrag(e) {
  return Array.from(e.dataTransfer?.types || []).includes('Files');
}

// Where an otherwise-unclaimed file (dropped or pasted) ends up.
function routeFiles(files) {
  if (!files.length) return;
  if ($('#tabs button.active')?.dataset.tab === 'make') loadFrames(files);
  else upload(files[0]);
}

function initGlobalDrop() {
  let depth = 0;   // nested dragenter/dragleave pairs - see MDN's own caveat
                   // on why a plain enter/leave pair isn't enough

  window.addEventListener('dragenter', (e) => {
    if (!isFileDrag(e)) return;
    depth++;
    document.body.classList.add('page-drop-active');
  });
  window.addEventListener('dragover', (e) => {
    if (isFileDrag(e)) e.preventDefault();
  });
  window.addEventListener('dragleave', (e) => {
    if (!isFileDrag(e)) return;
    depth = Math.max(0, depth - 1);
    if (depth === 0) document.body.classList.remove('page-drop-active');
  });
  window.addEventListener('drop', (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    depth = 0;
    document.body.classList.remove('page-drop-active');
    if (e.target.closest('.dropzone')) return;   // already handled there
    routeFiles([...(e.dataTransfer.files || [])]);
  });

  // Unlike a drop, a paste carries no coordinates - pasteIntoHovered()
  // covers "the pointer is sitting over one of the small file-drop fields
  // right now"; anything else (nothing under the pointer, or the pointer
  // is over ordinary page content) falls back to the same routing a drop
  // would get. A plain text paste is untouched either way: filesFromClipboard
  // comes back empty for one, so nothing here ever runs for it.
  window.addEventListener('paste', (e) => {
    if (pasteIntoHovered(e)) return;
    const files = filesFromClipboard(e);
    if (!files.length) return;
    e.preventDefault();
    routeFiles(files);
  });
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
initGlobalDrop();
setUploaderVisible($('#tabs button.active').dataset.tab !== 'make');
initHealth();
initWorkdir();
initWorkspace();
initMaker();
initTools();
initRecovery();
initSliders();
initCollapsibleFieldsets();
initResettable();
