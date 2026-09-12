// Downloads a result through fetch's streaming body instead of a plain
// <a download> link, so the global progress bar can show real percentage
// for a big GIF/video export rather than the browser silently doing it.

import { progressBusy, progressEnd, progressSet, progressStart } from './progress.js';
import { toast } from './ui.js';

export async function downloadWithProgress(url, filename) {
  progressStart('Downloading…');
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Download failed (${res.status})`);
    const total = Number(res.headers.get('Content-Length')) || 0;
    const reader = res.body?.getReader?.();

    let blob;
    if (!reader) {
      blob = await res.blob();
    } else {
      const chunks = [];
      let loaded = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        loaded += value.length;
        if (total) progressSet(loaded / total, `Downloading… ${Math.round((loaded / total) * 100)}%`);
        else progressBusy('Downloading…');
      }
      blob = new Blob(chunks);
    }

    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 4000);
  } catch (e) {
    toast(e.message || String(e), 'error');
  } finally {
    progressEnd();
  }
}
