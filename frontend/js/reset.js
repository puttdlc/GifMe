// A small "reset to default" button next to every slider and typeable field
// in the app - number, text, url, colour and textarea inputs, plus every
// range slider (wherever it shows its value: an <output>, or the typeable
// slider-input box some panels use instead). Each button resets its field
// to whatever value the HTML originally shipped with (`.defaultValue`, a
// standard DOM property no JS here has to maintain by hand) and fires the
// same events a real edit would, so every field it's paired with - a linked
// delay/FPS pair, a live preview - reacts exactly as if the user had typed
// it themselves.
//
// Left out on purpose: checkboxes and <select> aren't "typeable"; the crop
// and censor x/y/w/h fields are driven by dragging a box over the image, so
// there's no fixed default worth resetting to; the "paste a link" URL
// fields default to empty, so a reset would have nothing to do. Those are
// opted out with `data-no-reset` in the markup rather than guessed here.

import { el } from './ui.js';

function icon() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '13');
  svg.setAttribute('height', '13');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2.2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  ['M1 4v6h6', 'M3.51 15a9 9 0 1 0 2.13-9.36L1 10'].forEach(d => {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    svg.append(path);
  });
  return svg;
}

function resetButton(onReset) {
  const btn = el('button', {
    type: 'button', class: 'reset-btn',
    'aria-label': 'Reset to default', title: 'Reset to default',
  });
  btn.append(icon());
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    onReset();
  });
  return btn;
}

// Fires both events a real edit produces - 'input' for anything tracking
// live (a linked FPS field, a slider's own <output>), 'change' for anything
// that only reacts once a field is committed.
function fire(input) {
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

// A range slider's value display is either an <output> or a typeable
// slider-input box (see initSliders in ui.js) - either way, the range
// itself is the field with a `name` that actually gets submitted, so that's
// what the button resets; the display syncs to it the same way it does to
// any other change.
function wireSlider(range) {
  const host = range.closest('label.slider');
  if (!host || host.dataset.resetReady) return;
  host.dataset.resetReady = '1';
  const anchor = host.querySelector('output, input.slider-input') || range;
  anchor.after(resetButton(() => {
    range.value = range.defaultValue;
    fire(range);
  }));
}

// Plain typeable fields: the input is pulled out of the flow and replaced
// with a small inline-flex wrapper holding the input and its button side by
// side, so the button lands right next to the field regardless of whether
// the field itself is a block-level element (every input here is, by the
// app's own CSS).
function wireField(input) {
  if (input.dataset.resetReady) return;
  input.dataset.resetReady = '1';
  const wrap = el('span', { class: `field-reset${input.tagName === 'TEXTAREA' ? ' top' : ''}` });
  input.replaceWith(wrap);
  wrap.append(input, resetButton(() => {
    input.value = input.defaultValue;
    fire(input);
  }));
}

export function initResettable(root = document) {
  root.querySelectorAll('input[type=range]').forEach(wireSlider);

  root.querySelectorAll(
    'input[type=number], input[type=text], input[type=url], input[type=color], textarea',
  ).forEach((input) => {
    // Mirrors a range slider (see wireSlider above) - not a field of its own.
    if (input.classList.contains('slider-input') || input.closest('label.slider')) return;
    if (input.hasAttribute('data-no-reset')) return;
    // Per-frame fields in the GIF Maker's frame strip have no single fixed
    // default to reset to - each frame's own value *is* the setting.
    if (input.closest('.frame')) return;
    wireField(input);
  });
}
