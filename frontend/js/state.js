// The file currently being worked on. Tools read from here instead of asking
// for a new upload each time, which is what makes chained editing possible.

const listeners = new Set();

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
  listeners.forEach(fn => fn(state));
}

export function clearCurrent() {
  Object.assign(state, { job: null, name: null, url: null, meta: null, sizeBytes: 0, freshSide: null });
  listeners.forEach(fn => fn(state));
}

export function hasFile() {
  return Boolean(state.job && state.url);
}
