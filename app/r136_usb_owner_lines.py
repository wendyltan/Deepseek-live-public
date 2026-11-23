"""Transparent one-owner USB line pushback for microphone preemption.

The screen reader must return the *exact* actual microphone BEGIN bytes
instead of consuming a board voice packet while cancelling its screenshot.
Never opens a second port; avoids storing audio data.
"""
from collections import deque
class OwnedLinePort:
    def __init__(self,actual):
        self.actual=actual
        self._pending=deque()
    def unread(self,line:bytes):
        if not isinstance(line,bytes) or not line or len(self._pending)>=3:
            raise ValueError('invalid_unread_mic_frame')
        self._pending.appendleft(line)
    def readline(self):
        return self._pending.popleft() if self._pending else self.actual.readline()
    def __getattr__(self,name):
        return getattr(self.actual,name)
