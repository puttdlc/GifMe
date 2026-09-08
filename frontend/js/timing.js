// Delay time and frame rate are two views of one setting, so every delay field
// in the UI is paired with an FPS field that mirrors it: fill either one and
// the other follows.

export const MS_PER_CS = 10;   // ezgif states delays in 1/100 s

// `unitMs` is how many milliseconds one unit of the delay field stands for -
// 1 for a field in ms, MS_PER_CS for one in centiseconds.
export const fpsFromDelay = (delay, unitMs = 1) => 1000 / (delay * unitMs);
export const delayFromFps = (fps, unitMs = 1) => 1000 / fps / unitMs;

// Numbers land in the fields as plain as possible: no trailing ".00" on an FPS
// that came out whole, and no decimals at all on a delay field.
function show(n, decimals) {
  if (!Number.isFinite(n) || n <= 0) return '';
  return String(Number(n.toFixed(decimals)));
}

/**
 * Keep a delay input and an FPS input in step.
 * Returns { delayMs, setDelayMs } for reading and driving the pair.
 */
export function linkDelayFps(delayInput, fpsInput, { unitMs = 1, onChange } = {}) {
  const read = input => {
    const raw = input.value.trim();
    if (raw === '') return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  };

  // A blank or nonsense entry blanks its partner rather than leaving a stale
  // number behind that a form would go on submitting.
  const mirror = (from, to, convert, decimals) => {
    const n = read(from);
    to.value = n === null ? '' : show(convert(n), decimals);
    onChange?.(delayMs());
  };

  const delayMs = () => {
    const d = read(delayInput);
    if (d !== null) return d * unitMs;
    const f = read(fpsInput);
    return f !== null ? 1000 / f : 0;
  };

  const setDelayMs = (ms) => {
    delayInput.value = show(ms / unitMs, 0);
    fpsInput.value = show(1000 / ms, 2);
  };

  delayInput.addEventListener('input', () =>
    mirror(delayInput, fpsInput, d => fpsFromDelay(d, unitMs), 2));
  fpsInput.addEventListener('input', () =>
    mirror(fpsInput, delayInput, f => delayFromFps(f, unitMs), 0));

  return { delayMs, setDelayMs };
}
