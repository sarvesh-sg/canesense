// Downsamples the microphone to 16 kHz 16-bit PCM in 100 ms frames for the Gemini Live API.
class Pcm16k extends AudioWorkletProcessor {
  constructor(o) { super(); this.inRate = o.processorOptions.inRate; this.ratio = this.inRate / 16000; this.acc = []; this.pos = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]; if (!ch) return true;
    for (let i = 0; i < ch.length; i++) { this.pos += 1; if (this.pos >= this.ratio) { this.pos -= this.ratio; this.acc.push(Math.max(-1, Math.min(1, ch[i]))); } }
    if (this.acc.length >= 1600) {
      const out = new Int16Array(this.acc.length); for (let i = 0; i < out.length; i++) out[i] = this.acc[i] * 32767;
      this.port.postMessage(out.buffer, [out.buffer]); this.acc = [];
    }
    return true;
  }
}
registerProcessor('pcm16-16k', Pcm16k);
