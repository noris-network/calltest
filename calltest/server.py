import anyio
import asyncari
from .util import attrdict
from typing import Optional, Any
from functools import partial
from quart_trio import QuartTrio as Quart
from hypercorn.config import Config as HyperConfig
from hypercorn.trio import serve as hyper_serve
from quart.logging import create_serving_logger
from quart import jsonify, websocket

async def run (  # type: ignore
    self, # app
    host: str = "127.0.0.1",
    port: int = 5000,
    debug: Optional[bool] = None,
    ca_certs: Optional[str] = None,
    certfile: Optional[str] = None,
    keyfile: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """Run this application.
    """
    config = HyperConfig()
    config.access_log_format = "%(h)s %(r)s %(s)s %(b)s %(D)s"
    config.access_logger = create_serving_logger()  # type: ignore
    config.bind = [f"{host}:{port}"]
    config.ca_certs = ca_certs
    config.certfile = certfile
#   if debug is not None:
#       config.debug = debug
    config.error_logger = config.access_logger  # type: ignore
    config.keyfile = keyfile
    config.use_reloader = False

    scheme = "http" if config.ssl_enabled is None else "https"

    await hyper_serve(self, config)


async def serve(cfg, checks):
    ast = cfg.asterisk
    url = "http://%s:%d/" % (ast.host,ast.port)

    stats = {}
    socks = set()
    app = Quart("calltest.server", root_path="/tmp")
    @app.route("/", methods=['GET'])
    @app.route("/list", defaults={'with_ok':True}, methods=['GET'])
    async def index(with_ok=False):
        s = attrdict()
        s.fail = list(k for k,v in stats.items() if v.fail_count >= checks[k].test.fail)
        s.warn = list(k for k,v in stats.items() if checks[k].test.fail > v.fail_count >= checks[k].test.warn)
        s.note = list(k for k,v in stats.items() if checks[k].test.warn > v.fail_count > 0 or v.fail_count == 0 and v.fail_map)
        ok = list(k for k,v in stats.items() if v.fail_count == 0 and v.n_run > 0)
        if with_ok:
            s.ok = ok
            s.skip = list(k for k,v in stats.items() if checks[k].test.skip)
            s.n_skip = len(s.skip)
        s.n_fail = len(s.fail)
        s.n_warn = len(s.warn)
        s.n_note = len(s.note)
        s.n_ok = len(ok)
        return jsonify(s)

    async def alert(**msg):
        nonlocal socks
        ds = set()
        for s in socks:
            try:
                await s.send(msg)
            except Exception:
                ds.add(s)
        socks -= ds

    @app.route("/test/<test>", methods=['GET'])
    async def test_detail(test):
        c = checks[test]
        return jsonify(c.state)

    @app.route("/test/<test>/start", methods=['PUT'])
    async def test_start(test):
        c = checks[test]
        res = await c.test_start()
        return jsonify({"success":res})

    @app.route("/test/<test>/stop", methods=['PUT'])
    async def test_stop(test):
        c = checks[test]
        res = await c.test_stop(fail=False)
        return jsonify({"success":res})

    @app.route("/test/<test>/fail", methods=['PUT'])
    async def test_fail(test):
        c = checks[test]
        res = await c.test_stop(fail=True)
        return jsonify({"success":res})

    @app.websocket('/ws')
    async def ws():
        try:
            sock = websocket._get_current_object()
            socks.add(sock)
            while True:
                data = await sock.receive()
                print("IN",data)
        finally:
            socks.discard(sock)

    async def updated(call):
        await alert(action="update", name=call.name, state=call.state)
        stats[call.name] = call.state

    async with asyncari.connect(url, ast.app, username=ast.username, password=ast.password) as client:
        client._calltest_config = cfg
        async with anyio.create_task_group() as tg:
            await tg.spawn(partial(run, app, **cfg.server, debug=True))
            for c in checks.values():
                await tg.spawn(partial(c.run, client, updated=updated))
            pass # end loop
        pass # end taskgroup

