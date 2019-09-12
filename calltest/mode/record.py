"""
Incoming call that records its audio until the originator hangs up.
"""

import anyio

from . import BaseInWorker
from . import SyncPlay, start_record
from asyncari.util import mayNotExist
from asyncari.state import BridgeState, DTMFHandler

import logging
logger = logging.getLogger(__name__)

class RecBridgeState(DTMFHandler, BridgeState):
    def __init__(self, *a, rec_evt=None, **k):
        super().__init__(*a, **k)
        self._rec_evt = rec_evt

    async def on_dtmf_Pound(self, evt):
        await self._rec_evt.set()

class Worker(BaseInWorker):
    async def __call__(self):
        async with self.in_call() as icm:

            await self.connect_in(icm)

            outfile = self.call.audio.dst_out
            infile = self.call.audio.dst_in

            rec_evt = anyio.create_event()
            async with RecBridgeState.new(self.client, rec_evt=rec_evt) as br:
                await br.add(icm.channel)

                if infile is not None:
                    res = await start_record(br, infile)
                else:
                    res = None

                if outfile is not None:
                    await SyncPlay(br, outfile)

                if res is not None:
                    await rec_evt.wait()
                    with mayNotExist:
                        await res.stop(recordingName=infile)
                
