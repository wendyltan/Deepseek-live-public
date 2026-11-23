"""R241: in-memory numeric PCM16 near-silence diagnostics; never store samples.

This is only an observable correlate of perceived speech pauses, not a
perceptual-quality classifier. Do not use it to rewrite, censor or gate TTS.
"""
from __future__ import annotations

class NearSilenceMeter:
    def __init__(self, *, sample_rate=24000, window_ms=20, peak_limit=160):
        if sample_rate != 24000 or window_ms != 20 or peak_limit <= 0:
            raise ValueError('meter_requires_verified_24k_pcm')
        self.samples_per_window=sample_rate*window_ms//1000
        self.peak_limit=peak_limit
        self.window_n=0
        self.window_peak=0
        self.quiet_frames=0
        self.max_quiet_frames=0
        self.internal_quiet_120ms=0
        self.has_loud=False
        self.total_windows=0
        self.loud_windows=0
        self._pending_internal=0

    def feed(self, pcm16):
        # pcm16: short-lived memoryview of the already validated source block.
        # Only peak and frame counts persist, never waveform or transcript.
        for sample in pcm16:
            magnitude=abs(int(sample))
            if magnitude>self.window_peak:self.window_peak=magnitude
            self.window_n+=1
            if self.window_n==self.samples_per_window:
                self.total_windows+=1
                quiet=self.window_peak<=self.peak_limit
                if quiet:
                    self.quiet_frames+=1
                else:
                    self.loud_windows+=1
                    if self.has_loud and self.quiet_frames>=6:
                        self.internal_quiet_120ms+=1
                    self.has_loud=True
                    self.quiet_frames=0
                if self.quiet_frames>self.max_quiet_frames:
                    self.max_quiet_frames=self.quiet_frames
                self.window_n=0
                self.window_peak=0

    def result(self):
        # Trailing silence isn't an interior gap, but belongs in max length.
        return {'near_silence_max_ms':self.max_quiet_frames*20,
                'internal_near_silence_ge_120ms':self.internal_quiet_120ms,
                'near_silence_window_percent':round(
                    100*(self.total_windows-self.loud_windows)/max(1,self.total_windows),1),
                'sampled_audio_ms':self.total_windows*20}
