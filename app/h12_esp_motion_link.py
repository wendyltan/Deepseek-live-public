"""Serial state+motion receipt verifier for an H12 ESP32 SD renderer.

A queued command or text-state ACK is *never* reported as a rendered motion.
This module does not touch audio or submit a DSH turn. Serial ownership is
exclusively delegated by the already-attached companion session.
"""
from __future__ import annotations
import re
import time
from app.h11_device_event_gate import DeviceStateBridge,DeviceEventError

SELECTED_IDS=frozenset((0,1,2,3,8,10,11,13,14,15,16,18,19,20,23,24,25,
                       26,27,28,30,61,62,67,70,71,72,73,75,80,81,83,97,99,105))
MOTION_APPLIED=re.compile(r'^@@DFMOTION1 APPLIED seq=(\d{1,9}) id=m(\d{3}) frame=1$')

class ESPMotionUnavailable(RuntimeError):pass

class H12MotionLink:
    def __init__(self,port,*,clock=time.monotonic):
        self.port=port;self.clock=clock;self.bridge=DeviceStateBridge()
        self.serial_seq=1;self.enabled=False
        self._rendered_id=None
        self._rendered_at=-1e20
        self._rendered_phase=None

    def _send(self,line:bytes):
        try:
            count=self.port.write(line);self.port.flush()
        except (OSError,ValueError) as exc:
            raise ESPMotionUnavailable('motion_usb_write_failed') from exc
        if count!=len(line):raise ESPMotionUnavailable('motion_usb_write_partial')

    @staticmethod
    def _receipt_line(raw:bytes):
        """Allow an exact protocol ACK fused to a known ESP-IDF log prefix."""
        line=raw.decode('ascii','replace').strip()
        if line.startswith('@@DF'):return line
        if (line.startswith(('I (','W (','E (','D (')) and len(line)<=350 and
            line.count('@@DF')==1):
            return line[line.index('@@DF'):]
        return line

    def _until(self,matcher,*,timeout=5.0):
        deadline=self.clock()+timeout
        while self.clock()<deadline:
            try:raw=self.port.readline()
            except (OSError,ValueError) as exc:
                raise ESPMotionUnavailable('motion_usb_read_failed') from exc
            if not raw:continue
            line=self._receipt_line(raw)
            if 'Guru Meditation' in line or 'Rebooting...' in line:
                raise ESPMotionUnavailable('motion_board_reboot')
            if line.startswith('@@DFMOTION1 UNAVAILABLE') or line=='@@DFMOTION1 REJECTED':
                raise ESPMotionUnavailable('motion_board_rejected_or_missing_sd')
            result=matcher(line)
            if result is not None:return result
        raise ESPMotionUnavailable('motion_ack_timeout')

    def probe(self):
        self._send(b'@@DFSTATE1 CAPS\n')
        self._until(lambda line: line if line=='@@DFSTATE1 READY phases=9' else None,timeout=3)
        self.bridge.bind('@@DFSTATE1 READY phases=9')
        self._send(b'@@DFMOTION1 CAPS\n')
        self._until(lambda line: line if line=='@@DFMOTION1 READY profile=selected35 store=sd' else None,timeout=8)
        self.bridge.bind('@@DFMOTION1 READY profile=selected35 store=sd')
        self.enabled=True
        return {'device_state':True,'device_selected35':True,'actual_frames_verified':False,
                'sd_motion_verified':False,'capability_only':True}

    def apply_phase_only(self,phase:str):
        """R244: verified physical recovery changes only the board UI phase.

        State ACK does not imply an SD animation frame rendered. Avoid a
        second full SD motion selection during silent WakeNet rearming.
        """
        if not self.enabled:raise ESPMotionUnavailable('motion_link_not_probed')
        seq,encoded=self.bridge.state_message(phase)
        self._send(encoded)
        self._until(lambda line: line if line==f'@@DFSTATE1 APPLIED seq={seq} phase={phase}' else None)
        self.bridge.verify_applied(f'@@DFSTATE1 APPLIED seq={seq} phase={phase}',seq,phase)
        return {'phase':phase,'display_ack':True,'motion_ack':False,
                'actual_esp32_frame_verified':False}

    def apply_verified(self,phase:str,motion_id:str):
        if not self.enabled:raise ESPMotionUnavailable('motion_link_not_probed')
        if not isinstance(motion_id,str) or not re.fullmatch(r'm\d{3}',motion_id) or int(motion_id[1:]) not in SELECTED_IDS:
            raise ESPMotionUnavailable('motion_not_selected_by_user')
        seq,encoded=self.bridge.state_message(phase)
        self._send(encoded)
        self._until(lambda line: line if line==f'@@DFSTATE1 APPLIED seq={seq} phase={phase}' else None)
        self.bridge.verify_applied(f'@@DFSTATE1 APPLIED seq={seq} phase={phase}',seq,phase)
        # Phase ACK is immediate, but a rapidly changing DSH tool stream
        # should not load a new multi-MB animation every few hundred ms.
        # Reuse only a previously verified frame for a short bounded window.
        # Speaking/error/listening remain urgent and are never deferred.
        now=self.clock()
        working=frozenset(('transcribing','thinking','tool_pending',
                           'approval_pending','voice_generating'))
        age=now-self._rendered_at
        if self._rendered_id is not None and (
            (motion_id==self._rendered_id and age<2.5) or
            (phase in working and self._rendered_phase in working and age<1.5)):
            self._rendered_phase=phase
            return {'phase':phase,'motion_id':self._rendered_id,
                    'frame_index':1,'actual_esp32_frame_verified':True,
                    'sd_motion_verified':True,
                    'reused_verified_frame':True,
                    'optical_display_verified_by_human':False}
        motion_seq=self.serial_seq;self.serial_seq+=1
        self._send(f'@@DFMOTION1 SELECT seq={motion_seq} id={motion_id}\n'.encode('ascii'))
        def displayed(line):
            if line=='@@DFMOTION1 QUEUED':return None
            match=MOTION_APPLIED.fullmatch(line)
            if match is None:return None
            if (int(match[1]),int(match[2]))!=(motion_seq,int(motion_id[1:])):
                raise ESPMotionUnavailable('motion_frame_receipt_mismatch')
            return {'phase':phase,'motion_id':motion_id,'frame_index':1,
                    'actual_esp32_frame_verified':True,
                    'sd_motion_verified':True,
                    'optical_display_verified_by_human':False}
        result=self._until(displayed,timeout=10)
        self._rendered_id=motion_id
        self._rendered_at=self.clock()
        self._rendered_phase=phase
        return result
