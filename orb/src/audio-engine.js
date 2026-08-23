const SPECTRUM_BINS = 256;

/** Frequency bands, in Hz. Overlapping edges keep the response continuous. */
const BANDS = {
  bass: [20, 160],
  mid: [160, 1800],
  treble: [1800, 11000],
};

/** Asymmetric smoothing: snap up fast, fall away slowly. */
class Envelope {
  constructor(attack = 0.35, release = 0.06) {
    this.attack = attack;
    this.release = release;
    this.value = 0;
  }

  push(target) {
    const k = target > this.value ? this.attack : this.release;
    this.value += (target - this.value) * k;
    return this.value;
  }
}

/**
 * Wraps a Web Audio graph and reduces each frame to a handful of numbers the
 * shader can consume. Sources are hot-swappable; the analyser survives swaps.
 */
export class AudioEngine {
  constructor() {
    this.context = null;
    this.analyser = null;
    this.inputGain = null;

    this.source = 'none';
    this.sourceNode = null;
    this.stream = null;
    this.fileBuffer = null;
    this.fileName = '';
    this.filePlaying = false;
    this.fileOffset = 0;
    this.fileStartedAt = 0;

    this.gain = 1.4;
    this.sensitivity = 1;

    this.freqData = null;
    this.timeData = null;
    this.spectrum = new Uint8Array(SPECTRUM_BINS);

    this.envLevel = new Envelope(0.30, 0.05);
    this.envBass = new Envelope(0.45, 0.07);
    this.envMid = new Envelope(0.35, 0.06);
    this.envTreble = new Envelope(0.50, 0.09);

    this.peak = 0.25;
    this.bassHistory = new Float32Array(48);
    this.bassCursor = 0;
    this.beat = 0;
    this.lastBeatAt = 0;
    this.clock = 0;

    this.onSourceChange = null;
    this.onError = null;
  }

  // ------------------------------------------------------------------- setup

  _ensureContext() {
    if (this.context) return this.context;

    const context = new AudioContext({ latencyHint: 'interactive' });
    const analyser = context.createAnalyser();
    analyser.fftSize = 4096;
    analyser.smoothingTimeConstant = 0.72;
    analyser.minDecibels = -95;
    analyser.maxDecibels = -12;

    const inputGain = context.createGain();
    inputGain.gain.value = this.gain;
    inputGain.connect(analyser);

    this.context = context;
    this.analyser = analyser;
    this.inputGain = inputGain;
    this.freqData = new Uint8Array(analyser.frequencyBinCount);
    this.timeData = new Uint8Array(analyser.fftSize);

    this._buildBinMap();
    return context;
  }

  /** Precompute log-spaced FFT bin ranges so the display bars look musical. */
  _buildBinMap() {
    const nyquist = this.context.sampleRate / 2;
    const binCount = this.analyser.frequencyBinCount;
    const minHz = 28;
    const maxHz = Math.min(16000, nyquist);

    this.binMap = new Array(SPECTRUM_BINS);
    for (let i = 0; i < SPECTRUM_BINS; i++) {
      const f0 = minHz * Math.pow(maxHz / minHz, i / SPECTRUM_BINS);
      const f1 = minHz * Math.pow(maxHz / minHz, (i + 1) / SPECTRUM_BINS);
      const lo = Math.floor((f0 / nyquist) * binCount);
      const hi = Math.max(lo + 1, Math.ceil((f1 / nyquist) * binCount));
      this.binMap[i] = [Math.min(lo, binCount - 1), Math.min(hi, binCount)];
    }

    this.bandRanges = {};
    for (const [name, [lo, hi]] of Object.entries(BANDS)) {
      this.bandRanges[name] = [
        Math.floor((lo / nyquist) * binCount),
        Math.min(binCount, Math.ceil((hi / nyquist) * binCount)),
      ];
    }
  }

  async resume() {
    this._ensureContext();
    if (this.context.state === 'suspended') await this.context.resume();
  }

  // ----------------------------------------------------------------- sources

