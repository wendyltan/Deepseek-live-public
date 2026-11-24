#!/usr/bin/env python3
"""Scoped standalone Qwen3 TTS STREAMING audio lab. No DSH, external API, or LAN exposure."""
import base64, json, os, queue, threading, time, uuid, hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, unquote

# Explicit opt-in portability for fresh Macs; defaults preserve the
# currently accepted R503 model and reference audio on the author Mac.
PROJECT_ROOT=Path(__file__).resolve().parents[1]
TOOLS_ROOT=Path(os.environ.get("DAFEIYU_TOOLS_ROOT", str(PROJECT_ROOT.parent.parent / "Tools")))
_LEGACY_REF=Path.home()/"Library/Application Support/Deepseek-live/voice-r503-production/r644/reference.wav"
_BUNDLED_REF=PROJECT_ROOT/"release-assets/voice/r503-reference.wav"


def _pick_dir(env_key: str, primary: Path, *fallbacks: Path) -> Path:
    configured = os.environ.get(env_key, "").strip()
    if configured:
        return Path(configured).expanduser()
    for candidate in (primary, *fallbacks):
        if candidate.exists():
            return candidate
    return primary


_MODEL_NAME = "Qwen3-TTS-12Hz-0.6B-Base-8bit"
_TOOL_MODEL_CANDIDATES = [
    TOOLS_ROOT / "models" / _MODEL_NAME,
    *(sorted(TOOLS_ROOT.glob(f"*/models/{_MODEL_NAME}")) if TOOLS_ROOT.is_dir() else []),
]
ROOT=_pick_dir(
    "DAFEIYU_R503_LAB_ROOT",
    PROJECT_ROOT / "app/runtime/voice-agent-lab",
    TOOLS_ROOT / "voice-agent-lab",
)
MODEL=_pick_dir(
    "DAFEIYU_R503_MODEL_DIR",
    PROJECT_ROOT / "app/runtime/models" / _MODEL_NAME,
    *_TOOL_MODEL_CANDIDATES,
)
REFERENCE=Path(os.environ.get("DAFEIYU_R503_REFERENCE_AUDIO",
    str(_LEGACY_REF if _LEGACY_REF.is_file() else _BUNDLED_REF)))
# R644 release: exactly the R470 approved reference transcript; no import
# of experimental code that can execute GPU/model setup during startup.
REF_TEXT=os.environ.get("DAFEIYU_R503_REFERENCE_TEXT",
    '制冷剂经过节流装置以后，压力降低，再进入冰箱内部的蒸发器，吸收内部热量。')
# Same exact 8907 production wire contract (or 8906 baseline / 8908 smoke
# health candidate); never submit paid DSH or operate a phone.
PORT=int(os.environ.get("DAFEIYU_R503_PORT","8907"))
assert PORT in (8906,8907,8908)
EXPECTED_REFERENCE_SHA256=hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")

class Engine:
    def __init__(self):
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix="qwen3-stream")
        self.lock=threading.Lock()
        self.model=None
        self.ready=False
        self.error=None
        self.current=None
        self.executor.submit(self.bootstrap)

    def bootstrap(self):
        try:
            import mlx.core as mx
            from mlx_audio.tts.utils import load_model
            mx.set_memory_limit(7*1024**3)
            mx.set_cache_limit(512*1024**2)
            assert (MODEL/"model.safetensors").is_file()
            assert (MODEL/"speech_tokenizer/model.safetensors").is_file()
            assert REFERENCE.is_file()
            started=time.monotonic()
            self.model=load_model(str(MODEL))
            print("R505_MODEL_LOADED",round(time.monotonic()-started,2),flush=True)
            # Prewarm the SAME reference speaker and true streaming path.
            warm=self.model.generate(text="嗯，知道啦。",ref_audio=str(REFERENCE),ref_text=REF_TEXT,
               lang_code="chinese",stream=True,streaming_interval=0.64,
               streaming_context_size=25,max_tokens=100,temperature=.70)
            for part in warm: mx.eval(part.audio)
            self.ready=True
            print("R505_MODEL_WARMED",round(time.monotonic()-started,2),flush=True)
        except Exception as e:
            self.error=type(e).__name__
            print("R505_WARMUP_FAILED",self.error,flush=True)

    def schedule(self,text):
        with self.lock:
            if not self.ready or self.current is not None:return None
            job={"id":uuid.uuid4().hex, "text":text,"signal":threading.Event(),
                 "queue":queue.Queue(maxsize=16)}
            self.current=job
            self.executor.submit(self.generate,job)
            return job

    def stop(self,ident):
        with self.lock:
            job=self.current
            if not job or job["id"]!=ident:return False
            job["signal"].set()
            return True

    def generate(self,job):
        import mlx.core as mx
        import numpy as np
        started=time.monotonic()
        count=0;first=None;frames=0;rate=24000;cancelled=False
        try:
            # R323: repeatable local Qwen sampling per independent phrase.
            # Serial executor prevents concurrent RNG resets. The existing
            # D10 reference, text, model, stream shape and speed are unchanged.
            import random
            random.seed(20261017)
            np.random.seed(20261017)
            mx.random.seed(20261017)
            out=self.model.generate(
                text=job["text"],ref_audio=str(REFERENCE),ref_text=REF_TEXT,
                lang_code="chinese",stream=True,streaming_interval=0.64,
                streaming_context_size=25,max_tokens=700,temperature=.70,
                verbose=False)
            for result in out:
                if job["signal"].is_set():cancelled=True;break
                audio=result.audio;mx.eval(audio)
                samples=np.asarray(audio,dtype=np.float32).reshape(-1)
                if not samples.size:continue
                if not np.isfinite(samples).all():raise RuntimeError("invalid_pcm")
                rate=int(result.sample_rate)
                raw=(np.clip(samples,-1.0,1.0)*32767.0).astype("<i2").tobytes()
                now=time.monotonic()-started
                count+=1;frames+=len(samples)
                if first is None:first=now
                job["queue"].put({
                    "type":"audio","seq":count,"rate":rate,"frames":len(samples),
                    "elapsed_s":round(now,3),"pcm_b64":base64.b64encode(raw).decode("ascii")
                },timeout=10)
            if job["signal"].is_set():cancelled=True
            total=time.monotonic()-started
            job["queue"].put({
                "type":"end","cancelled":cancelled,
                "first_chunk_s":round(first,3) if first is not None else None,
                "generation_s":round(total,3),"audio_s":round(frames/rate,3),
                "rtf":round(total/(frames/rate),3) if frames else None,
                "chunks":count
            },timeout=5)
        except Exception as e:
            try:job["queue"].put({"type":"error","message":type(e).__name__},timeout=2)
            except queue.Full:pass
            import traceback
            traceback.print_exception(type(e),e,e.__traceback__,limit=4)
            print("R505_GENERATE_FAIL",type(e).__name__,flush=True)
        finally:
            with self.lock:
                if self.current is job:self.current=None

