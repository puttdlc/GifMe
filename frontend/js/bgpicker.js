// The eyedropper + live preview behind the Remove Background tab.
//
// Two panes side by side: the source frame (click it to pick a colour) and
// the same frame with the current settings already applied, over a
// checkerboard. The preview runs the same distance/threshold/clamp maths the
// backend does, so dragging a slider answers "what will this do?" in a frame
// instead of a round trip - the server still does the real work, across every
// frame, when the tool is actually run.

import { el } from './ui.js';

// The working canvas is capped on its long edge: the preview is repainted on
// every slider tick, and a 4000px source would be 16M pixels of JavaScript
// per tick. Flat background areas survive the downscale unchanged, so picking
// a colour off it stays accurate.
const MAX_EDGE = 900;

export const toHex = (r, g, b) => `#${[r, g, b].map(v => v.toString(16).padStart(2, '0')).join('')}`;

export function parseHex(value) {
  const m = /^#?([0-9a-f]{6})$/i.exec((value || '').trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// "How much of this pixel to keep" per distance, 0-255 - the same curve as
// gifme/bgremove.py, as a 256-entry lookup.
function rampLut(threshold, clamp) {
  const span = clamp - threshold;
  const lut = new Uint8Array(256);
  for (let d = 0; d < 256; d++) {
    lut[d] = d <= threshold ? 0
      : span <= 0 || d >= clamp ? 255
        : Math.round((255 * (d - threshold)) / span);
  }
  return lut;
}

export function createBgPicker(container, { onPick } = {}) {
  let source = null;        // ImageData of the frame, at working size
  let sourceCanvas = null;  // what the user clicks on
  let outCanvas = null;     // the keyed preview
  let readout = null;       // the "under the cursor" chip
  let settings = { keys: [], threshold: 0, clamp: 0 };

  function message(text) {
    container.innerHTML = '';
    container.append(el('p', { class: 'hint' }, text));
    source = sourceCanvas = outCanvas = readout = null;
  }

  // Canvas pixel under a pointer event, accounting for the CSS scaling that
  // fits the canvas into the panel.
  function pixelAt(e) {
    const r = sourceCanvas.getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / r.width) * sourceCanvas.width);
    const y = Math.floor(((e.clientY - r.top) / r.height) * sourceCanvas.height);
    if (!source || x < 0 || y < 0 || x >= source.width || y >= source.height) return null;
    const i = (y * source.width + x) * 4;
    return [source.data[i], source.data[i + 1], source.data[i + 2]];
  }

  function paint() {
    if (!source || !outCanvas) return;
    const { keys, threshold, clamp } = settings;
    const out = outCanvas.getContext('2d').createImageData(source.width, source.height);
    out.data.set(source.data);

    if (keys.length) {
      const lut = rampLut(threshold, Math.max(threshold, clamp));
      const rgb = keys.map(parseHex).filter(Boolean);
      const px = out.data;
      for (let i = 0; i < px.length; i += 4) {
        let keep = 255;
        for (const [kr, kg, kb] of rgb) {
          // Chebyshev distance: the largest of the three channel differences.
          const d = Math.max(Math.abs(px[i] - kr), Math.abs(px[i + 1] - kg),
            Math.abs(px[i + 2] - kb));
          const k = lut[d];
          if (k < keep) keep = k;      // nearest key colour wins
          if (keep === 0) break;
        }
        if (keep < 255) px[i + 3] = (px[i + 3] * keep) / 255;
      }
    }
    outCanvas.getContext('2d').putImageData(out, 0, 0);
  }

  function pane(title, canvas, extra) {
    return el('div', { class: 'bg-pane' },
      el('span', { class: 'bg-pane-title' }, title, extra || ''),
      canvas);
  }

  return {
    // Draw `url` into the working canvases. Returns a promise so callers can
    // wait before sampling corners off it.
    load(url, name) {
      if (!url) {
        message('Upload a file to pick a background colour.');
        return Promise.resolve(false);
      }
      message('Loading preview…');
      return new Promise(resolve => {
        const img = new Image();
        img.onload = () => {
          const scale = Math.min(1, MAX_EDGE / Math.max(img.naturalWidth, img.naturalHeight));
          const w = Math.max(1, Math.round(img.naturalWidth * scale));
          const h = Math.max(1, Math.round(img.naturalHeight * scale));

          sourceCanvas = el('canvas', { width: w, height: h, class: 'bg-canvas pickable',
            title: 'Click to pick this colour' });
          outCanvas = el('canvas', { width: w, height: h, class: 'bg-canvas checkered' });
          const ctx = sourceCanvas.getContext('2d', { willReadFrequently: true });
          ctx.drawImage(img, 0, 0, w, h);
          source = ctx.getImageData(0, 0, w, h);

          readout = el('span', { class: 'bg-readout' });
          sourceCanvas.addEventListener('pointermove', e => {
            const p = pixelAt(e);
            readout.style.setProperty('--chip', p ? toHex(...p) : 'transparent');
            readout.textContent = p ? toHex(...p) : '';
            readout.classList.toggle('on', Boolean(p));
          });
          sourceCanvas.addEventListener('pointerleave', () => {
            readout.classList.remove('on');
            readout.textContent = '';
          });
          sourceCanvas.addEventListener('click', e => {
            const p = pixelAt(e);
            if (p) onPick?.(toHex(...p));
          });

          container.innerHTML = '';
          container.append(
            el('div', { class: 'bg-stage' },
              pane('Source - click to pick', sourceCanvas, readout),
              pane('Preview', outCanvas)),
            el('p', { class: 'hint' },
              'The preview is one frame at a reduced size; running the tool keys every '
              + 'frame of the file at full resolution.'));
          paint();
          resolve(true);
        };
        img.onerror = () => {
          message("That file can't be previewed here - background removal needs an image "
            + 'or a GIF.');
          resolve(false);
        };
        // Cache-busted the way every other preview in the app is, so a result
        // promoted to the input doesn't show the file it replaced.
        img.src = `${url}${url.includes('?') ? '&' : '?'}t=${Date.now()}`;
      });
    },

    // Repaint with new settings. Cheap enough to call on every slider tick.
    render(next) {
      settings = { ...settings, ...next };
      paint();
    },

    // The colours sitting in the four corners, deduped - the usual first
    // guess at "what is the background here".
    corners() {
      if (!source) return [];
      const inset = Math.max(1, Math.round(Math.min(source.width, source.height) * 0.01));
      const points = [
        [inset, inset], [source.width - 1 - inset, inset],
        [inset, source.height - 1 - inset], [source.width - 1 - inset, source.height - 1 - inset],
      ];
      const found = [];
      for (const [x, y] of points) {
        const i = (y * source.width + x) * 4;
        const c = [source.data[i], source.data[i + 1], source.data[i + 2]];
        // Corners of the same flat background differ by a shade or two after
        // quantization, and near-identical keys only cost time - so only keep
        // one that's genuinely a different colour.
        const near = found.some(f => Math.max(...parseHex(f).map((v, n) => Math.abs(v - c[n]))) < 12);
        if (!near) found.push(toHex(...c));
      }
      return found;
    },

    ready() { return Boolean(source); },
  };
}
