# DTMF: exchange calls, 

import anyio

from . import BaseDualWorker
from . import ExpectDTMF, wait_answered, random_dtmf

import logging
logger = logging.getLogger(__name__)

class Worker(BaseDualWorker):
    async def __call__(self):
        async with self.dual_call() as (icm, ocm):
            ok = anyio.create_event()
            sync = anyio.create_event()
            sync2 = anyio.create_event()

            in_dtmf = random_dtmf(len=self.call.dtmf.len)
            out_dtmf = random_dtmf(len=self.call.dtmf.len)

            async def run_in():
                await self.connect_in(icm)
                await sync.wait()
                await icm.channel.sendDTMF(dtmf=in_dtmf)
                await ExpectDTMF(icm, dtmf=out_dtmf, evt=sync2, may_repeat=self.call.dtmf.may_repeat)
                await ok.set()

            async def run_out():
                await self.connect_out(ocm)
                await ExpectDTMF(ocm, dtmf=in_dtmf, evt=sync, may_repeat=self.call.dtmf.may_repeat)
                await sync2.wait()
                await ocm.channel.sendDTMF(dtmf=out_dtmf)
                await ok.wait()
                
            await icm.taskgroup.spawn(run_in)
            await ocm.taskgroup.spawn(run_out)
            await ok.wait()

