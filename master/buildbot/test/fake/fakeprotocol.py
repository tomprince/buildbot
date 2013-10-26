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

from __future__ import print_function

from zope.interface import implements
from twisted.internet import defer
from buildbot.buildslave.protocols import base
from twisted.application.service import Service


class FakeConnector(Service, object):

    def __init__(self):
        self.remoteCalls = []
        self.info = {'slave_commands': [], 'version': '0.8.2'}

    def connect(self):
        self.conn = FakeConnection(self)
        self.parent.attached(self.conn, self.info)

    def detach(self):
        self.parent.detached()


class FakeConnection(object):
    implements(base.IConnection)

    def __init__(self, connector):
        self.connector = connector
        self.builders = {}  # { name : isBusy }

        # users of the fake can add to this as desired

    def print(self, message):
        self.connector.remoteCalls.append(('print', message))
        return defer.succeed(None)

    def setBuilderList(self, builderNames):
        self.connector.remoteCalls.append(('setBuilderList', builderNames[:]))
        self.builders = dict((b, FakeBuilder(self.connector)) for b in builderNames)
        return defer.succeed(None)

    def getBuilder(self, builderName):
        return self.builders[builderName]

    def shutdown(self):
        self.connector.remoteCalls.append(('shutdown',))
        return defer.succeed(None)

class FakeBuilder(object):
    implements(base.IBuilder)

    def __init__(self, connector):
        self.connector = connector

    def startBuild(self):
        self.connector.remoteCalls.append('startBuild')
        return defer.succeed(FakeBuild(self.connector))


class FakeBuild(object):
    implements(base.IBuild)

    def __init__(self, connector):
        self.connector = connector

    def startCommand(self, remoteCommand, commandName, args):
        self.connector.remoteCalls.append(('startCommand', remoteCommand, commandName, args))
        return defer.succeed(FakeCommand(self.connector))


class FakeCommand(object):
    implements(base.ICommand)

    def __init__(self, connector):
        self.connector = connector

    def interrupt(self, why):
        self.connector.remoteCalls.append(('interruptCommand', why))

