########################################################################
# File name: entity_info.py
# This file is part of: aioxmpp
#
# LICENSE
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program.  If not, see
# <http://www.gnu.org/licenses/>.
#
########################################################################
import asyncio
import itertools

import aioxmpp.disco
import aioxmpp.forms

from framework import Example, exec_example


class ServerInfo(Example):
    def prepare_argparse(self):
        super().prepare_argparse()

        # this gives a nicer name in argparse errors
        def jid(s):
            return aioxmpp.JID.fromstr(s)

        self.argparse.add_argument(
            "target_entity",
            default=None,
            nargs="?",
            type=jid,
            help="Entity to query (leave empty to query account)"
        )

        self.argparse.add_argument(
            "--node",
            dest="target_node",
            default=None,
            help="disco node to query"
        )

    async def run_simple_example(self):
        disco = self.client.summon(aioxmpp.DiscoClient)
        try:
            info = await disco.query_info(
                self.args.target_entity or self.client.local_jid.bare(),
                node=self.args.target_node,
                timeout=10
            )
        except Exception as exc:
            print("could not get info: ")
            print("{}: {}".format(type(exc).__name__, exc))
            raise

        print("features:")
        for feature in info.features:
            print("  {!r}".format(feature))

        print("identities:")
        identities = list(info.identities)

        def identity_key(ident):
            return (ident.category, ident.type_)

        identities.sort(key=identity_key)
        for (category, type_), identities in (
                itertools.groupby(info.identities, identity_key)):
            print("  category={!r} type={!r}".format(category, type_))
            subidentities = list(identities)
            subidentities.sort(key=lambda ident: ident.lang)
            for identity in subidentities:
                print("    [{}] {!r}".format(identity.lang, identity.name))

        print("extensions:")
        for ext in info.exts:
            print(" ", ext.get_form_type())
            for field in ext.fields:
                if (field.var == "FORM_TYPE" and
                        field.type_ == aioxmpp.forms.xso.FieldType.HIDDEN):
                    continue
                print("    var={!r} values=".format(field.var), end="")
                if len(field.values) == 1:
                    print("{!r}".format([field.values[0]]))
                elif len(field.values) == 0:
                    print("[]")
                else:
                    print("[")
                    for value in field.values:
                        print("      {!r}".format(value))
                    print("    ]")


if __name__ == "__main__":
    exec_example(ServerInfo())
