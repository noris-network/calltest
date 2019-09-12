"""
Answer-only mode. Accepts a sound file to play, plus optionally a file to
record to while playing.

The call ends / recording stops when the outgoing audio ends, or
immediately if there is no outgoing audio.
"""
import anyio

from . import BaseInWorker
from . import SyncPlay, start_record
from asyncari.util import mayNotExist
from asyncari.state import BridgeState

import logging
logger = logging.getLogger(__name__)

class Worker(BaseInWorker):
    async def __call__(self):
        async with self.in_call() as icm:

            await self.connect_in(icm)

            outfile = self.call.audio.dst_out
            infile = self.call.audio.dst_in

            async with BridgeState.new(self.client) as br:
                await br.add(icm.channel)

                if outfile is not None:
                    if infile is not None:
                        res = await start_record(br, infile)
                    else:
                        res = None
                    await SyncPlay(br, outfile)
                    if res is not None:
                        with mayNotExist:
                            await res.stop(recordingName=infile)
                