ENGINE=Engine()
ALLOWED_SAMPLES={
  "d10-casual-raw.wav","d10-casual-balanced.wav",
  "d10-continuity-raw.wav","d10-continuity-balanced.wav",
  "voxcpm8-casual.wav","voxcpm8-identity.wav",
  "qwen3-casual-stream.wav","qwen3-continuity-stream.wav",
}

class Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def allowed(self):
        host=self.headers.get("Host","").lower().split(":")[0]
        return self.client_address[0] in ("127.0.0.1","::1") and host in ("127.0.0.1","localhost")
    def json(self,code,body):
        data=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(code);self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if not self.allowed():return self.json(403,{"error":"localhost_only"})
        path=urlsplit(self.path).path
        if path=="/health":
            return self.json(200,{"ready":ENGINE.ready,"error":ENGINE.error,"busy":ENGINE.current is not None,
                                   "candidate":"R505-0p6b-long-only","stream_contract":"h11-ndjson",
                                   "reference_sha256":EXPECTED_REFERENCE_SHA256})
        if path=="/":
            file=ROOT/"index.html";mime="text/html; charset=utf-8"
        elif path.startswith("/sample/"):
            filename=unquote(path.removeprefix("/sample/"))
            if filename not in ALLOWED_SAMPLES:return self.json(404,{"error":"unknown_sample"})
            file=ROOT/"bench"/filename;mime="audio/wav"
        else:return self.json(404,{"error":"unknown"})
        if not file.is_file():return self.json(404,{"error":"missing_asset"})
        data=file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",mime);self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers();self.wfile.write(data)
    def do_POST(self):
        if not self.allowed():return self.json(403,{"error":"localhost_only"})
        # Same-origin browser only; localhost scripted CLI may omit Origin.
        origin=self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{PORT}",f"http://localhost:{PORT}"):
            return self.json(403,{"error":"origin"})
        size=self.headers.get("Content-Length","")
        if not size.isdigit() or not 0<int(size)<=4096:return self.json(413,{"error":"size"})
        try:
            data=json.loads(self.rfile.read(int(size)))
            assert type(data) is dict
        except Exception:return self.json(400,{"error":"json"})
        if self.path=="/cancel":
            ident=data.get("id")
            return self.json(200,{"cancel_requested":ENGINE.stop(ident) if isinstance(ident,str) else False})
        if self.path!="/stream":return self.json(404,{"error":"unknown"})
        text=data.get("text","")
        if not isinstance(text,str) or not 1<=len(text.strip())<=145:
            return self.json(400,{"error":"text_length_1_to_145"})
        if any(ord(c)<32 and c not in "\n\t" for c in text):
            return self.json(400,{"error":"invalid_control_char"})
        job=ENGINE.schedule(text.strip())
        if job is None:return self.json(503,{"error":"model_busy_or_warming"})
        self.send_response(200)
        self.send_header("Content-Type","application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Transfer-Encoding","chunked")
        self.end_headers()
        def send(item):
            line=(json.dumps(item,ensure_ascii=False,separators=(",",":"))+"\n").encode()
            self.wfile.write(f"{len(line):x}\r\n".encode()+line+b"\r\n")
            self.wfile.flush()
        try:
            send({"type":"start","id":job["id"],"rate":24000})
            while True:
                try:item=job["queue"].get(timeout=40)
                except queue.Empty:
                    send({"type":"error","message":"worker_timeout"});ENGINE.stop(job["id"]);break
                send(item)
                if item["type"] in ("end","error"):break
            self.wfile.write(b"0\r\n\r\n");self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError,OSError):
            ENGINE.stop(job["id"])
    def log_message(self,fmt,*args):
        if args and " /health " in str(args[0]):return
        super().log_message(fmt,*args)

if __name__=="__main__":
    assert not os.environ.get("DEEPSEEK_API_KEY"),"Do not run lab with model provider credentials"
    print("R505_LONG_TTS_CANDIDATE_LOCAL_ONLY profile=r503-0p6b port=%s"%PORT,flush=True)
    server=ThreadingHTTPServer(("127.0.0.1",PORT),Handler)
    try:server.serve_forever(poll_interval=.3)
    except KeyboardInterrupt:pass
    finally:server.server_close();ENGINE.executor.shutdown(wait=False,cancel_futures=True)
