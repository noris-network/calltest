# DTMF: exchange calls, 

from . import BaseIncall, BaseOutcall, BaseDualWorker
from . import ReadDTMF, wait_answered

class Worker(BaseDualWorker):
    def __init__(self, client, call):
        self.client = client
        self.call = call

    async def __call__(self):
        async with self.work() as (ic,oc):
            ok = anyio.create_event()
            sync = anyio.create_event()
            in_dtmf = "".join("*",*random.choices("1243567890",6),"#")
            out_dtmf = "".join("*",*random.choices("1243567890",6),"#")

            async def run_in():
                await wait_answered(ic)
                await sync.wait()
                await ic.sendDTMF(dtmf=in_dtmf)
                await ReadDTMF(ic, dtmf=out_dtmf)
                await ok.set()

            async def run_out():
                await wait_answered(oc)
                await ReadDTMF(oc, dtmf=in_dtmf, evt=sync)
                await oc.sendDTMF(dtmf=out_dtmf)
                
            await ic.tg.spawn(run_in)
            await oc.tg.spawn(run_out)
            await ok.wait()

