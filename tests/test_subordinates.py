#
# foris-controller-subordinates-module
# Copyright (C) 2020 CZ.NIC, z.s.p.o. (http://www.nic.cz/)
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
    backend,
    infrastructure,
    only_backends,
    only_message_buses,
    uci_configs_init,
    init_script_result,
    file_root_init,
    network_restart_command,
    UCI_CONFIG_DIR_PATH,
    FILE_ROOT_PATH,
)
from foris_controller_testtools.utils import get_uci_module, check_service_result


def prepare_subordinate_token(controller_id: str, ip_address: str) -> str:
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
        add_to_tar(
            tar,
            f"some_name/conf.json",
            json.dumps(
                {
                    "name": "some_name",
                    "hostname": "localhost",
                    "ipv4_ips": {"lan": [ip_address], "wan": []},
                    "dhcp_names": [],
                    "port": 11884,
                    "device_id": controller_id,
                }
            ),
        )

    new_file.seek(0)
    final_content = new_file.read()
    new_file.close()

    return base64.b64encode(final_content).decode()


@pytest.mark.only_message_buses(["unix-socket", "ubus"])
def test_complex_subordinates_unsupported(uci_configs_init, infrastructure, file_root_init):
    res = infrastructure.process_message(
        {"module": "subordinates", "action": "list", "kind": "request"}
    )
    assert res == {
        "module": "subordinates",
        "action": "list",
        "kind": "reply",
        "data": {"subordinates": []},
    }
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_sub",
            "kind": "request",
            "data": {"token": prepare_subordinate_token("1122334455667788", "1.1.1.1")},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": False},
    }
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "del",
            "kind": "request",
            "data": {"controller_id": "1122334455667788"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": False},
    }
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "set_enabled",
            "kind": "request",
            "data": {"controller_id": "1122334455667788", "enabled": False},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": False},
    }
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "update_sub",
            "kind": "request",
            "data": {"controller_id": "1122334455667788", "options": {"custom_name": "nice name"}},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "update_sub",
        "kind": "reply",
        "data": {"result": False},
    }


@pytest.mark.only_message_buses(["mqtt"])
def test_complex_subordinates(uci_configs_init, infrastructure, file_root_init, init_script_result):
    def in_list(controller_id):
        res = infrastructure.process_message(
            {"module": "subordinates", "action": "list", "kind": "request"}
        )
        assert "subordinates" in res["data"]
        output = None
        for record in res["data"]["subordinates"]:
            assert set(record.keys()) == {"options", "controller_id", "enabled", "subsubordinates"}
            if record["controller_id"] == controller_id:
                output = record
        return output

    assert None is in_list("1122334455667788")
    token = prepare_subordinate_token("1122334455667788", "2.2.2.2")

    filters = [("subordinates", "add_sub")]
    notifications = infrastructure.get_notifications(filters=filters)

    # add
    res = infrastructure.process_message(
        {"module": "subordinates", "action": "add_sub", "kind": "request", "data": {"token": token}}
    )
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": True, "controller_id": "1122334455667788"},
    }
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "notification",
        "data": {"controller_id": "1122334455667788"},
    }
    assert in_list("1122334455667788") == {
        "controller_id": "1122334455667788",
        "enabled": True,
        "options": {"custom_name": "", "ip_address": "2.2.2.2"},
        "subsubordinates": [],
    }

    res = infrastructure.process_message(
        {"module": "subordinates", "action": "add_sub", "kind": "request", "data": {"token": token}}
    )
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": False},
    }
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True, expected_found=False)

    assert in_list("1122334455667788") == {
        "controller_id": "1122334455667788",
        "enabled": True,
        "options": {"custom_name": "", "ip_address": "2.2.2.2"},
        "subsubordinates": [],
    }

    # add2
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_sub",
            "kind": "request",
            "data": {"token": prepare_subordinate_token("8877665544332211", "3.3.3.3")},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": True, "controller_id": "8877665544332211"},
    }
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "notification",
        "data": {"controller_id": "8877665544332211"},
    }
    assert in_list("8877665544332211") == {
        "controller_id": "8877665544332211",
        "enabled": True,
        "options": {"custom_name": "", "ip_address": "3.3.3.3"},
        "subsubordinates": [],
    }

    # set
    filters = [("subordinates", "set_enabled")]
    notifications = infrastructure.get_notifications(filters=filters)
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "set_enabled",
            "kind": "request",
            "data": {"controller_id": "1122334455667788", "enabled": False},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": True},
    }
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True)
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "notification",
        "data": {"controller_id": "1122334455667788", "enabled": False},
    }
    assert in_list("1122334455667788") == {
        "controller_id": "1122334455667788",
        "enabled": False,
        "options": {"custom_name": "", "ip_address": "2.2.2.2"},
        "subsubordinates": [],
    }
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "set_enabled",
            "kind": "request",
            "data": {"controller_id": "2222334455667788", "enabled": True},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": False},
    }
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True, expected_found=False)

    # del
    filters = [("subordinates", "del")]
    notifications = infrastructure.get_notifications(filters=filters)
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "del",
            "kind": "request",
            "data": {"controller_id": "1122334455667788"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": True},
    }
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True)
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "del",
        "kind": "notification",
        "data": {"controller_id": "1122334455667788"},
    }
    assert None is in_list("1122334455667788")

    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "del",
            "kind": "request",
            "data": {"controller_id": "1122334455667788"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": False},
    }
    if infrastructure.backend_name == "openwrt":
        check_service_result("fosquitto", "restart", passed=True, expected_found=False)
    assert None is in_list("1122334455667788")


