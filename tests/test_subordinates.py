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

import base64
import json
import pytest
import tarfile
import pathlib

from io import BytesIO


from foris_controller_testtools.fixtures import (
    backend, infrastructure, ubusd_test, only_backends, only_message_buses, uci_configs_init,
    init_script_result, lock_backend, file_root_init, network_restart_command,
    UCI_CONFIG_DIR_PATH, mosquitto_test, start_buses, FILE_ROOT_PATH
)
from foris_controller_testtools.utils import (
    get_uci_module, check_service_result
)


def prepare_subordinate_token(controller_id):
    def add_to_tar(tar, name, content):
        data = content.encode()
        fake_file = BytesIO(data)
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        info.mode = 0o0600
        fake_file.seek(0)
        tar.addfile(info, fake_file)
        fake_file.close()

    new_file = BytesIO()
    with tarfile.open(fileobj=new_file, mode="w:gz") as tar:
        add_to_tar(tar, f"some_name/token.crt", "token cert content")
        add_to_tar(tar, f"some_name/token.key", "token key content")
        add_to_tar(tar, f"some_name/ca.crt", "ca cert content")
        add_to_tar(tar, f"some_name/conf.json", json.dumps({
            "name": "some_name",
            "hostname": "localhost",
            "ipv4_ips": {"lan": ["123.123.123.123"], "wan": []},
            "dhcp_names": [],
            "port": 11884,
            "device_id": controller_id,
        }))

    new_file.seek(0)
    final_content = new_file.read()
    new_file.close()

    return base64.b64encode(final_content).decode()


@pytest.mark.only_message_buses(['unix-socket', 'ubus'])
def test_complex_subordinates_unsupported(uci_configs_init, infrastructure, start_buses, file_root_init):
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "list",
        "kind": "request",
    })
    assert res == {
        "module": "subordinates",
        "action": "list",
        "kind": "reply",
        "data": {"subordinates": []}
    }
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_sub",
        "kind": "request",
        "data": {
            "token": prepare_subordinate_token("1122334455667788"),
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": False}
    }
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "del",
        "kind": "request",
        "data": {
            "controller_id": "1122334455667788",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": False}
    }
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "request",
        "data": {
            "controller_id": "1122334455667788", "enabled": False,
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": False}
    }
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "update_sub",
        "kind": "request",
        "data": {
            "controller_id": "1122334455667788", "options": {"custom_name": "nice name"}
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "update_sub",
        "kind": "reply",
        "data": {"result": False}
    }


@pytest.mark.only_message_buses(['mqtt'])
def test_complex_subordinates(
    uci_configs_init, infrastructure, start_buses, file_root_init, init_script_result
):
    def in_list(controller_id):
        res = infrastructure.process_message({
            "module": "subordinates",
            "action": "list",
            "kind": "request",
        })
        assert "subordinates" in res["data"]
        output = None
        for record in res["data"]["subordinates"]:
            assert set(record.keys()) == {"options", "controller_id", "enabled", "subsubordinates"}
            if record["controller_id"] == controller_id:
                output = record
        return output

    assert None is in_list("1122334455667788")
    token = prepare_subordinate_token("1122334455667788")

    filters = [("subordinates", "add_sub")]
    notifications = infrastructure.get_notifications(filters=filters)

    # add
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_sub",
        "kind": "request",
        "data": {
            "token": token,
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": True, "controller_id": "1122334455667788"}
    }
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "notification",
        "data": {"controller_id": "1122334455667788"}
    }
    assert in_list("1122334455667788") == {
        "controller_id": "1122334455667788", "enabled": True, "options": {"custom_name": ""},
        "subsubordinates": [],
    }

    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_sub",
        "kind": "request",
        "data": {
            "token": token,
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": False}
    }
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True, expected_found=False)

    assert in_list("1122334455667788") == {
        "controller_id": "1122334455667788", "enabled": True, "options": {"custom_name": ""},
        "subsubordinates": [],
    }

    # add2
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_sub",
        "kind": "request",
        "data": {
            "token": prepare_subordinate_token("8877665544332211"),
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": True, "controller_id": "8877665544332211"}
    }
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "notification",
        "data": {"controller_id": "8877665544332211"}
    }
    assert in_list("8877665544332211") == {
        "controller_id": "8877665544332211", "enabled": True, "options": {"custom_name": ""},
        "subsubordinates": [],
    }

    # set
    filters = [("subordinates", "set_enabled")]
    notifications = infrastructure.get_notifications(filters=filters)
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "request",
        "data": {
            "controller_id": "1122334455667788", "enabled": False,
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": True}
    }
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True)
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "notification",
        "data": {"controller_id": "1122334455667788", "enabled": False}
    }
    assert in_list("1122334455667788") == {
        "controller_id": "1122334455667788", "enabled": False, "options": {"custom_name": ""},
        "subsubordinates": [],
    }
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "request",
        "data": {
            "controller_id": "2222334455667788", "enabled": True,
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": False}
    }
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True, expected_found=False)

    # del
    filters = [("subordinates", "del")]
    notifications = infrastructure.get_notifications(filters=filters)
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "del",
        "kind": "request",
        "data": {
            "controller_id": "1122334455667788",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": True}
    }
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True)
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "del",
        "kind": "notification",
        "data": {"controller_id": "1122334455667788"}
    }
    assert None is in_list("1122334455667788")

    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "del",
        "kind": "request",
        "data": {
            "controller_id": "1122334455667788",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": False}
    }
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True, expected_found=False)
    assert None is in_list("1122334455667788")


