import { AudioEngine } from './audio-engine.js';
import { Visualizer, PALETTES } from './visualizer.js';

const $ = (id) => document.getElementById(id);

const stage = $('stage');
const canvas = $('scene');
const ui = $('ui');
const toast = $('toast');
const dropHint = $('drop-hint');
const fileInput = $('file-input');
const sourceLabel = $('source-label');
const fpsLabel = $('fps');
const meter = $('meter');
const meterCtx = meter.getContext('2d');

const audio = new AudioEngine();
const visualizer = new Visualizer(canvas, stage);

let toastTimer = 0;

function notify(message, isError = false) {
  toast.textContent = message;
  toast.classList.add('show');
  toast.style.borderColor = isError ? 'rgba(255,106,60,0.45)' : 'rgba(69,200,255,0.4)';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), isError ? 5200 : 2600);
}

// --------------------------------------------------------------- source list

const SOURCE_ACTIONS = {
  mic: () => audio.useMicrophone(),
  system: () => audio.useSystemAudio(),
  file: () => fileInput.click(),
  demo: () => audio.useDemo(),
  none: () => audio.stop(),
};

const FAILURE_HINTS = {
  mic: 'Não foi possível abrir o microfone. Verifique as permissões de privacidade do Windows.',
  system: 'Não foi possível capturar o áudio do sistema. O loopback exige Windows e uma tela compartilhável.',
  file: 'Não foi possível decodificar esse arquivo de áudio.',
};

async function selectSource(kind) {
  try {
    await SOURCE_ACTIONS[kind]();
  } catch (error) {
    notify(FAILURE_HINTS[kind] ?? String(error?.message ?? error), true);
    // Keep something on screen rather than freezing on a dead source.
    if (kind !== 'none') audio.useDemo();
  }
}

for (const button of document.querySelectorAll('button.src')) {
  button.addEventListener('click', () => selectSource(button.dataset.source));
}

const SOURCE_LABELS = {
  mic: 'Microfone',
  system: 'Áudio do sistema',
  file: 'Arquivo',
  demo: 'Padrão demo',
  none: 'Nenhuma fonte',
};

audio.onSourceChange = (kind, detail) => {
  sourceLabel.textContent = detail || SOURCE_LABELS[kind] || kind;
  for (const button of document.querySelectorAll('button.src')) {
    button.classList.toggle('active', button.dataset.source === kind);
  }
};

// -------------------------------------------------------------------- inputs

fileInput.addEventListener('change', async () => {
  const file = fileInput.files?.[0];
  if (!file) return;
  try {
    await audio.useFile(file);
    notify(`Reproduzindo ${file.name}`);
  } catch {
    notify(FAILURE_HINTS.file, true);
  }
  fileInput.value = '';
});

const bindSlider = (id, apply) => {
  const input = $(id);
  const push = () => apply(parseFloat(input.value));
  input.addEventListener('input', push);
  push();
};

bindSlider('sensitivity', (v) => (audio.sensitivity = v));
bindSlider('turbulence', (v) => (visualizer.settings.turbulence = v));
bindSlider('detail', (v) => (visualizer.settings.detail = v));
bindSlider('speed', (v) => (visualizer.settings.speed = v));
bindSlider('glow', (v) => (visualizer.settings.glow = v));
bindSlider('bloom', (v) => (visualizer.settings.bloom = v));

const paletteSelect = $('palette');
for (const [key, palette] of Object.entries(PALETTES)) {
  const option = document.createElement('option');
  option.value = key;
  option.textContent = palette.label;
  paletteSelect.append(option);
}
paletteSelect.value = 'ember';
paletteSelect.addEventListener('change', () => visualizer.applyPalette(paletteSelect.value));

// ------------------------------------------------------------ drag and drop

let dragDepth = 0;

window.addEventListener('dragenter', (event) => {
  event.preventDefault();
  dragDepth++;
  dropHint.classList.add('show');
});

window.addEventListener('dragover', (event) => event.preventDefault());

window.addEventListener('dragleave', (event) => {
  event.preventDefault();
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) dropHint.classList.remove('show');
});