@pytest.mark.only_backends(["openwrt"])
@pytest.mark.only_message_buses(["mqtt"])
def test_complex_subordinates_openwrt(
    uci_configs_init, infrastructure, file_root_init, init_script_result
):
    uci = get_uci_module(infrastructure.name)
    token = prepare_subordinate_token("1122334455667788", "4.4.4.4")
    res = infrastructure.process_message(
        {"module": "subordinates", "action": "add_sub", "kind": "request", "data": {"token": token}}
    )
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": True, "controller_id": "1122334455667788"},
    }

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    assert uci.get_option_named(data, "fosquitto", "1122334455667788", "address", "") == "4.4.4.4"
    assert uci.get_option_named(data, "fosquitto", "1122334455667788", "port", "") == "11884"
    assert uci.parse_bool(
        uci.get_option_named(data, "fosquitto", "1122334455667788", "enabled", "")
    )

    subordinate_root = (
        pathlib.Path(FILE_ROOT_PATH) / "etc" / "fosquitto" / "bridges" / "1122334455667788"
    )
    assert subordinate_root.exists()
    assert (subordinate_root / "conf.json").exists()
    assert (subordinate_root / "token.crt").exists()
    assert (subordinate_root / "token.key").exists()
    assert (subordinate_root / "ca.crt").exists()

    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "set_enabled",
            "kind": "request",
            "data": {"controller_id": "1122334455667788", "enabled": False},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": True},
    }

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    assert not uci.parse_bool(
        uci.get_option_named(data, "fosquitto", "1122334455667788", "enabled", "")
    )

    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "del",
            "kind": "request",
            "data": {"controller_id": "1122334455667788"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": True},
    }

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    with pytest.raises(uci.UciRecordNotFound):
        uci.get_section(data, "fosquitto", "1122334455667788")
    assert not subordinate_root.exists()


@pytest.mark.only_message_buses(["unix-socket", "ubus"])
def test_complex_subsubordinates_unsupported(uci_configs_init, infrastructure, file_root_init):
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_subsub",
            "kind": "request",
            "data": {"controller_id": "8877665544332211", "via": "1122334455667788"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": False},
    }
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "set_enabled",
            "kind": "request",
            "data": {"controller_id": "8877665544332211", "enabled": False},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": False},
    }
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "del",
            "kind": "request",
            "data": {"controller_id": "8877665544332211"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": False},
    }


