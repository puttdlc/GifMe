// Entry point: tabs, dependency banner, and module wiring.

import { get } from './api.js';
import { initMaker } from './maker.js';
import { initTools } from './tools.js';
import { initWorkspace, setUploaderVisible } from './workspace.js';
import { $, $$, el, initSliders } from './ui.js';

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

initTabs();
setUploaderVisible($('#tabs button.active').dataset.tab !== 'make');
initHealth();
initWorkspace();
initMaker();
initTools();
initSliders();
