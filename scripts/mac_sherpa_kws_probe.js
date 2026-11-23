#!/usr/bin/env node
'use strict';
/**
 * Offline-only Sherpa WenetSpeech KWS probe. Does not open a microphone,
 * access the network, or send any wake event to DSH / ESP32.
 * Only paths provided by operator; emitted data is limited to keyword/time.
 */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const ROOT = process.env.DAFEIYU_HOME || process.cwd();
const KWS = path.join(ROOT, 'private-runtime/mac-kws-lab/wenetspeech-3.3m');
const SHERPA_DIR = process.env.DAFEIYU_SHERPA_MODULE || 'sherpa-onnx-node';
const REQUIRED = ['encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx',
  'decoder-epoch-12-avg-2-chunk-16-left-64.onnx',
  'joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx', 'tokens.txt'];
function readWave(filename) {
  const raw = fs.readFileSync(filename);
  if (raw.length < 44 || raw.toString('ascii', 0, 4) !== 'RIFF' ||
      raw.toString('ascii', 8, 12) !== 'WAVE') {
    throw new Error('Unsupported WAV RIFF header');
  }
  let fmt = null, data = null, offset = 12;
  while (offset + 8 <= raw.length) {
    const type = raw.toString('ascii', offset, offset + 4);
    const size = raw.readUInt32LE(offset + 4), start = offset + 8;
    if (start + size > raw.length) throw new Error('Invalid WAV chunk size');
    if (type === 'fmt ') {
      if (size < 16) throw new Error('Invalid WAV format');
      fmt = { format: raw.readUInt16LE(start), channels: raw.readUInt16LE(start + 2),
        sampleRate: raw.readUInt32LE(start + 4), bits: raw.readUInt16LE(start + 14) };
    }
    if (type === 'data') data = raw.subarray(start, start + size);
    offset = start + size + (size & 1);
  }
  if (!fmt || !data || fmt.format !== 1 || fmt.channels !== 1 ||
      fmt.sampleRate !== 16000 || fmt.bits !== 16 || data.length % 2) {
    throw new Error('Probe supports only 16kHz PCM16 mono WAV');
  }
  const samples = new Float32Array(data.length / 2);
  for (let i = 0; i < samples.length; ++i) samples[i] = data.readInt16LE(i * 2) / 32768;
  return {sampleRate: 16000, samples};
}
function hashFile(p) {
  const h = crypto.createHash('sha256');
  h.update(fs.readFileSync(p));
  return h.digest('hex');
}
function validateFiles(modelDir, keywords) {
  const manifestPath = path.join(modelDir,'source-manifest.json');
  const manifest = JSON.parse(fs.readFileSync(manifestPath,'utf8'));
  for (const filename of REQUIRED) {
    const p = path.join(modelDir,filename);
    if (!fs.existsSync(p)) throw new Error('Missing model artifact '+filename);
    if (manifest.files_sha256[filename] !== hashFile(p)) {
      throw new Error('Model checksum mismatch '+filename);
    }
  }
  const rawKeywords = fs.readFileSync(keywords,'utf8').trim();
  if (!rawKeywords || !rawKeywords.includes('@')) {
    throw new Error('Invalid or empty KWS keywords file');
  }
}
function run({wav, keywordsFile, modelDir=KWS, threshold=0.25}) {
  validateFiles(modelDir,keywordsFile);
  const sherpa = require(SHERPA_DIR);
  if (typeof sherpa.KeywordSpotter !== 'function') {
    throw new Error('Native Sherpa KeywordSpotter is unavailable');
  }
  const modelConfig = {
    transducer: {
      encoder: path.join(modelDir,REQUIRED[0]),
      decoder: path.join(modelDir,REQUIRED[1]),
      joiner: path.join(modelDir,REQUIRED[2])
    },
    tokens: path.join(modelDir,REQUIRED[3]),
    numThreads: 1, provider: 'cpu', debug: false
  };
  const spotter = new sherpa.KeywordSpotter({
    featConfig: {sampleRate:16000, featureDim:80},
    modelConfig,
    keywordsFile, keywordsScore: 1.0, keywordsThreshold: threshold,
    maxActivePaths: 4, numTrailingBlanks: 1
  });
  const stream = spotter.createStream();
  const {sampleRate,samples} = readWave(wav);
  const hits = [];
  let decodeCalls = 0;
  const decode = () => {
    while (spotter.isReady(stream)) {
      if (++decodeCalls > 50000) throw new Error('KWS decode loop guard');
      spotter.decode(stream);
      const result = spotter.getResult(stream);
      if (typeof result.keyword === 'string' && result.keyword) {
        hits.push({keyword:result.keyword,start_time:result.start_time ?? null});
        spotter.reset(stream);
      }
    }
  };
  for(let i=0;i<samples.length;i+=1600) {
    stream.acceptWaveform({samples:samples.subarray(i,Math.min(i+1600,samples.length)),
       sampleRate});
    decode();
  }
  // Provide a post-utterance silence tail as documented by Sherpa.
  stream.acceptWaveform({samples:new Float32Array(8000),sampleRate});
  stream.inputFinished();
  decode();
  return {mode:'offline-only',wav:path.basename(wav),duration_s:samples.length/sampleRate,
    keywordsFile:path.basename(keywordsFile),hits,decodeCalls,modelRuntime:'sherpa-onnx-node'};
}
function main(argv) {
  if (argv.includes('--readiness')) {
    const exists = [...REQUIRED,'source-manifest.json'].every(f=>fs.existsSync(path.join(KWS,f)));
    console.log(JSON.stringify({modelReady:exists,node:process.version,
      sherpa:require(path.join(SHERPA_DIR,'package.json')).version,activeVoiceUntouched:true}));
    return;
  }
  const wavPos=argv.indexOf('--wav');
  const kwPos=argv.indexOf('--keywords');
  if (wavPos < 0 || kwPos < 0 || !argv[wavPos+1] || !argv[kwPos+1]) {
    throw new Error('Usage: node scripts/mac_sherpa_kws_probe.js --wav /path/audio.wav --keywords /path/keywords.txt');
  }
  console.log(JSON.stringify(run({wav:argv[wavPos+1],keywordsFile:argv[kwPos+1]})));
}
if (require.main === module) {
  try {main(process.argv.slice(2));} catch (e) {
    console.error('KWS_OFFLINE_PROBE_FAIL',e.message);process.exitCode=2;
  }
}
module.exports = {readWave,run,validateFiles};