@pytest.mark.only_message_buses(["mqtt"])
def test_complex_subsubordinates(
    uci_configs_init, infrastructure, file_root_init, init_script_result
):
    # prepare subordinates
    def add_subordinate(controller_id, ip_address, result):
        token = prepare_subordinate_token(controller_id, ip_address)
        res = infrastructure.process_message(
            {
                "module": "subordinates",
                "action": "add_sub",
                "kind": "request",
                "data": {"token": token},
            }
        )
        if result:
            assert res == {
                "module": "subordinates",
                "action": "add_sub",
                "kind": "reply",
                "data": {"result": True, "controller_id": controller_id},
            }
        else:
            assert res == {
                "module": "subordinates",
                "action": "add_sub",
                "kind": "reply",
                "data": {"result": False},
            }

    add_subordinate("8888888888888888", "5.5.5.5", True)
    add_subordinate("7777777777777777", "6.6.6.6", True)

    def check_under(parent, child):
        res = infrastructure.process_message(
            {"module": "subordinates", "action": "list", "kind": "request"}
        )
        assert 1 == len(
            [
                e
                for record in res["data"]["subordinates"]
                if record["controller_id"] == parent
                for e in record["subsubordinates"]
                if e["controller_id"] == child
            ]
        )

    filters = [("subordinates", "add_subsub")]
    notifications = infrastructure.get_notifications(filters=filters)
    # add subsub success
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_subsub",
            "kind": "request",
            "data": {"controller_id": "6666666666666666", "via": "8888888888888888"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": True},
    }
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "notification",
        "data": {"controller_id": "6666666666666666", "via": "8888888888888888"},
    }
    check_under("8888888888888888", "6666666666666666")

    # already added
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_subsub",
            "kind": "request",
            "data": {"controller_id": "6666666666666666", "via": "7777777777777777"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": False},
    }

    # add subsub with same controller_id as sub
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_subsub",
            "kind": "request",
            "data": {"controller_id": "7777777777777777", "via": "8888888888888888"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": False},
    }

    # add subsub when via subsub
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_subsub",
            "kind": "request",
            "data": {"controller_id": "5555555555555555", "via": "6666666666666666"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": False},
    }

    # add subsub when via non existing
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_subsub",
            "kind": "request",
            "data": {"controller_id": "5555555555555555", "via": "1111111111111111"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": False},
    }

    # add sub but subsub already exists
    add_subordinate("6666666666666666", "7.7.7.7", False)

    filters = [("subordinates", "set_enabled")]
    notifications = infrastructure.get_notifications(filters=filters)
    # set subsub success
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "set_enabled",
            "kind": "request",
            "data": {"controller_id": "6666666666666666", "enabled": False},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": True},
    }
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "notification",
        "data": {"controller_id": "6666666666666666", "enabled": False},
    }
    res = infrastructure.process_message(
        {"module": "subordinates", "action": "list", "kind": "request"}
    )
    assert "subordinates" in res["data"]
    for record in res["data"]["subordinates"]:
        if record["controller_id"] == "8888888888888888":
            assert record["subsubordinates"][0] == {
                "controller_id": "6666666666666666",
                "enabled": False,
                "options": {"custom_name": ""},
            }

    filters = [("subordinates", "del")]
    notifications = infrastructure.get_notifications(filters=filters)
    # del subsub success
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "del",
            "kind": "request",
            "data": {"controller_id": "6666666666666666"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": True},
    }
    notifications = infrastructure.get_notifications(notifications, filters=filters)
    assert notifications[-1] == {
        "module": "subordinates",
        "action": "del",
        "kind": "notification",
        "data": {"controller_id": "6666666666666666"},
    }


@pytest.mark.only_backends(["openwrt"])
@pytest.mark.only_message_buses(["mqtt"])
def test_complex_subsubordinates_openwrt(
    uci_configs_init, infrastructure, file_root_init, init_script_result
):
    uci = get_uci_module(infrastructure.name)

    def add_subordinate(controller_id, ip_address):
        token = prepare_subordinate_token(controller_id, ip_address)
        res = infrastructure.process_message(
            {
                "module": "subordinates",
                "action": "add_sub",
                "kind": "request",
                "data": {"token": token},
            }
        )
        assert res == {
            "module": "subordinates",
            "action": "add_sub",
            "kind": "reply",
            "data": {"result": True, "controller_id": controller_id},
        }
        check_service_result("fosquitto", "restart", passed=True)

    add_subordinate("4444444444444444", "8.8.8.8")
    add_subordinate("5555555555555555", "9.9.9.9")

    # add subsub
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_subsub",
            "kind": "request",
            "data": {"controller_id": "2222222222222222", "via": "4444444444444444"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": True},
    }
    check_service_result("fosquitto", "restart", passed=True)

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    assert uci.get_option_named(data, "fosquitto", "2222222222222222", "via") == "4444444444444444"

    # set subsub
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "set_enabled",
            "kind": "request",
            "data": {"controller_id": "2222222222222222", "enabled": False},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "set_enabled",
        "kind": "reply",
        "data": {"result": True},
    }
    check_service_result("fosquitto", "restart", passed=True)

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    assert uci.get_option_named(data, "fosquitto", "2222222222222222", "via") == "4444444444444444"
    assert not uci.parse_bool(
        uci.get_option_named(data, "fosquitto", "2222222222222222", "enabled")
    )

    # del subsub
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "del",
            "kind": "request",
            "data": {"controller_id": "2222222222222222"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "del",
        "kind": "reply",
        "data": {"result": True},
    }
    check_service_result("fosquitto", "restart", passed=True)

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()

    with pytest.raises(uci.UciRecordNotFound):
        uci.get_section(data, "fosquitto", "2222222222222222")

    # del section and all its subsections
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_subsub",
            "kind": "request",
            "data": {"controller_id": "1111111111111111", "via": "4444444444444444"},
        }
    )
    assert res["data"]["result"]
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "del",
            "kind": "request",
            "data": {"controller_id": "4444444444444444"},
        }
    )
    assert res["data"]["result"]

    with pytest.raises(uci.UciRecordNotFound):
        uci.get_section(data, "fosquitto", "1111111111111111")


