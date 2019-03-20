#
# foris-controller-subordinates-module
# Copyright (C) 2019 CZ.NIC, z.s.p.o. (http://www.nic.cz/)
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA
#

import pytest
import os

# load common fixtures
from foris_controller_testtools.fixtures import (
    uci_config_default_path, cmdline_script_root,
    controller_modules, extra_module_paths, message_bus, backend
)



@pytest.fixture(scope="session")
def uci_config_default_path():
    return os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "uci_configs"
    )


@pytest.fixture(scope="session")
def cmdline_script_root():
    return os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "test_root"
    )


@pytest.fixture(scope="module")
def controller_modules():
    return ["remote", "subordinates"]


def pytest_addoption(parser):
    parser.addoption(
        "--backend", action="append",
        default=[],
        help=("Set test backend here. available values = (mock, openwrt)")
    )
    parser.addoption(
        "--message-bus", action="append",
        default=[],
        help=("Set test bus here. available values = (unix-socket, ubus, mqtt)")
    )
    parser.addoption(
        "--debug-output", action="store_true",
        default=False,
        help=("Whether show output of foris-controller cmd")
    )


@pytest.fixture(scope="session")
def file_root():
    # default src dirctory will be the same as for the scripts  (could be override later)
    return os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "test_root"
    )


def pytest_generate_tests(metafunc):
    if 'backend' in metafunc.fixturenames:
        backend = metafunc.config.option.backend
        if not backend:
            backend = ['openwrt']
        metafunc.parametrize("backend_param", backend, scope='module')

    if 'message_bus' in metafunc.fixturenames:
        message_bus = metafunc.config.option.message_bus
        if not message_bus:
            message_bus = ['ubus']
        metafunc.parametrize("message_bus_param", message_bus, scope='module')
