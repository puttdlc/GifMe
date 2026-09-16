// A drop zone + "paste a link" affordance for a lone <input type=file>
// inside a tool form - the same upload UX the workspace uploader and GIF
// Maker already offer, wired onto secondary file fields (Overlay's
// watermark image, Video to GIF's source clip) that otherwise only had the
// browser's own file picker button. Also accepts a Ctrl+V paste of actual
// image/file data copied to the clipboard (not a link - a screenshot, or
// "Copy image" off a web page) while the pointer is over the zone; see
// pasteIntoHovered() below for how that's told apart from a paste destined
// for some other field entirely.

import { post } from './api.js';
import { el, toast, withBusy } from './ui.js';

// Makes `files` the input's real value, as if it had been picked through
// its own native dialog - every bit of code that reads input.files at
// submit time (see fileFrom/readFields in tools.js/api.js) keeps working
// unchanged.
function assign(input, files) {
  const dt = new DataTransfer();
  files.forEach(f => dt.items.add(f));
  input.files = dt.files;
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

// The actual files in a clipboard paste, if any - empty for a plain text
// paste, which is left completely alone (no preventDefault, nothing) so
// pasting into a normal text field never changes.
export function filesFromClipboard(e) {
  const items = e.clipboardData?.items;
  if (!items) return [];
  return Array.from(items)
    .filter(item => item.kind === 'file')
    .map(item => item.getAsFile())
    .filter(Boolean);
}

// Which field a stray Ctrl+V should land in isn't answerable from the
// paste event itself - unlike a drop, it carries no coordinates, only
// whatever last had keyboard focus, which for a page with no text field
// selected is just the page itself. Mouse hover stands in for that: at
// most one zone can be under the pointer at a time, tracked here as the
// input it belongs to (or null), and the app-wide paste listener in app.js
// checks this first, before falling back to its own default.
let hovered = null;

export function pasteIntoHovered(e) {
  if (!hovered) return false;
  const files = filesFromClipboard(e);
  if (!files.length) return false;
  e.preventDefault();
  assign(hovered, hovered.multiple ? files : [files[0]]);
  return true;
}

// Fetches a pasted URL through the same server-side fetcher the main
// uploader uses - that sidesteps CORS, since the *second* fetch (of the
// result) is same-origin, against GifMe's own file store, whatever the
// original URL's own CORS policy is.
async function fetchAsFile(url) {
  const r = await post('/api/upload-url', { url });
  const res = await fetch(r.url);
  const blob = await res.blob();
  return new File([blob], r.name, { type: blob.type });
}

// Wraps `input` (an existing <input type=file>, left in the DOM but
// hidden - everything else still reads/writes it exactly as before) with a
// dropzone and a "paste a link" row placed right where it was. `label`
// names what's being picked ("an image", "a video") for the zone's own
// text and the URL field's placeholder.
export function attachFileDrop(input, { label = 'a file', example = 'file' } = {}) {
  const zone = el('div', { class: 'dropzone small' },
    el('strong', {}, `+ Choose, drop or paste ${label}`),
    el('span', { class: 'hint' }, 'or paste a link below'));
  const name = el('span', { class: 'hint file-drop-name' });
  const urlInput = el('input', {
    type: 'url', placeholder: `https://example.com/${example}`, 'data-no-reset': '',
  });
  const urlBtn = el('button', { type: 'button', class: 'ghost' }, 'Load');
  const urlRow = el('div', { class: 'url-row' },
    el('span', { class: 'hint' }, 'Alternatively, paste a link'), urlInput, urlBtn);

  input.hidden = true;
  input.before(zone, urlRow, name);

  const sync = () => {
    name.textContent = input.files?.length
      ? `Selected: ${[...input.files].map(f => f.name).join(', ')}` : '';
  };

  zone.addEventListener('click', () => input.click());
  zone.addEventListener('mouseenter', () => { hovered = input; });
  zone.addEventListener('mouseleave', () => { if (hovered === input) hovered = null; });
  input.addEventListener('change', sync);

  ['dragover', 'dragenter'].forEach(ev => zone.addEventListener(ev, (e) => {
    e.preventDefault();
    zone.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach(ev => zone.addEventListener(ev, (e) => {
    e.preventDefault();
    zone.classList.remove('over');
  }));
  zone.addEventListener('drop', (e) => {
    const files = [...(e.dataTransfer?.files || [])];
    if (!files.length) return;
    assign(input, input.multiple ? files : [files[0]]);
  });

  const loadUrl = () => withBusy(urlBtn, async () => {
    const url = urlInput.value.trim();
    if (!url) return;
    const file = await fetchAsFile(url);
    assign(input, [file]);
    urlInput.value = '';
    toast(`${file.name} loaded`);
  });
  urlBtn.addEventListener('click', loadUrl);
  urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); loadUrl(); }
  });

  sync();
}
