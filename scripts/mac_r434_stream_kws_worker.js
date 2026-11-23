#!/usr/bin/env node
'use strict';
// R434: sandboxed binary streaming KWS worker; no microphone, network, DSH or file writes.
// Request: 8-byte big endian header (seq:u32, n:u32), followed by PCM16LE 16k mono;
// Response: one newline JSON {seq,hit}; never emits raw audio or transcripts.
const fs=require('node:fs'),path=require('node:path');
const ROOT=process.env.DAFEIYU_KWS_MODEL_DIR||path.join(process.cwd(),'app/runtime/models/wenetspeech-3.3m');
const SHERPA=process.env.DAFEIYU_SHERPA_MODULE||'sherpa-onnx-node';
const probe=require('./mac_sherpa_kws_probe.js');
const model=ROOT;
const keywords=path.join(model,'keywords-nihaodafeiyu.txt');
const required=['encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx',
 'decoder-epoch-12-avg-2-chunk-16-left-64.onnx',
 'joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx','tokens.txt'];
const MAX_PACKETS=10000;
let count=0,expected=0,buffer=Buffer.alloc(0),disposed=false;
function error(e){
 if(disposed)return;
 disposed=true;
 process.stderr.write('R434_KWS_WORKER_FAILED '+(e&&e.message?e.message:String(e))+'\n');
 process.exitCode=2;
 process.stdin.pause();
}
try{
 probe.validateFiles(model,keywords);
 const {KeywordSpotter}=require(SHERPA);
 const spotter=new KeywordSpotter({
  featConfig:{sampleRate:16000,featureDim:80},
  modelConfig:{transducer:{
    encoder:path.join(model,required[0]),decoder:path.join(model,required[1]),
    joiner:path.join(model,required[2])},
   tokens:path.join(model,required[3]),numThreads:1,provider:'cpu',debug:false},
  // R533: gentle 0.18->0.17 sensitivity adjustment for real missed hits.
  // Eight synthetic positive/near-sounding negative samples retained the
  // same 4 hit / 4 no-hit results at 0.18, 0.17 and 0.16.
  // Human false-wake/miss rate still needs field acceptance.
  // Keep one-use authenticated wake tickets and postwake ASR/VAD gates.
  keywordsFile:keywords,keywordsScore:1.0,keywordsThreshold:0.17,
  maxActivePaths:4,numTrailingBlanks:1
 });
 const stream=spotter.createStream();
 process.stdout.write(JSON.stringify({type:'ready',protocol:'r434-kws-worker-v1'})+'\n');
 process.stdin.on('data',chunk=>{
  if(disposed)return;
  try{
   buffer=Buffer.concat([buffer,chunk]);
   if(buffer.length>65536)throw Error('oversized_buffer');
   while(buffer.length>=8){
    const seq=buffer.readUInt32BE(0),n=buffer.readUInt32BE(4);
    if(n!==1920||seq!==expected||count>=MAX_PACKETS)throw Error('invalid_frame_or_replay');
    if(buffer.length<8+n)break;
    const payload=buffer.subarray(8,8+n),data=new Float32Array(960);
    for(let i=0;i<960;i++)data[i]=payload.readInt16LE(i*2)/32768;
    stream.acceptWaveform({sampleRate:16000,samples:data});
    let hit=false,guard=0;
    while(spotter.isReady(stream)){
      if(++guard>128)throw Error('unbounded_decode');
      spotter.decode(stream);
      const result=spotter.getResult(stream);
      if(result&&result.keyword==='你好大肥鱼'){
       hit=true;spotter.reset(stream);break;
      }
    }
    buffer=buffer.subarray(8+n);
    count++;expected++;
    process.stdout.write(JSON.stringify({seq,hit})+'\n');
    if(hit){disposed=true;process.stdin.pause();break;}
   }
  }catch(err){error(err);}
 });
 process.stdin.on('end',()=>{if(!disposed&&buffer.length)error(Error('truncated_frame'));});
}catch(e){error(e);}
