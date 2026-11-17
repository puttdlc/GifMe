// Global top-of-page progress indicator for network activity - uploading a
// file, the backend processing it (ffmpeg/gifsicle/etc can take a while),
// and downloading a result. Self-hosted instances have no other sign that
// anything is happening in between, so this exists to make it obvious
// without blocking the rest of the UI - it's a slim bar plus a status
// pill, never an overlay.

import { el } from './ui.js';

let bar, fill, label, hideTimer;
let depth = 0;

// Once an indeterminate phase (progressBusy) has run a few seconds, an
// elapsed-time counter gets appended to its label ("Removing background…
// (12s)") so a slow tool still reads as "working" rather than "stuck", even
// though there's no real fraction to show. Tracked outside paint() since the
// counter's own tick must not stomp the caller's base text.
let tickTimer, busyBase, busyStart;

function ensure() {
  if (bar) return;
  fill = el('div', { class: 'global-progress-fill' });
  bar = el('div', { id: 'global-progress', class: 'global-progress' }, fill);
  label = el('div', { id: 'global-progress-label', class: 'global-progress-label' });
  document.body.append(bar, label);
}

function paint(text) {
  ensure();
  clearTimeout(hideTimer);
  bar.hidden = false;
  label.hidden = false;
  if (text) label.textContent = text;
}

function stopTicking() {
  clearInterval(tickTimer);
  tickTimer = null;
  busyBase = null;
}

// Call once per operation. Pair with exactly one progressEnd().
export function progressStart(text = 'Working…') {
  depth++;
  stopTicking();
  paint(text);
  fill.classList.remove('indeterminate');
  fill.style.width = '0%';
}

// A known fraction (0-1) of the current phase is done, e.g. bytes uploaded.
export function progressSet(fraction, text) {
  stopTicking();
  paint(text);
  fill.classList.remove('indeterminate');
  fill.style.width = `${Math.max(0, Math.min(1, fraction)) * 100}%`;
}

// No fraction to report (e.g. the server is busy encoding) - show motion
// anyway so it reads as "working", not "stuck". Called with the same text
// repeatedly (e.g. on every upload-progress tick) is fine - the elapsed timer
// only (re)starts when the label itself actually changes.
export function progressBusy(text) {
  if (text !== busyBase) {
    busyBase = text;
    busyStart = Date.now();
    clearInterval(tickTimer);
    tickTimer = setInterval(() => {
      const secs = Math.round((Date.now() - busyStart) / 1000);
      if (secs >= 3) paint(`${busyBase} (${secs}s)`);
    }, 1000);
  }
  paint(busyBase);
  fill.classList.add('indeterminate');
}

export function progressEnd() {
  depth = Math.max(0, depth - 1);
  if (depth > 0 || !bar) return;
  stopTicking();
  fill.classList.remove('indeterminate');
  fill.style.width = '100%';
  hideTimer = setTimeout(() => {
    bar.hidden = true;
    label.hidden = true;
    fill.style.width = '0%';
  }, 300);
}
