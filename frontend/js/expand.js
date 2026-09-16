// Fullscreen "expand" overlay shared by every media preview in the app (the
// workspace/result thumbnails, the crop/censor stage, and the remove-
// background picker). Expanding moves the real preview node into a dimmed,
// centred overlay instead of cloning it, so anything interactive living
// inside it - the crop box, Magic Select's canvases - keeps working exactly
// as it does inline, at whatever size the overlay renders it at; collapsing
// moves it straight back to where it came from.

import { el } from './ui.js';

// Feather-style corner-bracket icons: pointing outward (expand) and inward
// (collapse), sharing one 24x24 line-icon language with the rest of the app.
const EXPAND_PATHS = [
  'M8 3H5a2 2 0 0 0-2 2v3', 'M21 8V5a2 2 0 0 0-2-2h-3',
  'M3 16v3a2 2 0 0 0 2 2h3', 'M16 21h3a2 2 0 0 0 2-2v-3',
];
const COLLAPSE_PATHS = [
  'M8 3v3a2 2 0 0 1-2 2H3', 'M21 8h-3a2 2 0 0 1-2-2V3',
  'M3 16h3a2 2 0 0 1 2 2v3', 'M16 21v-3a2 2 0 0 1 2-2h3',
];

function icon(paths) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '16');
  svg.setAttribute('height', '16');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2.2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  paths.forEach(d => {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    svg.append(path);
  });
  return svg;
}

let overlay = null;
let open = null;   // { node, placeholder, button }

function ensureOverlay() {
  if (overlay) return overlay;
  overlay = el('div', { id: 'expand-overlay' });
  // Only a click on the dimmed backdrop itself closes it - a click that
  // bubbles up from the image, crop box or Magic Select canvas has a
  // different e.target and is left alone.
  overlay.addEventListener('click', (e) => { if (e.target === overlay) collapseExpand(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && open) collapseExpand();
  });
  document.body.append(overlay);
  return overlay;
}

function setButtonState(button, expanded) {
  button.innerHTML = '';
  button.append(icon(expanded ? COLLAPSE_PATHS : EXPAND_PATHS));
  button.setAttribute('aria-label', expanded ? 'Collapse' : 'Expand');
  button.title = expanded ? 'Collapse' : 'Expand';
}

// True while `container` holds the spot an expanded node would return to -
// i.e. its placeholder - even though the node itself currently lives in the
// overlay, not inside `container`. Callers about to rebuild a container's
// contents check this first, so they can collapse their own expanded node
// without touching an unrelated one that happens to be expanded elsewhere.
export function isExpandedWithin(container) {
  return Boolean(open && container.contains(open.placeholder));
}

// Collapses whatever is currently expanded, if anything. `immediate` skips
// the animation and moves the node back synchronously - use it right before
// the node (or its container) is about to be torn down and rebuilt, so it
// never ends up orphaned inside the overlay.
export function collapseExpand({ immediate = false } = {}) {
  if (!open) return;
  const { node, placeholder, button } = open;
  overlay.classList.remove('open');
  setButtonState(button, false);
  document.body.classList.remove('expand-lock');
  open = null;
  const finish = () => {
    node.classList.remove('expand-open');
    placeholder.replaceWith(node);
  };
  if (immediate) finish();
  else setTimeout(finish, 220);
}

function expandNode(node, button) {
  ensureOverlay();
  if (open) collapseExpand({ immediate: true });
  const placeholder = document.createComment('expand-placeholder');
  node.before(placeholder);
  node.classList.add('expand-open');
  overlay.append(node);
  document.body.classList.add('expand-lock');
  open = { node, placeholder, button };
  setButtonState(button, true);
  // Two rAFs: the first lets the append and class change land in the DOM,
  // the second starts the transition on the frame after that - a single one
  // can still land in the same frame as the append and skip straight to the
  // end state instead of animating into it.
  requestAnimationFrame(() => requestAnimationFrame(() => overlay.classList.add('open')));
}

// Adds an Expand/Collapse toggle button to `node`, which becomes the thing
// that fills the screen when it's pressed. Call it again each time `node`
// itself is recreated (e.g. after loading a new file into the crop stage) -
// there's nothing to clean up on the old instance since the whole node it
// belonged to is gone.
export function attachExpand(node) {
  node.classList.add('expand-host');
  const button = el('button', { type: 'button', class: 'expand-btn' });
  setButtonState(button, false);
  button.addEventListener('click', (e) => {
    e.stopPropagation();
    if (open && open.node === node) collapseExpand();
    else expandNode(node, button);
  });
  node.append(button);
  return button;
}
