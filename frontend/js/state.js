// The file currently being worked on. Tools read from here instead of asking
// for a new upload each time, which is what makes chained editing possible.

const listeners = new Set();

export const state = {
  job: null,
  name: null,
  url: null,
  meta: null,
  sizeBytes: 0,
};

export function subscribe(fn) {
  listeners.add(fn);
  fn(state);
  return () => listeners.delete(fn);
}

export function setCurrent({ job, name, url, meta, size_bytes }) {
  state.job = job ?? state.job;
  state.name = name ?? state.name;
  state.url = url ?? state.url;
  state.meta = meta ?? state.meta;
  state.sizeBytes = size_bytes ?? state.sizeBytes;
  listeners.forEach(fn => fn(state));
}

export function clearCurrent() {
  Object.assign(state, { job: null, name: null, url: null, meta: null, sizeBytes: 0 });
  listeners.forEach(fn => fn(state));
}

export function hasFile() {
  return Boolean(state.job && state.url);
}
