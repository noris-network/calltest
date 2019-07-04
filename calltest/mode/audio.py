# DTMF: exchange calls, 

import anyio

from asyncari.util import mayNotExist
from . import BaseDualWorker, SyncPlay, start_record

import logging
logger = logging.getLogger(__name__)

class Worker(BaseDualWorker):
    async def __call__(self):
        async with self.dual_call() as (icm, ocm):
            # Coordinate between the tasks; DTMF sending must wait
            # until the receiver is listening
            sync1 = anyio.create_event()
            sync2 = anyio.create_event()
            sync3 = anyio.create_event()

            async def run_in():
                outfile = self.call.audio.dst_out
                infile = self.call.audio.dst_in

                await self.connect_in(icm)
                await sync1.wait()
                if outfile:
                    await SyncPlay(icm, outfile)
                res = await start_record(icm, infile) if infile is not None else None
                await sync2.set()
                await sync3.wait()
                if res is not None:
                    with mayNotExist:
                        await res.stop(recordingName=infile)


            async def run_out():
                outfile = self.call.audio.src_out
                infile = self.call.audio.src_in

                await self.connect_out(ocm)
                res = await start_record(ocm, infile) if infile is not None else None
                await sync1.set()
                await sync2.wait()
                if res is not None:
                    with mayNotExist:
                        await res.stop(recordingName=infile)
                if outfile is not None:
                    await SyncPlay(ocm, outfile)
                await sync3.set()
                
            await icm.taskgroup.spawn(run_in)
            await ocm.taskgroup.spawn(run_out)
            await sync3.wait()

