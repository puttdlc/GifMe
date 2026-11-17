// The file currently being worked on. Tools read from here instead of asking
// for a new upload each time, which is what makes chained editing possible.

const listeners = new Set();

// Just enough to find the working file again after a page refresh - the
// backend still has everything else. Best-effort: storage can be blocked
// (private windows, strict site settings), and the app works without it.
const SESSION_KEY = 'gifme.session';

function remember(job, name) {
  try {
    if (job) localStorage.setItem(SESSION_KEY, JSON.stringify({ job, name }));
    else localStorage.removeItem(SESSION_KEY);
  } catch { /* storage unavailable */ }
}

export function rememberedSession() {
  try { return JSON.parse(localStorage.getItem(SESSION_KEY) || 'null'); } catch { return null; }
}

export const state = {
  job: null,
  name: null,
  url: null,
  meta: null,
  sizeBytes: 0,
  // Which of the input (workspace bar) / output (result panel) thumbnails
  // most recently became the "freshest" file, for the green highlight that
  // tracks where the newest result lives - null until anything has happened.
  freshSide: null,
};

export function subscribe(fn) {
  listeners.add(fn);
  fn(state);
  return () => listeners.delete(fn);
}

// The input and output highlight are mutually exclusive - whichever side
// just produced/adopted a file is "freshest", and the other reverts.
export function markFresh(side) {
  state.freshSide = side;
  listeners.forEach(fn => fn(state));
}

export function setCurrent({ job, name, url, meta, size_bytes }) {
  state.job = job ?? state.job;
  state.name = name ?? state.name;
  state.url = url ?? state.url;
  state.meta = meta ?? state.meta;
  state.sizeBytes = size_bytes ?? state.sizeBytes;
  state.freshSide = 'input';
  remember(state.job, state.name);
  listeners.forEach(fn => fn(state));
}

export function clearCurrent() {
  Object.assign(state, { job: null, name: null, url: null, meta: null, sizeBytes: 0, freshSide: null });
  remember(null);
  listeners.forEach(fn => fn(state));
}

export function hasFile() {
  return Boolean(state.job && state.url);
}
