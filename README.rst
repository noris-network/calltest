===========
Call tester
===========

This program connects to an Asterisk server and performs call tests, i.e.
it causes one channel to call another and verifies that the call worked.

CallTest implements a small JSON server. You can use it with your favorite
monitoring system to check test results, or to manually trigger a test from
some web site or via ``curl``.

This package is a work in progress. Some planned features are not yet implemented.
Also, this README needs to be expanded and split up. Volunteers welcome.

Configuration
=============

The configuration is a YAML file and basically looks like this::

    links: 
      foo:
        channel: "SIP/foo/{number}"
        number: "+49123456789"
      bar:
        channel: "SIP/bar/{number}"
        number: "+49987654321"

    calls:
      ':default:':
        mode: dtmf

      foobar:
        src: foo
        dst: bar
        info: "Check that calling bar from foo works"


See ``example.cfg`` for a working version. Run ``./ct -c example.cfg
dumpcfg`` for a copy that's been pre-filled with default values.

Links
+++++

``links`` contains the Asterisk channels that CallTest can use.

These parameters are used when originating a call on the link:

* channel: The dial string used to call out on this channel. ``{number}`` is a
  placeholder for the destination phone number.

These parameters are used when answering a call:

* number: The number to dial, when calling this link.

The ``prio`` value is used for avoiding deadlocks when acquiring links for
bidirectional tests. If identical, the link's name is used.

The ':default:' values are applied to all other entries (unless overridden),
which saves you from changing 999 identical entries.


Calls
+++++

``calls`` contains a number of (named) tests.

* src: the source link to use, i.e. to originate the call.

* dst: the destination to use, i.e. to answer the call.

* mode: How to perform a test. See below.

* timeout: Hard limit for a call's duration. If a call exceeds this,
  it is terminated and the test fails.

* url: for answer-only modes, you need a way to cause a call. For now this
  is done by fetching the data at this URL.

  This field may either be a simple URL, or a dictionary with these attributes:

  * url
  * method (GET POST PUT)
  * query
  * body

  `query` and `body` may contain a ``{number}`` substitution.

* check_callerid: set to ``false`` to disable Caller ID verification.

The ':default:' values are applied to all other entries (unless overridden),
which saves you from changing 999 identical entries.

The ``test`` subheading contains values that are relevant for running
repeated tests in the background:

* retry, repeat: seconds to delay until repeating a call, depending on
  whether the previous attempt failed or succeeded.

* warn: number of consecutive failures when the test enters "warn" state.

* fail: number of consecutive failures when the test enters "fail" state.

* skip: if True, this test can only be triggered manually.


Modes
+++++

The ``mode`` value configure how CallTest processes a call.

dtmf
----

The answering channel sends a random sequence of DTMF tones. The originator
then does the same thing. The receivers verify that the codes are correct.

When ``dtmf.may_repeat`` is set, the receiver is allowed to read duplicate DTMF
tones. This flag might be necessary with in-band signalling.

``dtmf.len`` is the number of digits to test. Typically, one digit will be
repeated. The sequence is otherwise random.

call
----

The answering channel will acknowledge that it's ringing, but then simply
hang up.

audio
-----

Like DTMF, but both sides send a sound file instead. The sounds are
recorded. They should match, somewhat, but that's not yet tested.

ring
----

Originate-only: call this number. It should be RINGING. Then hang up.

play
----

Originate-only: call this number. It should answer. Play a sound, then
hang up.

If no ``audio.src_out`` sound is specified, simply hang up.

Optionally, ``audio.dst_in`` records incoming audio during the call.
Recording runs while the outgoing sound is playing.


fail
----

TODO.

Originate-only: call this number. The call may not go through. It must be
rejected, some time before ``ringtime``.

Also TODO: Add a flag to determine whether an intermediate ``Ringing``
state is allowed / required / prohibited.


timeout
-------

TODO.

Originate-only: call this number. The call may not go through. It must be
RINGing and then be rejected between ``ringtime`` and ``timeout`` seconds
later.


wait
----

Answer-only: wait for an incoming call, set it to RINGING, wait a few
seconds, hang up.


answer
------

Answer-only: wait for an incoming call, answer it, optionally play a sound,
optionally² record audio while the sound is playing, then hang up.


record
------

Answer-only:  wait for an incoming call, answer it, optionally play a sound,
optionally record incoming audio until the originator hangs up or presses
``#``.

The recording will be overlaid with the outgoing sound. This is an Asterisk
limitation.


Number format
+++++++++++++

CallTest recognizes two kinds of phone numbers: site-local extensions, and
everything else. CallTest distinguishes these by the initial '+'.

Outgoing
--------

The outgoing Asterisk channel should be able to handle both kinds directly.
If not, you need to write a "Local" channel that mangles the dialled number.
For instance, if you need to drop the '+', use this macro::

    context mangle {
        _+! => Dial(SIP/broken/${EXTEN:1});
    }

