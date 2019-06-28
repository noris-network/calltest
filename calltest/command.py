# command line interface

import os
import sys
import trio_click as click
from pprint import pprint
import json
from functools import partial

from .util import attrdict
from .model import gen_links
from .default import CFG

import logging
from logging.config import dictConfig

logger = logging.getLogger(__name__)


def cmd():
    """
    The main command entry point, as declared in ``setup.py``.
    """
    try:
        main(standalone_mode=False)
    except click.exceptions.MissingParameter as exc:
        print("You need to provide an argument '%s'.\n" % (exc.param.name.upper()), file=sys.stderr)
        print(exc.cmd.get_help(exc.ctx), file=sys.stderr)
        sys.exit(2)
    except click.exceptions.UsageError as exc:
        try:
            s = str(exc)
        except TypeError:
            logger.exception(repr(exc), exc_info=exc)
        else:
            print(s, file=sys.stderr)
        sys.exit(2)
    except click.exceptions.Abort:
        print("Aborted.", file=sys.stderr)
        pass
    except EnvironmentError as exc:
        print(type(err).__name__ + ":", *err.args, file=sys.stderr)
        sys.exit(1)
    except BaseException as exc:
        raise
        # print(exc)
        # sys.exit(1)


@click.group()
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Enable debugging. Use twice for more verbosity.",
)
@click.option(
    "-l", "--log", multiple=True, help="Adjust log level. Example: '--log asyncserf.actor=DEBUG'."
)
@click.option(
    "-q", "--quiet", count=True, help="Disable debugging. Opposite of '--verbose'."
)
@click.option("-c", "--cfg", type=click.File("r"), default=None, help="Configuration file (YAML).")
@click.option("-C", "--conf", multiple=True, help="Override a config entry. Example: '-C server.bind_default.port=57586'")
@click.pass_context
async def main(ctx, verbose, quiet, log, cfg, conf):
    """
    "calltest" periodically runs calls to verify that a phone
    line is operational.

    See the "help" subcommand for details.
    """
    ctx.ensure_object(attrdict)
    ctx.obj.debug = max(verbose - quiet + 1, 0)
    
    if cfg:
        logger.debug("Loading %s", cfg)
        import yaml

        ctx.obj.cfg = combine_dict(yaml.safe_load(cfg), CFG, cls=attrdict)
        cfg.close()
    else:
        ctx.obj.cfg = CFG

    # One-Shot-Hack the config file.
    for k in conf:
        try:
            k,v = k.split('=')
        except ValueError:
            v = NotGiven
        else:
            try:
                v = eval(v)
            except Exception:
                pass
        c = ctx.obj.cfg
        *sl, s = k.split('.')
        for k in sl:
            c = c[k]
        if v is NotGiven:
            del c[s]
        else:
            c[s] = v

    # Configure logging. This is a somewhat arcane art.
    lcfg = ctx.obj.cfg.logging
    lcfg['root']['level'] = "DEBUG" if verbose > 2 else "INFO" if verbose > 1 else "WARNING" if verbose else "ERROR"
    for k in log:
        k,v = k.split('=')
        lcfg['loggers'].setdefault(k, {})['level'] = v
    dictConfig(lcfg)
    logging.captureWarnings(verbose > 0)

    ctx.obj.links = gen_links(ctx.obj.cfg)


@main.command(short_help="Import the debugger",
        help="Imports PDB and then continues to process arguments.")
@click.argument("args", nargs=-1)
async def pdb(args):  # safe
    import pdb

    pdb.set_trace()  # safe
    if not args:
        return
    return await main.main(args)

@main.command()
@click.argument("check")
@click.pass_obj
async def run(obj):
    """
    Run a one-shot call.
    """

@main.command()
@click.pass_obj
async def dumpcfg(obj):
    """emit the current configuration as a YAML file."""
    import yaml
    yaml.safe_dump(obj.cfg, stream=sys.stdout)
