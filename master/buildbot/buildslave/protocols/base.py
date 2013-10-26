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

from zope.interface import Interface


class IConnection(Interface):

    # methods to send messages to the slave

    def print(message):
        """
        Instruct the slave to log a message.
        """

    def setBuilderList(builderNames):
        """
        Provide list of configured builders to the slave.
        """

    def getBuilder(builder):
        """
        """

    def shutdown():
        """
        Request that the slave shutdown.
        """

    def disconnect():
        """
        Forcibly disconnect the slave.
        """

class IBuilder(Interface):



    def startBuild(self):
        """
        """


class IBuild(Interface):
    def startCommand(remoteCommand, commandName, args):
        """
        """

class ICommand(Interface):
    def interrupt(self, why):
        """
        Interrupt a running command.
        """
