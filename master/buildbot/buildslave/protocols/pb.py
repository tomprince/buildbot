# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

from __future__ import absolute_import, print_function

from itertools import count

from zope.interface import implements

from twisted.python import log
from twisted.internet import defer, reactor
from twisted.application.service import Service
from buildbot.buildslave.protocols import base
from twisted.spread import pb
from twisted.python.util import FancyStrMixin
from buildbot.util import ComparableMixin


class Connector(FancyStrMixin, ComparableMixin, Service, object):

    fancybasename = "pb.Connector"
    showAttributes = ['username', 'password', 'endpointString']
    compare_attrs = showAttributes

    def __init__(self, username, password, endpointString):
        self.username = username
        self.password = password
        self.endpointString = endpointString

    def setServiceParent(self, parent):
        self.master = parent.master
        Service.setServiceParent(self, parent)

    def startService(self):
        self._regstration = self.master.pbmanager.register(
                self.endpointString, self.username, self.password, self._getPerspective)

    def stopService(self):
        return self._registration.unregister()


    @defer.inlineCallbacks
    def _getPerspective(self, mind, buildslaveName):
        bslaves = self.master.buildslaves
        log.msg("slave '%s' attaching from %s" % (buildslaveName,
                                        mind.broker.transport.getPeer()))

        # try to use TCP keepalives
        try:
            mind.broker.transport.setTcpKeepAlive(1)
        except Exception:
            log.msg("Can't set TcpKeepAlive")

        conn = Connection(self.master, self.parent, mind)

        # Slave Arbiter
        accepted = yield bslaves.newConnection(conn, buildslaveName)

        # return the Connection as the perspective
        if accepted:
            defer.returnValue(conn)
        else:
            # TODO: return something more useful
            raise RuntimeError("rejecting duplicate slave")


class Connection(pb.Avatar):
    implements(base.IConnection)

    # TODO: configure keepalive_interval in c['protocols']['pb']['keepalive_interval']
    keepalive_timer = None
    keepalive_interval = 3600
    info = None

    def __init__(self, master, buildslave, mind):
        self._master = master
        self._buildslave = buildslave
        self._mind = mind
        self._builders = {}

    # methods called by the PBManager

    @defer.inlineCallbacks
    def attached(self, mind):
        self._startKeepaliveTimer()

        yield self.print(message="attached")

        self._info = yield self._getSlaveInfo()
        log.msg("Got slaveinfo from '%s'" % 'FIXME: buildslaveName')

        yield self._buildslave.attached(self, self._info)
        defer.returnValue(self)

    def detached(self, mind):
        self._stopKeepaliveTimer()
        self._mind = None
        self._buildslave.detached()


    # disconnection handling

    def loseConnection(self):
        self._stopKeepaliveTimer()
        self._mind.broker.transport.loseConnection()

    # keepalive handling

    def _doKeepalive(self):
        return self._mind.callRemote('print', message="keepalive")

    def _stopKeepaliveTimer(self):
        if self._keepalive_timer and self._keepalive_timer.active():
            self._keepalive_timer.cancel()
            self._keepalive_timer = None

    def _startKeepaliveTimer(self):
        assert self._keepalive_interval
        self._keepalive_timer = reactor.callLater(self._keepalive_interval,
            self._doKeepalive)

    # methods to send messages to the slave

    def print(self, message):
        return self._mind.callRemote('print', message=message)

    @defer.inlineCallbacks
    def _getSlaveInfo(self):
        info = {}
        try:
            info = yield self._mind.callRemote('getSlaveInfo')
        except pb.NoSuchMethod:
            log.msg("BuildSlave.getSlaveInfo is unavailable - ignoring")

        try:
            info["slave_commands"] = yield self._mind.callRemote('getCommands')
        except pb.NoSuchMethod:
            log.msg("BuildSlave.getCommands is unavailable - ignoring")

        try:
            info["version"] = yield self._mind.callRemote('getVersion')
        except pb.NoSuchMethod:
            log.msg("BuildSlave.getVersion is unavailable - ignoring")

        defer.returnValue(info)


    def setBuilderList(self, builderNames):
        if set(builderNames) == set(self._builders.keys()):
            return

        def saveBuilders(builders):
            self._builders = {}
            for name, builder in builders.iteritems():
                self._builders[name] = Builder(builder)
            self._builders = builders
            return builders

        d = self._mind.callRemote('setBuilderList', builderNames)
        d.addCallback(saveBuilders)
        return d


    def getBuilder(self, builderName):
        return self._builders[builderName]


    @defer.inlineCallbacks
    def shutdown(self):
        # First, try the "new" way - calling our own remote's shutdown
        # method. The method was only added in 0.8.3, so ignore NoSuchMethod
        # failures.
        def new_way():
            d = self._mind.callRemote('shutdown')
            d.addCallback(lambda _ : True) # successful shutdown request
            def check_nsm(f):
                f.trap(pb.NoSuchMethod)
                return False # fall through to the old way
            d.addErrback(check_nsm)
            def check_connlost(f):
                f.trap(pb.PBConnectionLost)
                return True # the slave is gone, so call it finished
            d.addErrback(check_connlost)
            return d

        if (yield new_way()):
            return # done!

        # Now, the old way. Look for a builder with a remote reference to the
        # client side slave. If we can find one, then call "shutdown" on the
        # remote builder, which will cause the slave buildbot process to exit.
        def old_way():
            d = None
            for b in self._builders.values():
                d = b._remote.callRemote("shutdown")
                break

            if d:
                name = self._buildslave.slavename
                log.msg("Shutting down (old) slave: %s" % name)
                # The remote shutdown call will not complete successfully since
                # the buildbot process exits almost immediately after getting
                # the shutdown request.
                # Here we look at the reason why the remote call failed, and if
                # it's because the connection was lost, that means the slave
                # shutdown as expected.
                def _errback(why):
                    if why.check(pb.PBConnectionLost):
                        log.msg("Lost connection to %s" % name)
                    else:
                        log.err("Unexpected error when trying to shutdown %s"
                                                                        % name)
                d.addErrback(_errback)
                return d
            log.err("Couldn't find remote builder to shut down slave")
            return defer.succeed(None)
        yield old_way()


    def disconnect(self):
        transport = self.broker.transport
        # this is the polite way to request that a socket be closed
        try:
            d = transport.abortConnection()
        except NameError: # For twisted 11.0
            d = transport.loseConnection()
        log.msg("waiting for slave to finish disconnecting")

        return d



    # perspective methods called by the slave

    def perspective_keepalive(self):
        self._buildslave.messageReceivedFromSlave()

    def perspective_shutdown(self):
        self._buildslave.messageReceivedFromSlave()
        self._buildslave.shutdownRequested()

class Builder(object):

    def __init__(self, remote):
        self._remote = remote

    def startBuild(self, builderName):
        d = self._remote.callRemote('startBuild')
        d.addCallback(lambda _: Build(self._remote))
        return d

class Build(object):

    def __init__(self, remote):
        self._remote = remote

    def startCommand(self, remoteCommand, commandName, args):
        command = Command(remoteCommand)
        commandID = command._id
        return self._remote.callRemote('startCommand',
            command, commandID, commandName, args
        )

class Command(pb.Referenceable):

    _getNextID = staticmethod(count().next)

    def __init__(self, remote):
        self._remote = remote
        self._id = self._getNextID()

    def interruptCommand(self, commandId, why):
        return self._remote.callRemote("interruptCommand",
            self._id, why)
