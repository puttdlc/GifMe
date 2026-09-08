// The selection box shared by the Crop and Censor tabs. The box is always
// there: drag its body to move it, pull one of the eight handles to resize it,
// or nudge it with the arrow keys. Coordinates are reported in the image's
// real pixels, not the on-screen preview size.

import { el } from './ui.js';

const MIN = 8;                 // smallest selection, in image pixels
const DIRS = ['nw', 'n', 'ne', 'w', 'e', 'sw', 's', 'se'];

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export function createCropper(container, onChange) {
  let img = null;
  let box = null;
  let sel = { x: 0, y: 0, w: 0, h: 0 };
  let ratio = 0;               // 0 = free
  let drag = null;             // { dir | 'move', start, from }

  const bounds = () => ({
    w: img?.naturalWidth || 0,
    h: img?.naturalHeight || 0,
  });

  function scale() {
    if (!img?.naturalWidth || !img.clientWidth) return 1;
    return img.naturalWidth / img.clientWidth;
  }

  function paint() {
    if (!box) return;
    const s = scale();
    box.style.left = `${sel.x / s}px`;
    box.style.top = `${sel.y / s}px`;
    box.style.width = `${sel.w / s}px`;
    box.style.height = `${sel.h / s}px`;
    box.hidden = sel.w <= 0 || sel.h <= 0;
  }

  function emit() {
    onChange?.({
      x: Math.round(sel.x), y: Math.round(sel.y),
      w: Math.round(sel.w), h: Math.round(sel.h),
    });
  }

  function commit(next) {
    sel = next;
    paint();
    emit();
  }

  function pointIn(e) {
    const r = img.getBoundingClientRect();
    const s = scale();
    const b = bounds();
    return {
      x: clamp((e.clientX - r.left) * s, 0, b.w),
      y: clamp((e.clientY - r.top) * s, 0, b.h),
    };
  }

  // Resize from one handle: the opposite edge (or the centre line, for a side
  // handle) stays put, and an aspect ratio shrinks the box to fit rather than
  // letting it spill off the image.
  function resized(dir, p, from) {
    const b = bounds();
    const right = from.x + from.w;
    const bottom = from.y + from.h;
    const cx = from.x + from.w / 2;
    const cy = from.y + from.h / 2;
    const west = dir.includes('w');
    const east = dir.includes('e');
    const north = dir.includes('n');
    const south = dir.includes('s');

    let w = west ? right - p.x : east ? p.x - from.x : from.w;
    let h = north ? bottom - p.y : south ? p.y - from.y : from.h;

    const maxW = west ? right : east ? b.w - from.x : 2 * Math.min(cx, b.w - cx);
    const maxH = north ? bottom : south ? b.h - from.y : 2 * Math.min(cy, b.h - cy);

    if (ratio) {
      if (dir === 'n' || dir === 's') w = h * ratio;
      else h = w / ratio;
      const fit = Math.min(1, maxW / w, maxH / h);
      w *= fit;
      h *= fit;
      if (w < MIN || h < MIN) {
        const grow = Math.max(MIN / w, MIN / h);
        w *= grow;
        h *= grow;
      }
    } else {
      w = clamp(w, MIN, maxW);
      h = clamp(h, MIN, maxH);
    }

    const x = west ? right - w : east ? from.x : cx - w / 2;
    const y = north ? bottom - h : south ? from.y : cy - h / 2;
    return {
      x: clamp(x, 0, Math.max(0, b.w - w)),
      y: clamp(y, 0, Math.max(0, b.h - h)),
      w, h,
    };
  }

  function moved(dx, dy, from) {
    const b = bounds();
    return {
      ...from,
      x: clamp(from.x + dx, 0, Math.max(0, b.w - from.w)),
      y: clamp(from.y + dy, 0, Math.max(0, b.h - from.h)),
    };
  }

  function onDown(e) {
    if (!img?.naturalWidth) return;
    e.preventDefault();
    box.focus({ preventScroll: true });
    drag = {
      dir: e.target.dataset.dir || 'move',
      start: pointIn(e),
      from: { ...sel },
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: true });
  }

  function onMove(e) {
    if (!drag) return;
    const p = pointIn(e);
    commit(drag.dir === 'move'
      ? moved(p.x - drag.start.x, p.y - drag.start.y, drag.from)
      : resized(drag.dir, p, drag.from));
  }

  function onUp() {
    drag = null;
    window.removeEventListener('pointermove', onMove);
  }

  // Arrow keys nudge by a pixel for the last bit of precision; Shift makes it
  // ten, and Alt resizes from the bottom-right corner instead of moving.
  function onKey(e) {
    const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!step || !img?.naturalWidth) return;
    e.preventDefault();
    const [dx, dy] = step.map(n => n * (e.shiftKey ? 10 : 1));
    if (e.altKey) {
      commit(resized('se', { x: sel.x + sel.w + dx, y: sel.y + sel.h + dy }, { ...sel }));
    } else {
      commit(moved(dx, dy, { ...sel }));
    }
  }

  // Re-shape the current selection to a newly chosen aspect ratio, keeping its
  // top-left corner where it is.
  function applyRatio() {
    if (!ratio || !img?.naturalWidth) return;
    commit(resized('se', { x: sel.x + sel.w, y: sel.y + sel.h }, { ...sel }));
  }

  return {
    load(url, name) {
      container.innerHTML = '';
      if (!url) {
        container.append(el('p', { class: 'hint' }, 'Upload a file to set a selection.'));
        img = box = null;
        return;
      }
      const wrap = el('div', { class: 'crop-stage' });
      img = el('img', { src: `${url}?t=${Date.now()}`, alt: name || 'preview' });
      box = el('div', { class: 'crop-box', tabindex: '0', hidden: '' },
        ...DIRS.map(d => el('span', { class: `crop-handle ${d}`, 'data-dir': d })));
      box.addEventListener('pointerdown', onDown);
      box.addEventListener('keydown', onKey);
      wrap.append(img, box);
      container.append(wrap, el('p', { class: 'hint' },
        'Drag the box to move it, pull a handle to resize, or type exact values below. '
        + 'Arrow keys nudge by 1px (Shift 10px, Alt resizes).'));
      img.addEventListener('load', () => {
        commit({ x: 0, y: 0, w: img.naturalWidth, h: img.naturalHeight });
      });
      window.addEventListener('resize', paint);
    },
    setRatio(r) { ratio = r; applyRatio(); },
    setSelection(next) {
      const b = bounds();
      const merged = { ...sel, ...next };
      sel = b.w ? {
        w: clamp(merged.w, 0, b.w),
        h: clamp(merged.h, 0, b.h),
        x: clamp(merged.x, 0, Math.max(0, b.w - merged.w)),
        y: clamp(merged.y, 0, Math.max(0, b.h - merged.h)),
      } : merged;
      paint();
    },
    selection() { return { ...sel }; },
  };
}
