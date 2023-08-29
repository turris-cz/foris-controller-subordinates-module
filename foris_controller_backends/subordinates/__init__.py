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

import os
import logging
import tarfile
import base64
import json
import pathlib
import shutil
import typing

from io import BytesIO

from foris_controller.app import app_info

from foris_controller_backends.files import BaseFile, makedirs, inject_file_root
from foris_controller_backends.uci import (
    UciBackend,
    parse_bool,
    UciException,
    store_bool,
    get_sections_by_type,
    get_section,
    UciRecordNotFound,
)
from foris_controller.utils import RWLock
from foris_controller_backends.services import OpenwrtServices

logger = logging.getLogger(__name__)


subordinate_dir_lock = RWLock(app_info["lock_backend"])


class SubordinatesUci(object):
    def _get_options_section(
        self, data: dict, controller_id: str, section_type: str
    ) -> typing.Optional[dict]:
        for section in get_sections_by_type(data, "foris-controller-subordinates", section_type):
            if section["name"] == controller_id:
                return section
        return None

    def _get_fosquitto_section(
        self, data: dict, controller_id: str, section_type: str
    ) -> typing.Optional[dict]:
        for section in get_sections_by_type(data, "fosquitto", section_type):
            if section["name"] == controller_id:
                return section
        return None

    def list_subordinates(self):
        with UciBackend() as backend:
            fosquitto_data = backend.read("fosquitto")
            sub_data = backend.read("foris-controller-subordinates")

        res = []
        subordinates_map = {}

        for item in get_sections_by_type(fosquitto_data, "fosquitto", "subsubordinate"):
            if "via" in item["data"]:
                controller_id = item["name"]

                # try to get options
                options = {"custom_name": ""}
                options_section = self._get_options_section(
                    sub_data, controller_id, "subsubordinate"
                )
                if options_section:
                    options["custom_name"] = options_section["data"].get("custom_name", "")

                subsubs = subordinates_map.get(item["data"]["via"], [])
                subsubs.append(
                    {
                        "controller_id": controller_id,
                        "options": options,
                        "enabled": parse_bool(item["data"].get("enabled", "1")),
                    }
                )
                subordinates_map[item["data"]["via"]] = subsubs

        for item in get_sections_by_type(fosquitto_data, "fosquitto", "subordinate"):
            controller_id = item["name"]
            enabled = parse_bool(item["data"].get("enabled", "0"))

            # try to get options
            options = {
                "custom_name": "",
                "ip_address": item["data"].get("address", "0.0.0.0"),
            }
            options_section = self._get_options_section(sub_data, controller_id, "subordinate")
            if options_section:
                options["custom_name"] = options_section["data"].get("custom_name", "")

            res.append(
                {
                    "controller_id": controller_id,
                    "enabled": enabled,
                    "options": options,
                    "subsubordinates": subordinates_map.get(controller_id, []),
                }
            )

        return res

    def add_subsubordinate(self, controller_id, via):
        if not app_info["bus"] == "mqtt":
            return False

        with subordinate_dir_lock.writelock:
            if controller_id in self.existing_controller_ids():
                return False
            if via not in [e["controller_id"] for e in self.list_subordinates()]:
                return False

            with UciBackend() as backend:
                backend.add_section("fosquitto", "subsubordinate", controller_id)
                backend.set_option("fosquitto", controller_id, "via", via)
                backend.set_option("fosquitto", controller_id, "enabled", store_bool(True))

        return True

    @staticmethod
    def add_subordinate(controller_id: str, address: str, port: int):
        with UciBackend() as backend:
            backend.add_section("fosquitto", "subordinate", controller_id)
            backend.set_option("fosquitto", controller_id, "enabled", store_bool(True))
            backend.set_option("fosquitto", controller_id, "address", address)
            backend.set_option("fosquitto", controller_id, "port", port)

    def set_enabled(self, controller_id: str, enabled: bool) -> bool:
        with subordinate_dir_lock.writelock, UciBackend() as backend:
            fosquitto_data = backend.read("fosquitto")
            try:
                get_section(fosquitto_data, "fosquitto", controller_id)
            except UciRecordNotFound:
                return False

            backend.set_option("fosquitto", controller_id, "enabled", store_bool(enabled))
        return True

    @staticmethod
    def delete(controller_id: str) -> bool:
        with UciBackend() as backend:
            fosquitto_data = backend.read("fosquitto")
            to_delete = [
                e["name"]
                for e in get_sections_by_type(fosquitto_data, "fosquitto", "subsubordinate")
                if e["data"].get("via") == controller_id
            ]
            try:
                backend.del_section("fosquitto", controller_id)
                for id_to_delete in to_delete:
                    backend.del_section("fosquitto", id_to_delete)
            except UciException:
                return False

        return True

    def existing_controller_ids(self):
        sub_list = self.list_subordinates()
        return (
            [app_info["controller_id"]]
            + [e["controller_id"] for e in sub_list]
            + [e["controller_id"] for record in sub_list for e in record["subsubordinates"]]
        )

    def update_sub(
        self, controller_id: str, custom_name: str, ip_address: typing.Optional[str] = None
    ):
        restart = False
        with UciBackend() as backend:
            fosquitto_data = backend.read("fosquitto")
            section = self._get_fosquitto_section(fosquitto_data, controller_id, "subordinate")
            if not section:
                return False

            backend.add_section("foris-controller-subordinates", "subordinate", controller_id)
            backend.set_option(
                "foris-controller-subordinates", controller_id, "custom_name", custom_name
            )
            if ip_address is not None:
                if ip_address != section["data"]["address"]:
                    restart = True

                backend.set_option("fosquitto", controller_id, "address", ip_address)
        if restart:
            SubordinatesService().restart()

        return True

    def update_subsub(self, controller_id: str, custom_name: str):
        with UciBackend() as backend:
            fosquitto_data = backend.read("fosquitto")
            if not self._get_fosquitto_section(fosquitto_data, controller_id, "subsubordinate"):
                return False
            backend.add_section("foris-controller-subordinates", "subsubordinate", controller_id)
            backend.set_option(
                "foris-controller-subordinates", controller_id, "custom_name", custom_name
            )
        return True


