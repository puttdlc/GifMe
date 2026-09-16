// The eyedropper + live preview behind the Remove Background tab.
//
// Two panes side by side: the source frame (click it to pick a colour) and
// the same frame with the current settings already applied, over a
// checkerboard. The preview runs the same maths the backend does - both the
// plain colour-distance ramp and, in Magic Select, the flood fill that
// restricts a colour to the region connected to where it was clicked - so
// dragging a slider or clicking a new point answers "what will this do?" in
// a frame instead of a round trip. The server still does the real work,
// across every frame at full resolution, when the tool is actually run.

import { attachExpand, collapseExpand, isExpandedWithin } from './expand.js';
import { el } from './ui.js';

// The working canvas is capped on its long edge: the preview is repainted on
// every slider tick, and a 4000px source would be 16M pixels of JavaScript
// per tick. Flat background areas survive the downscale unchanged, so picking
// a colour (or a flood-fill boundary) off it stays accurate enough to preview.
const MAX_EDGE = 900;

export const toHex = (r, g, b) => `#${[r, g, b].map(v => v.toString(16).padStart(2, '0')).join('')}`;

export function parseHex(value) {
  const m = /^#?([0-9a-f]{6})$/i.exec((value || '').trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// "How much of this pixel to keep" per distance, 0-255 - the same curve as
// gifme/bgremove.py's _ramp(), as a 256-entry lookup.
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

// Per-pixel Chebyshev distance (largest channel difference) to one key
// colour, over a whole RGBA buffer - the JS mirror of the ImageChops
// difference/lighter chain in bgremove.py's _key_frame.
function distanceTo(data, w, h, [kr, kg, kb]) {
  const out = new Uint8Array(w * h);
  for (let i = 0, p = 0; p < data.length; p += 4, i++) {
    out[i] = Math.max(Math.abs(data[p] - kr), Math.abs(data[p + 1] - kg),
      Math.abs(data[p + 2] - kb));
  }
  return out;
}

// Magic Select's connectivity gate: which pixels are 4-connected-reachable
// from (sx, sy) without ever stepping more than `clamp` away from the seed's
// own distance value - the JS mirror of ImageDraw.floodfill(thresh=clamp) in
// bgremove.py's _key_frame_magic. Iterative (a plain array as a stack), since
// a recursive flood fill would blow the call stack on any real image.
function floodReachable(dist, w, h, sx, sy, clamp) {
  const reached = new Uint8Array(w * h);
  const seedIdx = sy * w + sx;
  const background = dist[seedIdx];
  reached[seedIdx] = 1;
  const stack = [seedIdx];
  while (stack.length) {
    const idx = stack.pop();
    const x = idx % w;
    const y = (idx / w) | 0;
    // 4-connected neighbours, each visited at most once.
    if (x > 0 && !reached[idx - 1] && Math.abs(dist[idx - 1] - background) <= clamp) {
      reached[idx - 1] = 1; stack.push(idx - 1);
    }
    if (x < w - 1 && !reached[idx + 1] && Math.abs(dist[idx + 1] - background) <= clamp) {
      reached[idx + 1] = 1; stack.push(idx + 1);
    }
    if (y > 0 && !reached[idx - w] && Math.abs(dist[idx - w] - background) <= clamp) {
      reached[idx - w] = 1; stack.push(idx - w);
    }
    if (y < h - 1 && !reached[idx + w] && Math.abs(dist[idx + w] - background) <= clamp) {
      reached[idx + w] = 1; stack.push(idx + w);
    }
  }
  return reached;
}

// Fraction (0-1, top-left to bottom-right) <-> pixel index, on the same
// convention bgremove.py uses server-side (round(fraction * (extent - 1))),
// so a point picked here lands on the same relative spot at full resolution.
const fracToPx = (frac, extent) => Math.min(extent - 1, Math.max(0, Math.round(frac * (extent - 1))));

// Feathering's preview: a box blur over the finished mask. It's not the same
// algorithm as the server's Gaussian blur (ImageFilter.GaussianBlur), but a
// single box blur is a close enough stand-in for "the edge is now soft" at
// preview size - same spirit as the rest of this preview being an
// approximation, not a pixel-exact match of the real run.
function boxBlurH(src, dst, w, h, r) {
  for (let y = 0; y < h; y++) {
    const off = y * w;
    let sum = 0;
    for (let k = -r; k <= r; k++) sum += src[off + Math.min(w - 1, Math.max(0, k))];
    dst[off] = sum / (2 * r + 1);
    for (let x = 1; x < w; x++) {
      sum += src[off + Math.min(w - 1, x + r)] - src[off + Math.max(0, x - r - 1)];
      dst[off + x] = sum / (2 * r + 1);
    }
  }
}

function boxBlurV(src, dst, w, h, r) {
  for (let x = 0; x < w; x++) {
    let sum = 0;
    for (let k = -r; k <= r; k++) sum += src[Math.min(h - 1, Math.max(0, k)) * w + x];
    dst[x] = sum / (2 * r + 1);
    for (let y = 1; y < h; y++) {
      sum += src[Math.min(h - 1, y + r) * w + x] - src[Math.max(0, y - r - 1) * w + x];
      dst[y * w + x] = sum / (2 * r + 1);
    }
  }
}

// Blurs `mask` (a w*h alpha buffer) by `radius` preview pixels. radius <= 0
// is a no-op. Mirrors gifme/bgremove.py's _feather(): "inward" (default)
// never lets a pixel's alpha end up higher than it started, so a background
// pixel - still the background's own colour - can't pick up any opacity and
// bleed through as a colour ring; the softening only eats into the subject's
// own edge instead. "glow" is the plain, symmetric blur that does let that
// happen, for whoever wants the more diffuse look on purpose.
function featherMask(mask, w, h, radius, mode) {
  const r = Math.round(radius);
  if (r <= 0) return mask;
  const tmp = new Float32Array(w * h);
  const blurred = new Float32Array(w * h);
  boxBlurH(mask, tmp, w, h, r);
  boxBlurV(tmp, blurred, w, h, r);
  const out = new Uint8ClampedArray(w * h);
  if (mode === 'inward') {
    for (let i = 0; i < out.length; i++) out[i] = Math.min(mask[i], blurred[i]);
  } else {
    out.set(blurred);
  }
  return out;
}

export function createBgPicker(container, { onPick } = {}) {
  let source = null;        // ImageData of the frame, at working size
  let sourceCanvas = null;  // what the user clicks on
  let sourceCtx = null;     // its 2D context - reused to redraw + overlay seed dots
  let outCanvas = null;     // the keyed preview
  let readout = null;       // the "under the cursor" chip
  let previewScale = 1;     // preview px per full-resolution px - see load()
  let settings = { keys: [], points: [], threshold: 0, clamp: 0, magic: true,
    feather: true, featherAmount: 0, featherMode: 'inward' };
  let paintScheduled = false;

  function message(text) {
    if (isExpandedWithin(container)) collapseExpand({ immediate: true });
    container.innerHTML = '';
    container.append(el('p', { class: 'hint' }, text));
    source = sourceCanvas = sourceCtx = outCanvas = readout = null;
  }

  // Canvas pixel under a pointer event, accounting for the CSS scaling that
  // fits the canvas into the panel.
  function pixelAt(e) {
    const r = sourceCanvas.getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / r.width) * sourceCanvas.width);
    const y = Math.floor(((e.clientY - r.top) / r.height) * sourceCanvas.height);
    if (!source || x < 0 || y < 0 || x >= source.width || y >= source.height) return null;
    const i = (y * source.width + x) * 4;
    return { r: source.data[i], g: source.data[i + 1], b: source.data[i + 2], x, y };
  }

  // A small marker at each Magic Select seed point, on the source pane - so
  // it's clear at a glance where each click landed and which region of the
  // preview it's responsible for. Two-tone (white halo, dark ring) so it
  // stays visible over both light and dark image content.
  function drawSeedDot(x, y, w, h) {
    const r = Math.max(3, Math.min(9, Math.round(Math.min(w, h) * 0.018)));
    sourceCtx.beginPath();
    sourceCtx.arc(x, y, r + 2, 0, Math.PI * 2);
    sourceCtx.fillStyle = 'rgba(255,255,255,0.95)';
    sourceCtx.fill();
    sourceCtx.beginPath();
    sourceCtx.arc(x, y, r, 0, Math.PI * 2);
    sourceCtx.fillStyle = '#2f7fd8';
    sourceCtx.fill();
    sourceCtx.lineWidth = 1.5;
    sourceCtx.strokeStyle = 'rgba(0,0,0,0.65)';
    sourceCtx.stroke();
  }

  function paint() {
    if (!source || !outCanvas) return;
    const { keys, points, threshold, clamp, magic, feather, featherAmount, featherMode } = settings;
    const w = source.width, h = source.height;

    // The source pane always starts from the pristine frame - any dots drawn
    // last time have to be erased before a possibly-different set is drawn,
    // e.g. after a point is removed.
    if (sourceCtx) {
      sourceCtx.putImageData(source, 0, 0);
      if (magic) {
        points.forEach(pt => { if (pt) drawSeedDot(fracToPx(pt.x, w), fracToPx(pt.y, h), w, h); });
      }
    }
    const out = outCanvas.getContext('2d').createImageData(w, h);
    out.data.set(source.data);

    if (keys.length) {
      const lut = rampLut(threshold, Math.max(threshold, clamp));
      const px = out.data;
      // "keep" starts at 255 (untouched) everywhere and each key colour can
      // only lower it - darker()/min() across keys, same as the backend.
      let keep = new Uint8Array(w * h).fill(255);

      keys.forEach((keyHex, i) => {
        const rgb = parseHex(keyHex);
        if (!rgb) return;
        const dist = distanceTo(source.data, w, h, rgb);
        let gate = null;   // null = ungated (whole frame eligible), else a reached mask
        if (magic) {
          const pt = points[i];
          if (!pt) return;  // no seed for this key yet - nothing to preview
          gate = floodReachable(dist, w, h, fracToPx(pt.x, w), fracToPx(pt.y, h),
            Math.max(threshold, clamp));
        }
        for (let p = 0; p < keep.length; p++) {
          if (gate && !gate[p]) continue;      // outside the flooded region: untouched
          const k = lut[dist[p]];
          if (k < keep[p]) keep[p] = k;
        }
      });

      // The blur radius is in full-resolution pixels (what the backend
      // works at); scaled down by the same factor the preview itself was,
      // so a given amount looks proportionally the same softness here as in
      // the real result, not fixed at its raw pixel count on a shrunk canvas.
      if (feather && featherAmount > 0) {
        keep = featherMask(keep, w, h, featherAmount * previewScale, featherMode);
      }

      for (let p = 0, i = 3; p < keep.length; p++, i += 4) {
        if (keep[p] < 255) px[i] = (px[i] * keep[p]) / 255;
      }
    }
    outCanvas.getContext('2d').putImageData(out, 0, 0);
  }

  // Slider drags fire 'input' continuously; coalescing repaints onto the
  // next animation frame keeps a flood-fill-heavy preview from queuing up
  // behind the pointer instead of tracking it.
  function schedulePaint() {
    if (paintScheduled) return;
    paintScheduled = true;
    requestAnimationFrame(() => { paintScheduled = false; paint(); });
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
          previewScale = scale;

          sourceCanvas = el('canvas', { width: w, height: h, class: 'bg-canvas pickable',
            title: 'Click to pick this colour' });
          outCanvas = el('canvas', { width: w, height: h, class: 'bg-canvas checkered' });
          sourceCtx = sourceCanvas.getContext('2d', { willReadFrequently: true });
          sourceCtx.drawImage(img, 0, 0, w, h);
          source = sourceCtx.getImageData(0, 0, w, h);

          readout = el('span', { class: 'bg-readout' });
          sourceCanvas.addEventListener('pointermove', e => {
            const p = pixelAt(e);
            readout.style.setProperty('--chip', p ? toHex(p.r, p.g, p.b) : 'transparent');
            readout.textContent = p ? toHex(p.r, p.g, p.b) : '';
            readout.classList.toggle('on', Boolean(p));
          });
          sourceCanvas.addEventListener('pointerleave', () => {
            readout.classList.remove('on');
            readout.textContent = '';
          });
          sourceCanvas.addEventListener('click', e => {
            const p = pixelAt(e);
            if (p) onPick?.(toHex(p.r, p.g, p.b), { x: p.x / Math.max(1, w - 1), y: p.y / Math.max(1, h - 1) });
          });

          container.innerHTML = '';
          const stage = el('div', { class: 'bg-stage' },
            pane('Source - click to pick', sourceCanvas, readout),
            pane('Preview', outCanvas));
          attachExpand(stage);
          container.append(
            stage,
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

    // Repaint with new settings. `points` (parallel to `keys`) are fractions,
    // {x, y} each 0-1, ignored unless `magic` is true. Cheap enough to call
    // on every slider tick - see schedulePaint above for how that's kept smooth.
    render(next) {
      settings = { ...settings, ...next };
      schedulePaint();
    },

    // The colours (and their pixel position, as the same 0-1 fractions
    // `render` takes in `points`) sitting in the four corners, deduped - the
    // usual first guess at "what is the background here".
    corners() {
      if (!source) return [];
      const w = source.width, h = source.height;
      const inset = Math.max(1, Math.round(Math.min(w, h) * 0.01));
      const spots = [
        [inset, inset], [w - 1 - inset, inset],
        [inset, h - 1 - inset], [w - 1 - inset, h - 1 - inset],
      ];
      const found = [];
      for (const [x, y] of spots) {
        const i = (y * w + x) * 4;
        const c = [source.data[i], source.data[i + 1], source.data[i + 2]];
        // Corners of the same flat background differ by a shade or two after
        // quantization, and near-identical keys only cost time - so only keep
        // one that's genuinely a different colour.
        const near = found.some(f => Math.max(...parseHex(f.hex).map((v, n) => Math.abs(v - c[n]))) < 12);
        if (!near) found.push({ hex: toHex(...c), x: x / Math.max(1, w - 1), y: y / Math.max(1, h - 1) });
      }
      return found;
    },

    ready() { return Boolean(source); },
  };
}
