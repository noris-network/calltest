"""
Outgoing call that plays a sound file, then ends the call.
"""

import anyio

from . import BaseOutWorker
from . import wait_ringing
from . import SyncPlay, start_record
from asyncari.util import mayNotExist

import logging
logger = logging.getLogger(__name__)

class Worker(BaseOutWorker):
    async def __call__(self):
        async with self.out_call() as ocm:

            await self.connect_out(ocm)
            outfile = self.call.audio.src_out
            infile = self.call.audio.src_in
            if outfile is not None:
                if infile is not None:
                    res = await start_record(ocm, infile)
                else:
                    res = None
                await SyncPlay(ocm, outfile)
                if res is not None:
                    with mayNotExist:
                        await res.stop(recordingName=infile)
                