class SubordinatesFiles(BaseFile):
    @staticmethod
    def extract_token_subordinate(token: str) -> typing.Tuple[dict, dict]:
        token_data = BytesIO(base64.b64decode(token))
        with tarfile.open(fileobj=token_data, mode="r:gz") as tar:
            config_file = [e for e in tar.getmembers() if e.name.endswith(".json")][0]
            with tar.extractfile(config_file) as f:
                conf = json.load(f)
            file_data = {}
            for member in [e for e in tar.getmembers() if e.isfile()]:
                with tar.extractfile(member) as f:
                    file_data[os.path.basename(member.name)] = f.read()
        return conf, file_data

    @staticmethod
    def store_subordinate_files(controller_id: str, file_data: dict):
        path_root = pathlib.Path("/etc/fosquitto/bridges") / controller_id
        makedirs(str(path_root), 0o0777)

        for name, content in file_data.items():
            new_file = pathlib.Path(inject_file_root(str(path_root / name)))
            new_file.touch(0o0600)
            with new_file.open("wb") as f:
                f.write(content)
                f.flush()

            try:  # try chown (best effort)
                shutil.chown(new_file, "mosquitto", "mosquitto")
            except (LookupError, PermissionError):
                pass

    @staticmethod
    def remove_subordinate(controller_id: str):
        path = pathlib.Path("/etc/fosquitto/bridges") / controller_id
        shutil.rmtree(inject_file_root(str(path)), ignore_errors=True)


class SubordinatesComplex:
    def add_subordinate(self, token):
        if not app_info["bus"] == "mqtt":
            return {"result": False}

        conf, file_data = SubordinatesFiles.extract_token_subordinate(token)

        with subordinate_dir_lock.writelock:

            if conf["device_id"] in SubordinatesUci().existing_controller_ids():
                return {"result": False}

            SubordinatesFiles.store_subordinate_files(conf["device_id"], file_data)

            guessed_ip = ""
            # it would be more common to use wan ip first
            if conf["ipv4_ips"].get("wan", None):
                guessed_ip = conf["ipv4_ips"]["wan"][0]
            elif conf["ipv4_ips"].get("lan", None):
                guessed_ip = conf["ipv4_ips"]["lan"][0]

            SubordinatesUci.add_subordinate(conf["device_id"], guessed_ip, conf["port"])

        return {"result": True, "controller_id": conf["device_id"]}

    def delete(self, controller_id):
        with subordinate_dir_lock.writelock:
            if not SubordinatesUci.delete(controller_id):
                return False
            SubordinatesFiles.remove_subordinate(controller_id)

        return True


class SubordinatesService:
    def restart(self):
        with OpenwrtServices() as services:
            services.restart("fosquitto")
