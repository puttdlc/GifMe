// --- tab switching ---
document.querySelectorAll('#tabs button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
  });
});

// --- health check ---
fetch('/api/health').then(r => r.json()).then(h => {
  const missing = Object.entries(h).filter(([, ok]) => !ok).map(([name]) => name);
  document.getElementById('health').textContent = missing.length
    ? `⚠ missing: ${missing.join(', ')}`
    : '✓ all tools available';
}).catch(() => {
  document.getElementById('health').textContent = '⚠ backend unreachable';
});

const resultBody = document.getElementById('result-body');

function showLoading() {
  resultBody.innerHTML = '<p class="hint">Processing…</p>';
}

function showError(msg) {
  resultBody.innerHTML = `<p class="error">${msg}</p>`;
}

async function showResult(blob, filename) {
  const url = URL.createObjectURL(blob);
  const isVideo = /\.(mp4|webm)$/i.test(filename);
  const isZip = /\.zip$/i.test(filename);
  let previewHtml = '';
  if (isVideo) {
    previewHtml = `<video src="${url}" controls autoplay loop></video>`;
  } else if (!isZip) {
    previewHtml = `<img src="${url}">`;
  }
  resultBody.innerHTML = `
    ${previewHtml}
    <div><a class="download" href="${url}" download="${filename}">⬇ Download ${filename}</a></div>
  `;
}

// generic: post a FormData payload to an endpoint, show the resulting file
async function postForResult(endpoint, formData, outNameHint = 'output') {
  showLoading();
  try {
    const res = await fetch(endpoint, { method: 'POST', body: formData });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `Request failed (${res.status})`);
    }
    const cd = res.headers.get('content-disposition') || '';
    const match = cd.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : outNameHint;
    const blob = await res.blob();
    await showResult(blob, filename);
  } catch (e) {
    showError(e.message);
  }
}

function fileOf(id) {
  const el = document.getElementById(id);
  if (!el.files.length) throw new Error('Please choose a file first.');
  return el.files[0];
}

const Actions = {
  async videoToGif() {
    const fd = new FormData();
    fd.append('file', fileOf('make-video-file'));
    fd.append('fps', document.getElementById('make-fps').value);
    fd.append('width', document.getElementById('make-width').value);
    fd.append('start', document.getElementById('make-start').value);
    fd.append('duration', document.getElementById('make-duration').value);
    await postForResult('/api/video-to-gif', fd, 'output.gif');
  },

  async imagesToGif() {
    const el = document.getElementById('make-images-files');
    if (!el.files.length) return showError('Please choose images first.');
    const fd = new FormData();
    Array.from(el.files).forEach(f => fd.append('files', f));
    fd.append('delay_ms', document.getElementById('make-delay').value);
    fd.append('width', document.getElementById('make-images-width').value || 0);
    await postForResult('/api/images-to-gif', fd, 'output.gif');
  },

  async convert() {
    const fd = new FormData();
    fd.append('file', fileOf('convert-file'));
    const target = document.getElementById('convert-target').value;
    fd.append('target', target);
    await postForResult('/api/convert', fd, `output.${target}`);
  },

  async resize() {
    const fd = new FormData();
    fd.append('file', fileOf('resize-file'));
    fd.append('width', document.getElementById('resize-width').value || 0);
    fd.append('height', document.getElementById('resize-height').value || 0);
    await postForResult('/api/resize', fd);
  },

  async crop() {
    const fd = new FormData();
    fd.append('file', fileOf('crop-file'));
    fd.append('x', document.getElementById('crop-x').value);
    fd.append('y', document.getElementById('crop-y').value);
    fd.append('w', document.getElementById('crop-w').value);
    fd.append('h', document.getElementById('crop-h').value);
    await postForResult('/api/crop', fd);
  },

  async rotate(degrees) {
    const fd = new FormData();
    fd.append('file', fileOf('rotate-file'));
    fd.append('degrees', degrees);
    await postForResult('/api/rotate', fd);
  },

  async flip(axis) {
    const fd = new FormData();
    fd.append('file', fileOf('rotate-file'));
    fd.append('axis', axis);
    await postForResult('/api/flip', fd);
  },

  async speed() {
    const fd = new FormData();
    fd.append('file', fileOf('speed-file'));
    fd.append('factor', document.getElementById('speed-factor').value);
    await postForResult('/api/speed', fd);
  },

  async reverse() {
    const fd = new FormData();
    fd.append('file', fileOf('reverse-file'));
    await postForResult('/api/reverse', fd);
  },

  async effect() {
    const fd = new FormData();
    fd.append('file', fileOf('effects-file'));
    fd.append('name', document.getElementById('effects-name').value);
    await postForResult('/api/effect', fd);
  },

  async text() {
    const fd = new FormData();
    fd.append('file', fileOf('text-file'));
    fd.append('text', document.getElementById('text-content').value);
    fd.append('position', document.getElementById('text-position').value);
    fd.append('font_size', document.getElementById('text-size').value);
    fd.append('color', document.getElementById('text-color').value);
    await postForResult('/api/text', fd);
  },

  async optimize() {
    const fd = new FormData();
    fd.append('file', fileOf('optimize-file'));
    fd.append('lossy', document.getElementById('optimize-lossy').value);
    fd.append('colors', document.getElementById('optimize-colors').value || 0);
    await postForResult('/api/optimize', fd, 'output.gif');
  },

  async split() {
    const fd = new FormData();
    fd.append('file', fileOf('split-file'));
    await postForResult('/api/split-frames', fd, 'frames.zip');
  },

  async analyze() {
    const fd = new FormData();
    fd.append('file', fileOf('analyze-file'));
    const out = document.getElementById('analyze-output');
    out.textContent = 'Analyzing…';
    try {
      const res = await fetch('/api/analyze', { method: 'POST', body: fd });
      if (!res.ok) throw new Error('Analysis failed');
      out.textContent = JSON.stringify(await res.json(), null, 2);
    } catch (e) {
      out.textContent = 'Error: ' + e.message;
    }
  },
};
