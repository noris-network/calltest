"""
Exchange DTMF signalling.

Caller and receiver each select a random DTMF sequence whcih they send to
the other side.

The callee sends first.
"""

import anyio

from . import BaseDualWorker
from . import ExpectDTMF, random_dtmf

import logging
logger = logging.getLogger(__name__)

class Worker(BaseDualWorker):
    async def __call__(self):
        async with self.dual_call() as (icm, ocm):
            # Coordinate between the tasks; DTMF sending must wait
            # until the receiver is listening
            sync1 = anyio.create_event()
            sync3 = anyio.create_event()
            sync2 = anyio.create_event()

            in_dtmf = random_dtmf(len=self.call.dtmf.len)
            out_dtmf = random_dtmf(len=self.call.dtmf.len)

            async def run_in():
                await self.connect_in(icm)
                await sync1.wait()
                await icm.channel.sendDTMF(dtmf=in_dtmf, between=0.5)
                await ExpectDTMF(icm, dtmf=out_dtmf, ready=sync2, may_repeat=self.call.dtmf.may_repeat)
                await sync3.set()

            async def run_out():
                await self.connect_out(ocm)
                await ExpectDTMF(ocm, dtmf=in_dtmf, ready=sync1, may_repeat=self.call.dtmf.may_repeat)
                await sync2.wait()
                await ocm.channel.sendDTMF(dtmf=out_dtmf, between=0.5)
                await sync3.wait()
                
            await icm.taskgroup.spawn(run_in)
            await ocm.taskgroup.spawn(run_out)
            await sync3.wait()

