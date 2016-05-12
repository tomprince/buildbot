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

import os
from glob import glob
import shutil
from subprocess import call
from subprocess import check_call
from textwrap import dedent

from twisted.trial import unittest


class BuildbotWWWPkg(unittest.TestCase):
    pkgName = "buildbot_www"
    pkgPaths = ["www", "base"]
    epName = "base"

    loadTestScript = dedent("""
        import pkg_resources
        apps = {}
        for ep in pkg_resources.iter_entry_points('buildbot.www'):
            apps[ep.name] = ep.load()

        assert("scripts.js" in apps["%(epName)s"].resource.listNames())
        assert(apps["%(epName)s"].version.startswith("0."))
        assert(apps["%(epName)s"].description is not None)
        print apps["%(epName)s"]
        """)

    def rmtree(self, d):
        if os.path.isdir(d):
            shutil.rmtree(d)

    def setUp(self):
        self.virtualenv = os.path.abspath(self.mktemp())
        check_call(['virtualenv', self.virtualenv])
        self.python_path = os.path.join(self.virtualenv, 'bin', 'python')
        call([self.python_path, "-m", "pip", "install", os.path.dirname(__file__), "mock"])

        package_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", *self.pkgPaths))
        self.path = os.path.abspath(self.mktemp())
        shutil.copytree(package_path, self.path)
        self.rmtree(os.path.join(self.path, "build"))
        self.rmtree(os.path.join(self.path, "dist"))
        self.rmtree(os.path.join(self.path, "static"))

    def run_setup(self, cmd):
        check_call([self.python_path, "setup.py", cmd], cwd=self.path)

    def check_correct_installation(self):
        # assert we can import buildbot_www
        # and that it has an endpoint with resource containing file "script.js"
        check_call([
            self.python_path, '-c', self.loadTestScript % dict(epName=self.epName)])

    def test_install(self):
        self.run_setup("install")
        self.check_correct_installation()

    def test_wheel(self):
        self.run_setup("bdist_wheel")
        check_call([self.python_path, "-m", "pip", "install"] + glob("dist/*.whl"), cwd=self.path)
        self.check_correct_installation()

    def test_egg(self):
        self.run_setup("bdist_egg")
        # egg installation is not supported by pip, so we use easy_install
        check_call([self.python_path, "-m", "easy_install", "install"] + glob("dist/*.egg"), cwd=self.path)
        self.check_correct_installation()

    def test_develop(self):
        self.run_setup("develop")
        self.check_correct_installation()

    def test_develop_via_pip(self):
        check_call([self.python_path, "-m", "pip", "install", '-e', '.'], cwd=self.path)
        self.check_correct_installation()

    def test_sdist(self):
        self.run_setup("sdist")
        check_call([self.python_path, "-m", "pip", "install"] + glob('dist/*.tar.gz'), cwd=self.path)
        self.check_correct_installation()


class BuildbotMDWWWPkg(BuildbotWWWPkg):
    pkgPaths = ["www", "md_base"]


class BuildbotConsolePkg(BuildbotWWWPkg):
    pkgName = "buildbot-console-view"
    pkgPaths = ["www", "console_view"]
    epName = "console_view"


class BuildbotWaterfallPkg(BuildbotWWWPkg):
    pkgName = "buildbot-waterfall-view"
    pkgPaths = ["www", "waterfall_view"]
    epName = "waterfall_view"


class BuildbotCodeparameterPkg(BuildbotWWWPkg):
    pkgName = "buildbot-codeparameter"
    pkgPaths = ["www", "codeparameter"]
    epName = "codeparameter"
