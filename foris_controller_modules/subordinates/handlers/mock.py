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

import json
import logging
import base64
import tarfile
import typing

from io import BytesIO

from foris_controller.app import app_info
from foris_controller.handler_base import BaseMockHandler
from foris_controller.utils import logger_wrapper

from .. import Handler

logger = logging.getLogger(__name__)


class MockSubordinatesHandler(Handler, BaseMockHandler):
    subordinates: typing.List[dict] = []

    @logger_wrapper(logger)
    def list_subordinates(self):
        if app_info["bus"] != "mqtt":
            return []
        return MockSubordinatesHandler.subordinates

    @logger_wrapper(logger)
    def add_sub(self, token) -> dict:
        if app_info["bus"] != "mqtt":
            return {"result": False}

        token_data = BytesIO(base64.b64decode(token))
        with tarfile.open(fileobj=token_data, mode="r:gz") as tar:
            config_name = [e for e in tar.getmembers() if e.name.endswith("conf.json")][0]
            with tar.extractfile(config_name) as f:
                device_data = json.load(f)
                controller_id = device_data["device_id"]
                if len(device_data["ipv4_ips"]["lan"]) > 0:
                    ip_address = device_data["ipv4_ips"]["lan"][0]
                elif len(device_data["ipv4_ips"]["wan"]) > 0:
                    ip_address = device_data["ipv4_ips"]["wan"][0]
                else:
                    ip_address = ""

        for record in MockSubordinatesHandler.subordinates:
            if record["controller_id"] == controller_id:
                return {"result": False}  # already present

        existing_subsubordinates = [
            e["controller_id"]
            for record in MockSubordinatesHandler.subordinates
            for e in record["subsubordinates"]
        ]
        if controller_id in existing_subsubordinates:
            return {"result": False}

        MockSubordinatesHandler.subordinates.append(
            {
                "controller_id": controller_id,
                "enabled": True,
                "options": {"custom_name": "", "ip_address": ip_address},
                "subsubordinates": [],
            }
        )

        return {"result": True, "controller_id": controller_id}

    @logger_wrapper(logger)
    def delete(self, controller_id) -> bool:
        if app_info["bus"] != "mqtt":
            return False
        return self.del_subordinate(controller_id) or self.del_subsubordinate(controller_id)

    def del_subordinate(self, controller_id) -> bool:
        mapped = {e["controller_id"]: e for e in MockSubordinatesHandler.subordinates}
        if controller_id not in mapped:
            return False
        del mapped[controller_id]
        MockSubordinatesHandler.subordinates = list(mapped.values())
        return True

    def del_subsubordinate(self, controller_id) -> bool:
        for record in MockSubordinatesHandler.subordinates:
            found = None
            for subsub in record["subsubordinates"]:
                if controller_id == subsub["controller_id"]:
                    found = record
                    break
            if found:
                record["subsubordinates"] == [
                    e for e in record["subsubordinates"] if e["controller_id"] != controller_id
                ]
                return True

        # not found
        return False

    @logger_wrapper(logger)
    def set_enabled(self, controller_id, enabled) -> bool:
        if app_info["bus"] != "mqtt":
            return False
        return self.set_sub_enabled(controller_id, enabled) or self.set_subsub_enabled(
            controller_id, enabled
        )

    @logger_wrapper(logger)
    def set_subsub_enabled(self, controller_id, enabled) -> bool:
        for record in MockSubordinatesHandler.subordinates:
            for subsub in record["subsubordinates"]:
                if controller_id == subsub["controller_id"]:
                    subsub["enabled"] = enabled
                    return True

        # not found
        return False

    def set_sub_enabled(self, controller_id, enabled) -> bool:
        mapped = {e["controller_id"]: e for e in MockSubordinatesHandler.subordinates}
        if controller_id not in mapped:
            return False
        mapped[controller_id]["enabled"] = enabled
        return True

    @logger_wrapper(logger)
    def add_subsub(self, controller_id, via) -> bool:
        if app_info["bus"] != "mqtt":
            return False

        # via missing
        mapped = {e["controller_id"]: e for e in MockSubordinatesHandler.subordinates}
        if via not in mapped:
            return False

        # controller_id is a sub
        if controller_id in mapped:
            return False

        existing_subsubordinates = [
            e["controller_id"]
            for record in MockSubordinatesHandler.subordinates
            for e in record["subsubordinates"]
        ]
        # controller_id is a subsub
        if controller_id in existing_subsubordinates:
            return False

        mapped[via]["subsubordinates"].append(
            {"controller_id": controller_id, "enabled": True, "options": {"custom_name": ""},}
        )

        return True

    @logger_wrapper(logger)
    def restart_mqtt(self):
        pass  # mock service restart

    @logger_wrapper(logger)
    def update_sub(self, controller_id: str, custom_name: str):
        if app_info["bus"] != "mqtt":
            return False

        for record in MockSubordinatesHandler.subordinates:
            if record["controller_id"] == controller_id:
                record["options"]["custom_name"] = custom_name
                return True

        return False

    @logger_wrapper(logger)
    def update_subsub(self, controller_id: str, custom_name: str):
        if app_info["bus"] != "mqtt":
            return False

        for sub in MockSubordinatesHandler.subordinates:
            for subsub in sub["subsubordinates"]:
                if subsub["controller_id"] == controller_id:
                    subsub["options"]["custom_name"] = custom_name
                    return True

        return False