and then call ``Local/{number}@mangle``. As another example, if you need to use
lcoal number format to dial out::

    context mangle {
        _X! => Dial(SIP/broken/${EXTEN});  // pass-thru for local extensions
        _+49123! => Dial(SIP/broken/${EXTEN:6});  // 49123: country+city
        _+49! => Dial(SIP/broken/0${EXTEN:3});  // 49: country; 0: national prefix
        // _+! => Dial(SIP/broken/00${EXTEN:1}); // 00: international prefix
        _+! => Congestion();
    }

though you can probably get by with just the first and last line.

If you're in the NANP (USA or Canada), you probably want to use this macro
instead::

    context mangle {
        _N! => Dial(SIP/broken/1888${EXTEN});  // 888 is your area code
        _[01]! => Dial(SIP/broken/${EXTEN});  // pass-thru for operator and long-distance
        _+1! => Dial(SIP/broken/${EXTEN:1});  // long distance
        // _+! => Dial(SIP/broken/011${EXTEN:1});  // international
        _+! => Congestion();
    }

The last line causes a "Congestion" blocker so that a mistake
won't cause international charges.

Incoming
--------

CallTest will verify that the caller's number on an incoming call matches
the number in the test's configuration's source link. If that number is
prefixed with a '+', the incoming number is converted to international
format and needs to match exactly. Otherwise, the configured number is
assumed to be a local extension and must only be at the end of the
caller's.

This ensures that there's no incoming nonsense, while acknowledging that
site-local numbers often are not transmitted cleanly.

If you need Asterisk to mangle the caller's number so that it looks sane
enough for CallTest, add that to the ``calltest`` macro. For instance, if
your phone system adds a leading "get a trunk line" zero (in the NANP it's
usually a 9) to incoming calls, you'd do this::

    macro calltest(typ) {
        SET(cid=${CALLERID(num)})
        switch(cid) {
            pattern 0.:
                set(CALLERID(num)=${cid:1});
                break;
            default:
                break;
        }
        Stasis("calltest", ${typ});
        Hangup();
        return;
    }

We know that it's annoying to have to play with Asterisk's dialplans for this.
If you want to add a pattern-match-based number manglich scheme to
CallTest, great, we'll gladly accept a pull request. However, "sane" modern
phone systems should work fine with the default setting.

Asterisk configuration
++++++++++++++++++++++

Server connection
-----------------

Some parameters in the ``asterisk`` section require further elucidation.

* app: 

* audio: (the base of) the "sound" URL which Asterisk will use to find your
  test's outgoing sound files. Should be ``sound:/some/absolute/path``.

Test setup
----------

Asterisk needs to know how to direct incoming calls to the tester. This is
typically done with a Stasis macro. This is for ``extensions.ael``::

    macro calltest(link,nr) {
        Stasis(calltest,${link},${number});
        Hangup();
        return;
    }

* calltest: the ``asterisk.app`` config parameter. 

* link: the name of the link, in ``asterisk.link``.

* nr: the incoming destination phone number.

You'd call this macro from your context::

    1234 => &calltest(foo,${EXTEN});

If you want to route all incoming calls on a channel to this macro, use
something like this context::

   context ext_bar {
        s => &calltest(bar,);
        i => &calltest(bar,${INVALID_EXTEN});
        _+! => &calltest(bar,${EXTEN});
        _X! => &calltest(bar,${EXTEN});
        h => Hangup();
   }

Warning::

    These calls all have no spaces after the argument-separating commas.
    This is important.

Line setup
----------

PJSIP is not very forgiving. Sample config: TODO.

In lieu of voice quality checking, which this system does not yet do, you
might want to simply set your endpoints' DTMF mode to "inband". Don't use a
compressing codec when you do this. You might need to set the test's
``dtmf_may_repeat`` option. However, in-band DTMF is not particularly
reliable and may break randomly.

The random DTMF sequence only uses digits because letters are not
universally passed on, while ``#`` and ``*`` may be interpreted and thus
swallowed by intermediate systems.

Testing
-------

This package contains an ``example.cfg`` configuration. To use it, your
``asterisk.ael`` file should contain these lines::

    macro calltest(link, nr) {
        Stasis(calltest,${link},${number});
        Hangup();
        return;
    }

    context direct {
        _.! => &calltest(${EXTEN},);

        answer => {
            Wait(1);
            Answer();
            Wait(5);
            Hangup();
        }
        ringing => {
            Wait(1);
            Ringing();
            Wait(5);
            Hangup();
        }
        progress => {
            Wait(1);
            Progress();
            Wait(5);
            Hangup();
        }   
    }

Add this to your ``ari.conf``:

    [example]
    type = user
    password = oh_no_you_do_not
    password_format = plain

Finally, add ``enabled=yes`` to the ``[general]`` section of ``http.conf``.

After doing all of this and restarting your Asterisk (reloading "ael",
"http" and "res_ari" should work too), the command ``./ct -c example.cfg
run`` should pass.


Web service endpoints
=====================


* /

  List state and failed tests.

* /list

  Like ``/`` but als lists successful tests.

* /test/``name``

  Status for this test.

* /test/``name``/start (PUT)

  Start this test.

* /test/``name``/stop (PUT)

  Interrupt this test.

* /test/``name``/fail (PUT)

  Interrupt this test, mark the run as failed.

* /ws (web socket)

  Monitors the tester. Input on the websocket is discarded.