  async useMicrophone() {
    await this._disconnectSource();
    await this.resume();

    // Browser voice processing would fight the visualiser; turn it all off.
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: false,
    });

    this.stream = stream;
    this.sourceNode = this.context.createMediaStreamSource(stream);
    this.sourceNode.connect(this.inputGain);
    this._setSource('mic');
  }

  /**
   * Desktop loopback. Electron's main process answers the display-media request
   * with { audio: 'loopback' }; the video track it must include is discarded.
   */
  async useSystemAudio() {
    await this._disconnectSource();
    await this.resume();

    const stream = await navigator.mediaDevices.getDisplayMedia({ audio: true, video: true });
    for (const track of stream.getVideoTracks()) track.stop();

    if (stream.getAudioTracks().length === 0) {
      for (const track of stream.getTracks()) track.stop();
      throw new Error('No system audio track was returned.');
    }

    this.stream = stream;
    this.sourceNode = this.context.createMediaStreamSource(stream);
    this.sourceNode.connect(this.inputGain);
    // Loopback is already audible on the speakers; routing it back would echo.
    this._setSource('system');
  }

  async useFile(file) {
    await this.resume();
    const bytes = await file.arrayBuffer();
    const buffer = await this.context.decodeAudioData(bytes);

    await this._disconnectSource();
    this.fileBuffer = buffer;
    this.fileName = file.name;
    this.fileOffset = 0;
    this._startFile(0);
    this._setSource('file', file.name);
  }

  _startFile(offset) {
    const node = this.context.createBufferSource();
    node.buffer = this.fileBuffer;
    node.loop = true;
    node.connect(this.inputGain);
    // Unlike the capture sources, a decoded file must be routed to the speakers.
    this.inputGain.connect(this.context.destination);

    this.fileOffset = offset % this.fileBuffer.duration;
    this.fileStartedAt = this.context.currentTime;
    node.start(0, this.fileOffset);

    this.sourceNode = node;
    this.filePlaying = true;
  }

  /** @returns {boolean} true if playback is now running */
  toggleFilePlayback() {
    if (this.source !== 'file' || !this.fileBuffer) return false;

    if (this.filePlaying) {
      // Bank the playhead so resuming continues instead of restarting.
      this.fileOffset += this.context.currentTime - this.fileStartedAt;
      this.sourceNode.stop();
      this.sourceNode.disconnect();
      this.sourceNode = null;
      this.filePlaying = false;
    } else {
      this._startFile(this.fileOffset);
    }
    return this.filePlaying;
  }

  useDemo() {
    this._disconnectSource();
    this._ensureContext();
    this._setSource('demo');
  }

  async _disconnectSource() {
    if (this.sourceNode) {
      try {
        if (typeof this.sourceNode.stop === 'function') this.sourceNode.stop();
      } catch {
        /* buffer source already ended */
      }
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    if (this.stream) {
      for (const track of this.stream.getTracks()) track.stop();
      this.stream = null;
    }
    if (this.inputGain && this.context) {
      this.inputGain.disconnect();
      this.inputGain.connect(this.analyser);
    }
    this.filePlaying = false;
  }

  async stop() {
    await this._disconnectSource();
    this.fileBuffer = null;
    this._setSource('none');
  }

  /** @param {string} detail optional specifics, e.g. the track filename */
  _setSource(kind, detail = '') {
    this.source = kind;
    this.onSourceChange?.(kind, detail);
  }

  setGain(value) {
    this.gain = value;
    if (this.inputGain) this.inputGain.gain.value = value;
  }

  // ------------------------------------------------------------------ analyse

  /** Average magnitude across an FFT bin range, normalised to 0..1. */
  _bandEnergy(range) {
    const [lo, hi] = range;
    let sum = 0;
    for (let i = lo; i < hi; i++) sum += this.freqData[i];
    return hi > lo ? sum / (hi - lo) / 255 : 0;
  }

  _detectBeat(bass, dt) {
    this.bassHistory[this.bassCursor] = bass;
    this.bassCursor = (this.bassCursor + 1) % this.bassHistory.length;

    let mean = 0;
    for (let i = 0; i < this.bassHistory.length; i++) mean += this.bassHistory[i];
    mean /= this.bassHistory.length;

    const quiet = 0.16;
    const canFire = this.clock - this.lastBeatAt > 0.14;
    if (canFire && bass > quiet && bass > mean * 1.32) {
      this.lastBeatAt = this.clock;
      this.beat = 1;
    }

    this.beat = Math.max(0, this.beat - dt * 3.4);
    return this.beat;
  }

  /** Stand-in spectrum so the orb keeps breathing with no input connected. */
  _synthesize(dt) {
    const t = this.clock;
    const pulse = Math.pow(Math.max(0, Math.sin(t * 2.2)), 6);

    for (let i = 0; i < SPECTRUM_BINS; i++) {
      const u = i / SPECTRUM_BINS;
      const wave =
        Math.sin(u * 9 + t * 1.3) * 0.5 +
        Math.sin(u * 23 - t * 2.1) * 0.28 +
        Math.sin(u * 47 + t * 3.7) * 0.15;
      const tilt = Math.pow(1 - u, 1.6);
      this.spectrum[i] = Math.max(0, Math.min(1, (wave * 0.5 + 0.5) * tilt * (0.55 + pulse * 0.6))) * 255;
    }

    const bass = 0.22 + pulse * 0.55;
    const mid = 0.18 + Math.abs(Math.sin(t * 0.7)) * 0.3;
    const treble = 0.12 + Math.abs(Math.sin(t * 1.9)) * 0.25;

    if (this.clock - this.lastBeatAt > 0.4 && pulse > 0.75) {
      this.lastBeatAt = this.clock;
      this.beat = 1;
    }
    this.beat = Math.max(0, this.beat - dt * 3.4);

    return {
      level: this.envLevel.push((bass + mid + treble) / 2.4),
      bass: this.envBass.push(bass),
      mid: this.envMid.push(mid),
      treble: this.envTreble.push(treble),
      beat: this.beat,
      spectrum: this.spectrum,
      silent: false,
    };
  }

  /** Called once per frame. Always returns a usable frame. */
  read(dt) {
    this.clock += dt;

    if (!this.analyser || this.source === 'none') {
      // Nothing connected: decay everything to a calm resting state.
      this.spectrum.fill(0);
      return {
        level: this.envLevel.push(0.06),
        bass: this.envBass.push(0.05),
        mid: this.envMid.push(0.04),
        treble: this.envTreble.push(0.03),
        beat: 0,
        spectrum: this.spectrum,
        silent: true,
      };
    }

    if (this.source === 'demo') return this._synthesize(dt);

    this.analyser.getByteFrequencyData(this.freqData);
    this.analyser.getByteTimeDomainData(this.timeData);

    let bass = this._bandEnergy(this.bandRanges.bass);
    let mid = this._bandEnergy(this.bandRanges.mid);
    let treble = this._bandEnergy(this.bandRanges.treble);

    // RMS from the time domain tracks perceived loudness better than the FFT mean.
    let sumSquares = 0;
    for (let i = 0; i < this.timeData.length; i++) {
      const v = (this.timeData[i] - 128) / 128;
      sumSquares += v * v;
    }
    const rms = Math.sqrt(sumSquares / this.timeData.length);

    // Slowly-decaying peak keeps quiet material expressive without clipping loud material.
    this.peak = Math.max(rms, this.peak - dt * 0.08);
    const norm = this.sensitivity / Math.max(this.peak, 0.045);
    const level = Math.min(1.6, rms * norm * 0.55);

    bass = Math.min(1.5, bass * this.sensitivity * 1.15);
    mid = Math.min(1.5, mid * this.sensitivity * 1.35);
    treble = Math.min(1.5, treble * this.sensitivity * 1.7);

    // Log-spaced resample for the shader lookup.
    for (let i = 0; i < SPECTRUM_BINS; i++) {
      const [lo, hi] = this.binMap[i];
      let sum = 0;
      for (let b = lo; b < hi; b++) sum += this.freqData[b];
      const avg = sum / (hi - lo);
      this.spectrum[i] = Math.min(255, avg * this.sensitivity);
    }

    return {
      level: this.envLevel.push(level),
      bass: this.envBass.push(bass),
      mid: this.envMid.push(mid),
      treble: this.envTreble.push(treble),
      beat: this._detectBeat(bass, dt),
      spectrum: this.spectrum,
      silent: rms < 0.002,
    };
  }
}