window.addEventListener('drop', async (event) => {
  event.preventDefault();
  dragDepth = 0;
  dropHint.classList.remove('show');

  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  if (!file.type.startsWith('audio/')) {
    notify('Solte um arquivo de áudio.', true);
    return;
  }
  try {
    await audio.useFile(file);
    notify(`Reproduzindo ${file.name}`);
  } catch {
    notify(FAILURE_HINTS.file, true);
  }
});

// ----------------------------------------------------------------- shortcuts

async function saveFrame() {
  const blob = await visualizer.capture();
  if (!blob) {
    notify('Não foi possível capturar o quadro.', true);
    return;
  }

  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  try {
    const bytes = await blob.arrayBuffer();
    const savedTo = await window.orbHost.saveCapture(bytes, `sonic-orb-${stamp}.png`);
    notify(`Captura salva em ${savedTo}`);
  } catch (error) {
    notify(`Falha ao salvar a captura: ${error?.message ?? error}`, true);
  }
}

window.addEventListener('keydown', (event) => {
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) {
    if (event.key !== 'Escape') return;
  }

  switch (event.key.toLowerCase()) {
    case '1': selectSource('mic'); break;
    case '2': selectSource('system'); break;
    case '3': selectSource('file'); break;
    case '4': selectSource('demo'); break;
    case '0': selectSource('none'); break;
    case 'h': ui.classList.toggle('hidden'); break;
    case 'f': window.orbHost?.toggleFullscreen(); break;
    case 's': saveFrame(); break;
    case 'r':
      visualizer.resetCamera();
      break;
    case ' ':
      event.preventDefault();
      if (audio.source === 'file') {
        notify(audio.toggleFilePlayback() ? 'Reproduzindo' : 'Pausado');
      }
      break;
    default:
      break;
  }
});

// -------------------------------------------------------------------- meter

const METER_BARS = 72;

function drawMeter(frame) {
  const { width, height } = meter;
  meterCtx.clearRect(0, 0, width, height);

  const step = width / METER_BARS;
  const barWidth = Math.max(1, step - 1.6);
  const stride = frame.spectrum.length / METER_BARS;

  for (let i = 0; i < METER_BARS; i++) {
    // Average the slice so a bar never lands between two active bins.
    let sum = 0;
    const from = Math.floor(i * stride);
    const to = Math.floor((i + 1) * stride);
    for (let b = from; b < to; b++) sum += frame.spectrum[b];
    const value = sum / Math.max(1, to - from) / 255;

    const barHeight = Math.max(1.5, Math.pow(value, 0.8) * (height - 6));
    const t = i / METER_BARS;
    const gradient = meterCtx.createLinearGradient(0, height, 0, height - barHeight);
    gradient.addColorStop(0, `rgba(70,180,255,${0.35 + value * 0.45})`);
    gradient.addColorStop(1, `rgba(${255 - t * 40}, ${110 + t * 40}, ${60 + t * 60}, ${0.5 + value * 0.5})`);

    meterCtx.fillStyle = gradient;
    meterCtx.fillRect(i * step + 0.8, height - barHeight - 3, barWidth, barHeight);
  }

  // Beat flash across the baseline.
  if (frame.beat > 0.02) {
    meterCtx.fillStyle = `rgba(255,190,150,${frame.beat * 0.55})`;
    meterCtx.fillRect(0, height - 2.5, width, 2.5);
  }
}

let meterTick = 0;

visualizer.onFrame = (frame) => {
  drawMeter(frame);
  if (++meterTick % 15 === 0) fpsLabel.textContent = `${visualizer.fps} fps`;
};

// ---------------------------------------------------------------- bootstrap

// Match the meter bitmap to its CSS box so the bars stay crisp.
function sizeMeter() {
  const dpr = Math.min(window.devicePixelRatio, 2);
  const rect = meter.getBoundingClientRect();
  if (rect.width === 0) return;
  meter.width = Math.round(rect.width * dpr);
  meter.height = Math.round(46 * dpr);
}

window.addEventListener('resize', sizeMeter);
sizeMeter();

visualizer.start(audio);
audio.useDemo();
notify('Escolha uma fonte de áudio para reagir ao som');
