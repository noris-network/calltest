"""
This module contains the default values for calltest configuration.
"""

from .util import attrdict

__all__ = ["PORT", "CFG", "DEFAULT"]

ARI_PORT = 8088

# This default configuration will be used to supplement whatever
# configuration you use.
# It is "complete" in the sense that DistKV will never die
# due to a KeyError caused by a missing config value.

DEFAULT = ":default:"

CFG = attrdict(
    logging={ # a magic incantation
        "version":1,
        "loggers":{
            "asyncari": {"level":"INFO"},
        },
        "root":{
            "handlers": ["stderr",],
            "level":"INFO",
        },
        "handlers": {
            "logfile": {
                "class":"logging.FileHandler",
                "filename":"test.log",
                "level":"DEBUG",
                "formatter":"std",
            },
            "stderr": {
                "class":"logging.StreamHandler",
                "level":"DEBUG",
                "formatter":"std",
                "stream":"ext://sys.stderr",
            },
        },
        "formatters": {
            "std":{
                "class":"calltest.util.TimeOnlyFormatter",
                "format":'%(asctime)s %(levelname)s:%(name)s:%(message)s',
            },
        },
        "disable_existing_loggers":False,
    },
    asterisk=attrdict(
        # client: controls talking to the DistKV server
        host="localhost",
        port=ARI_PORT,
        ssl=False,
        # ssl=attrdict(cert='/path/to/cert.pem',key='/path/to/cert.key'),
        init_timeout=5,  # time to wait for connection plus greeting
        username="asterisk",
        password="asterisk",
        app="calltest",

        dialplan=attrdict(
            country="49",
            intl="00",
            city="FIXME",
            nat="0"
        ),
    ),
    server=attrdict(
        # a simple HTTP server that publishes test results via JSON.
        host="127.0.0.1",
        port=8080,
        prio=0,
    ),

    # maps app names to channels and phone numbers.
    # { "foo": attrdict(
    #          channel="SIP/bar/{nr}",           # incoming: Stasis argument 1
    #          number="+49123456789"),
    # }
    links = {
        DEFAULT: {
            "channel": None,
            "number": None,
        },
    },

    # list of named tests.
    # The test will be repeated every 10 minutes when successful and
    # retried every 5 min when unsuccessful.
    # 
    # These modes call me:
    # * dtmf: answer, exchange a random DTMF sequence to verify connectivity.
    # * call: simply test that a call arrives. It will be rejected, so no cost.
    # 
    # These modes only originate:
    # * ring: check for RINGING state (or ANSWER …) then hang up.
    # * try: check for ANSWER, optionally play a sound, then hang up.
    # * fail: verify that this call is rejected.
    #
    # These modes only answer:
    # * wait: wait for an incoming call, let it ring, then hang up.
    # * answer: wait for an incoming call, answer it, optionally play a sound, then hang up.
    # * record: wait for an incoming call, answer it, record audio until the caller hangs up.

    calls = {
        DEFAULT: {
            "retry": 5*60,
            "repeat": 10*60,
            "src": None,   # link. Must be missing for answer tests.
            "dst": None,   # link. Must be missing for originate tests.
            "mode": "dtmf",   # see below
            "timeout": 30, # seconds
            "info": "-", # short documentation
            "dtmf": attrdict(
              may_repeat=False, # lax DTMF comparison?
              len=5, # #digits
            ),
            "delay": attrdict(
                pre=0, # incoming: before doing anything
                ring=1, # incoming: after setting RINGING
                answer=1, # after establishing the call
            )
        },
    },
)