@pytest.mark.only_backends(['openwrt'])
@pytest.mark.only_message_buses(['mqtt'])
def test_complex_subordinates_openwrt(
    uci_configs_init, infrastructure, start_buses, file_root_init, init_script_result, lock_backend
):
    uci = get_uci_module(lock_backend)
    token = prepare_subordinate_token("1122334455667788")
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_sub",
        "kind": "request",
        "data": {
            "token": token,
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": True, "controller_id": "1122334455667788"}
    }

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    assert uci.get_option_named(
        data, "fosquitto", "1122334455667788", "address", "") == "123.123.123.123"
    assert uci.get_option_named(
        data, "fosquitto", "1122334455667788", "port", "") == "11884"
    assert uci.parse_bool(uci.get_option_named(
        data, "fosquitto", "1122334455667788", "enabled", ""))

    subordinate_root = \
        pathlib.Path(FILE_ROOT_PATH) / "etc" / "fosquitto" / "bridges" / "1122334455667788"
    assert subordinate_root.exists()
    assert (subordinate_root / "conf.json").exists()
    assert (subordinate_root / "token.crt").exists()
    assert (subordinate_root / "token.key").exists()
    assert (subordinate_root / "ca.crt").exists()

    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "request",
        "data": {
            "controller_id": "1122334455667788",
            "enabled": False,
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": True}
    }

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    assert not uci.parse_bool(uci.get_option_named(
        data, "fosquitto", "1122334455667788", "enabled", ""))

    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "del",
        "kind": "request",
        "data": {
            "controller_id": "1122334455667788",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": True}
    }

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    with pytest.raises(uci.UciRecordNotFound):
        uci.get_section(data, "fosquitto", "1122334455667788")
    assert not subordinate_root.exists()


@pytest.mark.only_message_buses(['unix-socket', 'ubus'])
def test_complex_subsubordinates_unsupported(uci_configs_init, infrastructure, start_buses, file_root_init):
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "request",
        "data": {
            "controller_id": "8877665544332211",
            "via": "1122334455667788",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": False}
    }
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "request",
        "data": {
            "controller_id": "8877665544332211",
            "enabled": False
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": False}
    }
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "del",
        "kind": "request",
        "data": {
            "controller_id": "8877665544332211",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": False}
    }