@pytest.mark.only_message_buses(["mqtt"])
def test_complex_subordinates_options(
    uci_configs_init, infrastructure, file_root_init, init_script_result
):
    def get_options(controller_id):
        res = infrastructure.process_message(
            {"module": "subordinates", "action": "list", "kind": "request"}
        )
        assert "subordinates" in res["data"]
        for record in res["data"]["subordinates"]:
            if record["controller_id"] == controller_id:
                return record["options"]

        for sub in res["data"]["subordinates"]:
            for subsub in sub["subsubordinates"]:
                if subsub["controller_id"] == controller_id:
                    return subsub["options"]
        return None

    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_sub",
            "kind": "request",
            "data": {"token": prepare_subordinate_token("1234567887654321", "10.10.10.10")},
        }
    )
    assert res["data"]["result"]
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_subsub",
            "kind": "request",
            "data": {"controller_id": "8765432112345678", "via": "1234567887654321"},
        }
    )
    assert res["data"]["result"]

    assert get_options("1234567887654321") == {"custom_name": "", "ip_address": "10.10.10.10"}
    assert get_options("8765432112345678") == {"custom_name": ""}

    # sub
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "update_sub",
            "kind": "request",
            "data": {"controller_id": "1234567887654321", "options": {"custom_name": "sub1"},},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "update_sub",
        "kind": "reply",
        "data": {"result": True},
    }
    assert get_options("1234567887654321") == {"custom_name": "sub1", "ip_address": "10.10.10.10"}

    # subsub
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "update_subsub",
            "kind": "request",
            "data": {"controller_id": "8765432112345678", "options": {"custom_name": "subsub1"},},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "update_subsub",
        "kind": "reply",
        "data": {"result": True},
    }
    assert get_options("8765432112345678") == {"custom_name": "subsub1"}

    # non-exsiting
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "update_sub",
            "kind": "request",
            "data": {"controller_id": "7755331188664422", "options": {"custom_name": "sub2"},},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "update_sub",
        "kind": "reply",
        "data": {"result": False},
    }
    assert get_options("7755331188664422") is None
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "update_subsub",
            "kind": "request",
            "data": {"controller_id": "2244668811335577", "options": {"custom_name": "subsub2"},},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "update_subsub",
        "kind": "reply",
        "data": {"result": False},
    }
    assert get_options("2244668811335577") is None


@pytest.mark.only_backends(["openwrt"])
@pytest.mark.only_message_buses(["mqtt"])
def test_complex_subordinates_options_openwrt(
    uci_configs_init, infrastructure, file_root_init, init_script_result
):
    uci = get_uci_module(infrastructure.name)

    token = prepare_subordinate_token("3344112266779988", "11.11.11.11")
    res = infrastructure.process_message(
        {"module": "subordinates", "action": "add_sub", "kind": "request", "data": {"token": token}}
    )
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": True, "controller_id": "3344112266779988"},
    }

    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "update_sub",
            "kind": "request",
            "data": {"controller_id": "3344112266779988", "options": {"custom_name": "sub3"},},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "update_sub",
        "kind": "reply",
        "data": {"result": True},
    }

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()
    assert (
        uci.get_option_named(
            data, "foris-controller-subordinates", "3344112266779988", "custom_name", ""
        )
        == "sub3"
    )
    assert (
        uci.get_option_named(data, "fosquitto", "3344112266779988", "address", "") == "11.11.11.11"
    )

    # add subsub
    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "add_subsub",
            "kind": "request",
            "data": {"controller_id": "8899776622114433", "via": "3344112266779988"},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "add_subsub",
        "kind": "reply",
        "data": {"result": True},
    }

    res = infrastructure.process_message(
        {
            "module": "subordinates",
            "action": "update_subsub",
            "kind": "request",
            "data": {"controller_id": "8899776622114433", "options": {"custom_name": "subsub3"}},
        }
    )
    assert res == {
        "module": "subordinates",
        "action": "update_subsub",
        "kind": "reply",
        "data": {"result": True},
    }

    with uci.UciBackend(UCI_CONFIG_DIR_PATH) as backend:
        data = backend.read()
    assert (
        uci.get_option_named(
            data, "foris-controller-subordinates", "8899776622114433", "custom_name", ""
        )
        == "subsub3"
    )


@pytest.mark.only_message_buses(["mqtt"])
def test_netboot_token(uci_configs_init, infrastructure, file_root_init, init_script_result):
    # test token which was generate net accepting client for netboot
    token = """\
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\
"""

    res = infrastructure.process_message(
        {"module": "subordinates", "action": "add_sub", "kind": "request", "data": {"token": token}}
    )
    assert res == {
        "module": "subordinates",
        "action": "add_sub",
        "kind": "reply",
        "data": {"result": True, "controller_id": "0000000D30000165"},
    }
