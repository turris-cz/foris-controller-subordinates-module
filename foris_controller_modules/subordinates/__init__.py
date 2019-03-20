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

import logging

from foris_controller.module_base import BaseModule
from foris_controller.handler_base import wrap_required_functions


class SubordinatesModule(BaseModule):
    logger = logging.getLogger(__name__)

    def action_list(self, data):
        return {"subordinates": self.handler.list_subordinates()}

    def action_add_sub(self, data):
        res = self.handler.add_sub(**data)
        if res["result"]:
            self.notify(
                "add_sub",
                {"controller_id": res["controller_id"]}
            )
            self.handler.restart_mqtt()
        return res

    def action_add_subsub(self, data):
        res = self.handler.add_subsub(**data)
        if res:
            self.notify("add_subsub", data)
            self.handler.restart_mqtt()
        return {"result": res}

    def action_del(self, data):
        res = self.handler.delete(**data)
        if res:
            self.notify("del", data)
            self.handler.restart_mqtt()
        return {"result": res}

    def action_set_enabled(self, data):
        res = self.handler.set_enabled(**data)
        if res:
            self.notify("set_enabled", data)
            self.handler.restart_mqtt()
        return {"result": res}

    def action_update_sub(self, data):
        res = self.handler.update_sub(data["controller_id"], **data["options"])
        if res:
            self.notify("update_sub", data)
        return {"result": res}

    def action_update_subsub(self, data):
        res = self.handler.update_subsub(data["controller_id"], **data["options"])
        if res:
            self.notify("update_subsub", data)
        return {"result": res}


@wrap_required_functions([
    'list_subordinates',
    'add_sub',
    'add_subsub',
    'delete',
    'set_enabled',
    'restart_mqtt',
    'update_sub',
    'update_subsub',
])
class Handler(object):
    pass