@pytest.mark.only_message_buses(['mqtt'])
def test_complex_subsubordinates(
    uci_configs_init, infrastructure, start_buses, file_root_init, init_script_result, lock_backend
):
    # prepare subordinates
    def add_subordinate(controller_id, result):
        token = prepare_subordinate_token(controller_id)
        res = infrastructure.process_message({
            "module": "subordinates",
            "action": "add_sub",
            "kind": "request",
            "data": {
                "token": token,
            }
        })
        if result:
            assert res == {
                "module": "subordinates",
                "action": "add_sub",
                "kind": "reply",
                "data": {"result": True, "controller_id": controller_id}
            }
        else:
            assert res == {
                    "module": "subordinates",
                    "action": "add_sub",
                    "kind": "reply",
                    "data": {"result": False}
                }
    add_subordinate("8888888888888888", True)
    add_subordinate("7777777777777777", True)

    def check_under(parent, child):
        res = infrastructure.process_message({
            "module": "subordinates",
            "action": "list",
            "kind": "request",
        })
        assert 1 == len([
            e for record in res["data"]["subordinates"] if record["controller_id"] == parent
            for e in record["subsubordinates"] if e["controller_id"] == child
        ])

    filters = [("subordinates", "add_subsub")]
    notifications = infrastructure.get_notifications(filters=filters)
    # add subsub success
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "request",
        "data": {
            "controller_id": "6666666666666666",
            "via": "8888888888888888",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": True}
    }
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "notification",
        "data": {"controller_id": "6666666666666666", "via": "8888888888888888"}
    }
    check_under("8888888888888888", "6666666666666666")

    # already added
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "request",
        "data": {
            "controller_id": "6666666666666666",
            "via": "7777777777777777",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": False}
    }

    # add subsub with same controller_id as sub
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "request",
        "data": {
            "controller_id": "7777777777777777",
            "via": "8888888888888888",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": False}
    }

    # add subsub when via subsub
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "request",
        "data": {
            "controller_id": "5555555555555555",
            "via": "6666666666666666",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": False}
    }

    # add subsub when via non existing
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "request",
        "data": {
            "controller_id": "5555555555555555",
            "via": "1111111111111111",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": False}
    }

    # add sub but subsub already exists
    add_subordinate("6666666666666666", False)

    filters = [("subordinates", "set_enabled")]
    notifications = infrastructure.get_notifications(filters=filters)
    # set subsub success
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "request",
        "data": {
            "controller_id": "6666666666666666",
            "enabled": False,
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": True}
    }
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "notification",
        "data": {
            "controller_id": "6666666666666666",
            "enabled": False,
        }
    }
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "list",
        "kind": "request",
    })
    assert "subordinates" in res["data"]
    for record in res["data"]["subordinates"]:
        if record["controller_id"] == "8888888888888888":
            assert record["subsubordinates"][0] == {
                "controller_id": "6666666666666666",
                "enabled": False,
                "options": {"custom_name": ""}
            }

    filters = [("subordinates", "del")]
    notifications = infrastructure.get_notifications(filters=filters)
    # del subsub success
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "del",
        "kind": "request",
        "data": {
            "controller_id": "6666666666666666",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": True}
    }
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "del",
        "kind": "notification",
        "data": {"controller_id": "6666666666666666"}
    }

@pytest.mark.only_backends(['openwrt'])
@pytest.mark.only_message_buses(['mqtt'])
def test_complex_subsubordinates_openwrt(
    uci_configs_init, infrastructure, start_buses, file_root_init, init_script_result, lock_backend
):
    uci = get_uci_module(lock_backend)

    def add_subordinate(controller_id):
        token = prepare_subordinate_token(controller_id)
        res = infrastructure.process_message({
            "module": "subordinates",
            "action": "add_sub",
            "kind": "request",
            "data": {
                "token": token,
            }
        })
        assert res == {
            "module": "subordinates",
            "action": "add_sub",
            "kind": "reply",
            "data": {"result": True, "controller_id": controller_id}
        }
        check_service_result("fosquitto", "restart", passed=True)

    add_subordinate("4444444444444444")
    add_subordinate("5555555555555555")

    # add subsub
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "request",
        "data": {
            "controller_id": "2222222222222222",
            "via": "4444444444444444",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": True}
    }
    check_service_result("fosquitto", "restart", passed=True)

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    assert uci.get_option_named(data, "fosquitto", "2222222222222222", "via") == "4444444444444444"

    # set subsub
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "request",
        "data": {
            "controller_id": "2222222222222222",
            "enabled": False
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": True}
    }
    check_service_result("fosquitto", "restart", passed=True)

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    assert uci.get_option_named(data, "fosquitto", "2222222222222222", "via") == "4444444444444444"
    assert not uci.parse_bool(
        uci.get_option_named(data, "fosquitto", "2222222222222222", "enabled"))

    # del subsub
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "del",
        "kind": "request",
        "data": {
            "controller_id": "2222222222222222",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": True}
    }
    check_service_result("fosquitto", "restart", passed=True)

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    with pytest.raises(uci.UciRecordNotFound):
        uci.get_section(data, "fosquitto", "2222222222222222")

    # del section and all its subsections
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "request",
        "data": {
            "controller_id": "1111111111111111",
            "via": "4444444444444444",
        }
    })
    assert res["data"]["result"]
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "del",
        "kind": "request",
        "data": {
            "controller_id": "4444444444444444",
        }
    })
    assert res["data"]["result"]

    with pytest.raises(uci.UciRecordNotFound):
        uci.get_section(data, "fosquitto", "1111111111111111")


