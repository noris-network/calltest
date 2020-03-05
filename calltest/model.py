#
# calltest data model

import anyio
import importlib
import time
import math

from contextlib import asynccontextmanager, AsyncExitStack
from functools import partial
import traceback

from .util import attrdict, combine_dict
from .default import DEFAULT

import logging
logger = logging.getLogger(__name__)

class Link:
    def __init__(self, name, channel, number, prio=0, **kw):
        self.name = name
        self.channel = channel
        self.number = number
        self._prio = prio
        for k,v in kw.items():
            setattr(self,k,v)
        self.lock = anyio.create_lock()

    def __repr__(self):
        return "<%s:%s>" % (self.__class__.__name__,self.name)

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other,Link):
            other = other.name
        return self.name == other

    @property
    def prio(self):
        """Relative priority. Used for deadlock avoidance."""
        return (self._prio, self.name)


@asynccontextmanager
async def locked_links(*locks):
    """
    Given a number of :cls:`Link` objects, lock them all in an order that
    prevents deadlocks.

    Usage::
        async with lock(src, dst):
            await process(src,dst)
    """
    async with AsyncExitStack() as s:
        for l in sorted(locks, key=lambda x: x.prio):
            await s.enter_async_context(l.lock)
        yield s


def gen_links(cfg):
    res = attrdict()
    default = cfg.links[DEFAULT]
    for k,v in cfg.links.items():
        if k == DEFAULT:
            continue
        v = combine_dict(v, default, cls=attrdict)
        l = Link(name=k, **v)
        res[k] = l
    return res

class Call:
    error = None
    err_count = 0
    _delay = None  # event for starting
    scope = None  # scope for stopping

    def __init__(self, links, name, *, timeout, mode="dtmf", info="-", src=None, dst=None, **kw):
        self.name = name
        self.mode = importlib.import_module("calltest.mode."+mode).Worker
        self.src = links[src] if src is not None else None
        self.dst = links[dst] if dst is not None else None
        self.info = info
        self.timeout = timeout
        self.state = attrdict(status="new", ct_wait=0, ct_run=0)
        self.state.t_start=time.time()
        for k,v in kw.items():
            setattr(self,k,v)
        self.lock = anyio.create_lock()

    def __repr__(self):
        return "<%s:%s>" % (self.__class__.__name__,self.name)

    async def __call__(self, client):
        runner = self.mode(client, self)
        self.state.t_wait=time.time()
        self.state.status="waiting"
        self.state.waiting=True
        try:
            async with runner.lock:
                self.state.waiting=False
                self.state.running=True
                self.state.status="running"
                self.state.t_start=time.time()
                self.state.ct_wait += self.state.t_start-self.state.t_wait
                async with anyio.fail_after(self.timeout):
                    await runner()
        finally:
            self.state.status="idle"
            self.state.running=False
            self.state.t_stop=time.time()
            self.state.ct_run += self.state.t_stop-self.state.t_start

    async def _run(self,client):
        state = self.state
        async with anyio.open_cancel_scope() as sc:
            self.scope = sc
            try:
                await self(client)
            except anyio.get_cancelled_exc_class():
                state.exc = "Canceled"
                if self.scope is not None:
                    state.n_fail += 1
                    state.fail_count += 1
                    state.fail_map.append(True)
                raise
            except Exception as exc:
                state.exc = traceback.format_exc().split('\n')
                state.n_fail += 1
                state.fail_count += 1
                state.fail_map.append(True)
            else:
                state.fail_count = 0 
                state.fail_map.append(False)
            finally:
                state.n_run += 1

                if any(state.fail_map):
                    del state.fail_map[:-20]
                else:
                    state.fail_map = []
                    # zero out after 20 successes in sequence
                self.scope = None
                logger.warning("END %s",self.name)

    async def run(self, client, updated=None):
        """
        Background task runner for this test, stores exceptions.

        :param updated: Callback that's fired when this test's status
                        changes.
        The accumulated test status is in the ``state`` attribute.
        """
        if updated is None:
            async def updated():
                pass
        else:
            updated = partial(updated, self)

        state = self.state
        state.update({
            "n_run": 0, # total
            "n_fail": 0, # total

            "running": False,
            "last_exc": None,
            "fail_map": [], # last 20 or whatever
            "fail_count": 0,
        })

        if self.test.skip:
            # on demand only
            while True:
                await updated()
                self._delay = anyio.create_event()
                await self._delay.wait()
                await updated()
                await self._run(client)

        else:
            while True:
                await updated()
                await self._run(client)
                await updated()
                self._delay = anyio.create_event()
                if state.fail_count > 0:
                    dly = self.test.retry
                else:
                    dly = self.test.repeat
                async with anyio.move_on_after(dly):
                    await self._delay.wait()

    async def test_start(self):
        """
        Start this test, either prematurely or at all.
        """
        if self._delay is None or self._delay.is_set():
            return False
        await self._delay.set()
        return True

    async def test_stop(self, fail=True):
        """Prematurely stop this test.
        
        :param fail: if set (default), count this cancellation as a failure.
        """
        sc = self.scope
        if sc is None:
            return False
        if not fail:
            self.scope = None
        await sc.cancel()

def gen_calls(links, cfg):
    res = attrdict()
    default = cfg.calls[DEFAULT]
    for k,v in cfg.calls.items():
        if k == DEFAULT:
            continue
        v = combine_dict(v, default, cls=attrdict)
        c = Call(links, name=k, **v)
        res[k] = c
    return res


