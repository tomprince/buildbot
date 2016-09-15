# coding=utf-8

# Everything below this is extracted from twisted.application.internet
# from Twisted 16.4.1.

# Copyright (c) 2001-2016
# Allen Short
# Amber Hawkie Brown
# Andrew Bennetts
# Andy Gayton
# Antoine Pitrou
# Apple Computer, Inc.
# Ashwini Oruganti
# Benjamin Bruheim
# Bob Ippolito
# Canonical Limited
# Charmander
# Christopher Armstrong
# David Reid
# Divmod Inc.
# Donovan Preston
# Eric Mangold
# Eyal Lotem
# Google Inc.
# Hybrid Logic Ltd.
# Hynek Schlawack
# Itamar Turner-Trauring
# James Knight
# Jason A. Mobarak
# Jean-Paul Calderone
# Jessica McKellar
# Jonathan D. Simms
# Jonathan Jacobs
# Jonathan Lange
# Julian Berman
# Jürgen Hermann
# Kevin Horn
# Kevin Turner
# Laurens Van Houtven
# Mary Gardiner
# Massachusetts Institute of Technology
# Matthew Lefkowitz
# Moshe Zadka
# Paul Swartz
# Pavel Pergamenshchik
# Rackspace, US Inc.
# Ralph Meijer
# Richard Wall
# Sean Riley
# Software Freedom Conservancy
# Tavendo GmbH
# Thijs Triemstra
# Thomas Herve
# Timothy Allen
# Tom Prince
# Travis B. Hartwell

# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:

# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""
A backport of ClientService for earlier versions of twisted.
"""

from __future__ import absolute_import
from __future__ import division

from random import random as _goodEnoughRandom

from twisted.application import service
from twisted.internet.defer import CancelledError
from twisted.internet.defer import Deferred
from twisted.internet.defer import fail
from twisted.internet.defer import gatherResults
from twisted.internet.defer import succeed
from twisted.python.failure import Failure

try:
    from twisted.logger import Logger
except ImportError:
    from .twisted_logger import Logger


def _maybeGlobalReactor(maybeReactor):
    """
    @return: the argument, or the global reactor if the argument is L{None}.
    """
    if maybeReactor is None:
        from twisted.internet import reactor
        return reactor
    else:
        return maybeReactor


class _ReconnectingProtocolProxy(object):
    """
    A proxy for a Protocol to provide connectionLost notification to a client
    connection service, in support of reconnecting when connections are lost.
    """

    def __init__(self, protocol, lostNotification):
        """
        Create a L{_ReconnectingProtocolProxy}.

        @param protocol: the application-provided L{interfaces.IProtocol}
            provider.
        @type protocol: provider of L{interfaces.IProtocol} which may
            additionally provide L{interfaces.IHalfCloseableProtocol} and
            L{interfaces.IFileDescriptorReceiver}.

        @param lostNotification: a 1-argument callable to invoke with the
            C{reason} when the connection is lost.
        """
        self._protocol = protocol
        self._lostNotification = lostNotification

    def connectionLost(self, reason):
        """
        The connection was lost.  Relay this information.

        @param reason: The reason the connection was lost.

        @return: the underlying protocol's result
        """
        try:
            return self._protocol.connectionLost(reason)
        finally:
            self._lostNotification(reason)

    def __getattr__(self, item):
        return getattr(self._protocol, item)

    def __repr__(self):
        return '<%s wrapping %r>' % (
            self.__class__.__name__, self._protocol)


class _DisconnectFactory(object):
    """
    A L{_DisconnectFactory} is a proxy for L{IProtocolFactory} that catches
    C{connectionLost} notifications and relays them.
    """

    def __init__(self, protocolFactory, protocolDisconnected):
        self._protocolFactory = protocolFactory
        self._protocolDisconnected = protocolDisconnected

    def buildProtocol(self, addr):
        """
        Create a L{_ReconnectingProtocolProxy} with the disconnect-notification
        callback we were called with.

        @param addr: The address the connection is coming from.

        @return: a L{_ReconnectingProtocolProxy} for a protocol produced by
            C{self._protocolFactory}
        """
        return _ReconnectingProtocolProxy(
            self._protocolFactory.buildProtocol(addr),
            self._protocolDisconnected
        )

    def __getattr__(self, item):
        return getattr(self._protocolFactory, item)

    def __repr__(self):
        return '<%s wrapping %r>' % (
            self.__class__.__name__, self._protocolFactory)


def backoffPolicy(initialDelay=1.0, maxDelay=60.0, factor=1.5,
                  jitter=_goodEnoughRandom):
    """
    A timeout policy for L{ClientService} which computes an exponential backoff
    interval with configurable parameters.

    @since: 16.1.0

    @param initialDelay: Delay for the first reconnection attempt (default
        1.0s).
    @type initialDelay: L{float}

    @param maxDelay: Maximum number of seconds between connection attempts
        (default 60 seconds, or one minute).  Note that this value is before
        jitter is applied, so the actual maximum possible delay is this value
        plus the maximum possible result of C{jitter()}.
    @type maxDelay: L{float}

    @param factor: A multiplicative factor by which the delay grows on each
        failed reattempt.  Default: 1.5.
    @type factor: L{float}

    @param jitter: A 0-argument callable that introduces noise into the delay.
        By default, C{random.random}, i.e. a pseudorandom floating-point value
        between zero and one.
    @type jitter: 0-argument callable returning L{float}

    @return: a 1-argument callable that, given an attempt count, returns a
        floating point number; the number of seconds to delay.
    @rtype: see L{ClientService.__init__}'s C{retryPolicy} argument.
    """
    def policy(attempt):
        return min(initialDelay * (factor ** attempt), maxDelay) + jitter()
    return policy

_defaultPolicy = backoffPolicy()


def _noop():
    """
    Do nothing; this stands in for C{transport.loseConnection()} and
    C{DelayedCall.cancel()} when L{ClientService} is in a state where there's
    nothing to do.
    """


class ClientService(service.Service, object):
    """
    A L{ClientService} maintains a single outgoing connection to a client
    endpoint, reconnecting after a configurable timeout when a connection
    fails, either before or after connecting.

    @since: 16.1.0
    """

    _log = Logger()

    def __init__(self, endpoint, factory, retryPolicy=None, clock=None):
        """
        @param endpoint: A L{stream client endpoint
            <interfaces.IStreamClientEndpoint>} provider which will be used to
            connect when the service starts.

        @param factory: A L{protocol factory <interfaces.IProtocolFactory>}
            which will be used to create clients for the endpoint.

        @param retryPolicy: A policy configuring how long L{ClientService} will
            wait between attempts to connect to C{endpoint}.
        @type retryPolicy: callable taking (the number of failed connection
            attempts made in a row (L{int})) and returning the number of
            seconds to wait before making another attempt.

        @param clock: The clock used to schedule reconnection.  It's mainly
            useful to be parametrized in tests.  If the factory is serialized,
            this attribute will not be serialized, and the default value (the
            reactor) will be restored when deserialized.
        @type clock: L{IReactorTime}
        """
        clock = _maybeGlobalReactor(clock)
        retryPolicy = _defaultPolicy if retryPolicy is None else retryPolicy

        self._endpoint = endpoint
        self._failedAttempts = 0
        self._stopped = False
        self._factory = factory
        self._timeoutForAttempt = retryPolicy
        self._clock = clock
        self._stopRetry = _noop
        self._lostDeferred = succeed(None)
        self._connectionInProgress = succeed(None)
        self._loseConnection = _noop

        self._currentConnection = None
        self._awaitingConnected = []

    def whenConnected(self):
        """
        Retrieve the currently-connected L{Protocol}, or the next one to
        connect.

        @return: a Deferred that fires with a protocol produced by the factory
            passed to C{__init__}
        @rtype: L{Deferred} firing with L{IProtocol} or failing with
            L{CancelledError} the service is stopped.
        """
        if self._currentConnection is not None:
            return succeed(self._currentConnection)
        elif self._stopped:
            return fail(CancelledError())
        else:
            result = Deferred()
            self._awaitingConnected.append(result)
            return result

    def _unawait(self, value):
        """
        Fire all outstanding L{ClientService.whenConnected} L{Deferred}s.

        @param value: the value to fire the L{Deferred}s with.
        """
        self._awaitingConnected, waiting = [], self._awaitingConnected
        for w in waiting:
            w.callback(value)

    def startService(self):
        """
        Start this L{ClientService}, initiating the connection retry loop.
        """
        if self.running:
            self._log.warn("Duplicate ClientService.startService {log_source}")
            return
        super(ClientService, self).startService()
        self._failedAttempts = 0

        def connectNow():
            thisLostDeferred = Deferred()

            def clientConnect(protocol):
                self._failedAttempts = 0
                self._loseConnection = protocol.transport.loseConnection
                self._lostDeferred = thisLostDeferred
                self._currentConnection = protocol._protocol
                self._unawait(self._currentConnection)

            def clientDisconnect(reason):
                self._currentConnection = None
                self._loseConnection = _noop
                thisLostDeferred.callback(None)
                retry(reason)

            factoryProxy = _DisconnectFactory(self._factory, clientDisconnect)

            self._stopRetry = _noop
            self._connectionInProgress = (self._endpoint.connect(factoryProxy)
                                          .addCallback(clientConnect)
                                          .addErrback(retry))

        def retry(failure):
            if not self.running:
                return
            self._failedAttempts += 1
            delay = self._timeoutForAttempt(self._failedAttempts)
            self._log.info("Scheduling retry {attempt} to connect {endpoint} "
                           "in {delay} seconds.", attempt=self._failedAttempts,
                           endpoint=self._endpoint, delay=delay)
            self._stopRetry = self._clock.callLater(delay, connectNow).cancel

        connectNow()

    def stopService(self):
        """
        Stop attempting to reconnect and close any existing connections.

        @return: a L{Deferred} that fires when all outstanding connections are
            closed and all in-progress connection attempts halted.
        """
        super(ClientService, self).stopService()
        self._stopRetry()
        self._stopRetry = _noop
        self._connectionInProgress.cancel()
        self._loseConnection()
        self._currentConnection = None

        def finishStopping(result):
            if not self.running:
                self._stopped = True
                self._unawait(Failure(CancelledError()))
            return None
        return (gatherResults([self._connectionInProgress, self._lostDeferred])
                .addBoth(finishStopping))


__all__ = ['ClientService']