@pytest.mark.only_message_buses(['mqtt'])
def test_complex_subordinates_options(
    uci_configs_init, infrastructure, start_buses, file_root_init, init_script_result
):
    def get_options(controller_id):
        res = infrastructure.process_message({
            "module": "subordinates",
            "action": "list",
            "kind": "request",
        })
        assert "subordinates" in res["data"]
        for record in res["data"]["subordinates"]:
            if record["controller_id"] == controller_id:
                return record["options"]

        for sub in res["data"]["subordinates"]:
            for subsub in sub["subsubordinates"]:
                if subsub["controller_id"] == controller_id:
                    return subsub["options"]
        return None

    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_sub",
        "kind": "request",
        "data": {
            "token": prepare_subordinate_token("1234567887654321"),
        }
    })
    assert res["data"]["result"]
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "request",
        "data": {
            "controller_id": "8765432112345678",
            "via": "1234567887654321",
        }
    })
    assert res["data"]["result"]

    assert get_options("1234567887654321") == {"custom_name": ""}
    assert get_options("8765432112345678") == {"custom_name": ""}

    # sub
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "update_sub",
        "kind": "request",
        "data": {
            "controller_id": "1234567887654321",
            "options": {"custom_name": "sub1"}
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "update_sub",
        "kind": "reply",
        "data": {
            "result": True,
        }
    }
    assert get_options("1234567887654321") == {"custom_name": "sub1"}

    # subsub
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "update_subsub",
        "kind": "request",
        "data": {
            "controller_id": "8765432112345678",
            "options": {"custom_name": "subsub1"},
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "update_subsub",
        "kind": "reply",
        "data": {
            "result": True,
        }
    }
    assert get_options("8765432112345678") == {"custom_name": "subsub1"}

    # non-exsiting
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "update_sub",
        "kind": "request",
        "data": {
            "controller_id": "7755331188664422",
            "options": {"custom_name": "sub2"},
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "update_sub",
        "kind": "reply",
        "data": {
            "result": False,
        }
    }
    assert get_options("7755331188664422") is None
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "update_subsub",
        "kind": "request",
        "data": {
            "controller_id": "2244668811335577",
            "options": {"custom_name": "subsub2"},
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "update_subsub",
        "kind": "reply",
        "data": {
            "result": False,
        }
    }
    assert get_options("2244668811335577") is None


@pytest.mark.only_backends(['openwrt'])
@pytest.mark.only_message_buses(['mqtt'])
def test_complex_subordinates_options_openwrt(
    uci_configs_init, infrastructure, start_buses, file_root_init, init_script_result, lock_backend
):
    uci = get_uci_module(lock_backend)

    token = prepare_subordinate_token("3344112266779988")
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_sub",
        "kind": "request",
        "data": {
            "token": token,
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": True, "controller_id": "3344112266779988"}
    }

    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "update_sub",
        "kind": "request",
        "data": {
            "controller_id": "3344112266779988",
            "options": {"custom_name": "sub3"},
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "update_sub",
        "kind": "reply",
        "data": {
            "result": True,
        }
    }

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()
    assert uci.get_option_named(
        data, "foris-controller-subordinates", "3344112266779988", "custom_name", "") == "sub3"

    # add subsub
    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "request",
        "data": {
            "controller_id": "8899776622114433",
            "via": "3344112266779988",
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": True}
    }

    res = infrastructure.process_message({
        "module": "subordinates",
        "action": "update_subsub",
        "kind": "request",
        "data": {
            "controller_id": "8899776622114433",
            "options": {"custom_name": "subsub3"},
        }
    })
    assert res == {
        "module": "subordinates",
        "action": "update_subsub",
        "kind": "reply",
        "data": {
            "result": True,
        }
    }

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()
    assert uci.get_option_named(
        data, "foris-controller-subordinates", "8899776622114433", "custom_name", "") == "subsub3"
