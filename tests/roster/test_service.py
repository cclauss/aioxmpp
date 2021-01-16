########################################################################
# File name: test_service.py
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
import contextlib
import unittest

import aioxmpp.dispatcher
import aioxmpp.errors as errors
import aioxmpp.roster.service as roster_service
import aioxmpp.roster.xso as roster_xso
import aioxmpp.service as service
import aioxmpp.stanza as stanza
import aioxmpp.structs as structs

from aioxmpp.utils import namespaces

from aioxmpp.testutils import (
    make_connected_client,
    run_coroutine,
    make_listener,
)


TEST_JID = structs.JID.fromstr("user@foo.example")


class TestItem(unittest.TestCase):
    def setUp(self):
        self.jid = TEST_JID

    def test_init(self):
        item = roster_service.Item(self.jid)
        self.assertEqual(self.jid, item.jid)
        self.assertEqual("none", item.subscription)
        self.assertFalse(item.approved)
        self.assertIsNone(item.ask)
        self.assertIsNone(item.name)
        self.assertSetEqual(set(), item.groups)

        item = roster_service.Item(
            self.jid,
            subscription="both",
            approved=True,
            ask="subscribe",
            name="foobar",
            groups=("fnord", "bar"))
        self.assertEqual("both", item.subscription)
        self.assertTrue(item.approved)
        self.assertEqual("subscribe", item.ask)
        self.assertEqual("foobar", item.name)
        self.assertSetEqual(
            {"fnord", "bar"},
            item.groups
        )

    def test_update_from_xso_item(self):
        xso_item = roster_xso.Item(
            jid=self.jid,
            subscription="to",
            ask="subscribe",
            approved=False,
            name="test",
            groups=[
                roster_xso.Group(name="foo"),
                roster_xso.Group(name="bar"),
            ])

        item = roster_service.Item(self.jid)
        item.update_from_xso_item(xso_item)
        self.assertEqual(xso_item.jid, item.jid)
        self.assertEqual(xso_item.subscription, item.subscription)
        self.assertEqual(xso_item.ask, item.ask)
        self.assertEqual(xso_item.approved, item.approved)
        self.assertEqual(xso_item.name, item.name)
        self.assertSetEqual({"foo", "bar"}, item.groups)

        xso_item = roster_xso.Item(
            jid=structs.JID.fromstr("user@bar.example"),
            subscription="from",
            ask=None,
            approved=True,
            name="other test",
            groups=[
                roster_xso.Group(name="a")
            ])
        item.update_from_xso_item(xso_item)

        self.assertEqual(self.jid, item.jid)
        self.assertEqual(xso_item.subscription, item.subscription)
        self.assertEqual(xso_item.ask, item.ask)
        self.assertEqual(xso_item.approved, item.approved)
        self.assertEqual(xso_item.name, item.name)
        self.assertSetEqual({"a"}, item.groups)

    @unittest.mock.patch.object(roster_service.Item, "update_from_xso_item")
    def test_from_xso_item(self, update_from_xso_item):
        xso_item = roster_xso.Item(
            jid=structs.JID.fromstr("user@bar.example"),
            subscription="from",
            ask=None,
            approved=True)

        item = roster_service.Item.from_xso_item(xso_item)
        self.assertEqual(xso_item.jid, item.jid)
        self.assertSequenceEqual(
            [
                unittest.mock.call(xso_item)
            ],
            update_from_xso_item.mock_calls
        )

    def test_export_as_json(self):
        item = roster_service.Item(
            jid=self.jid,
            subscription="to",
            ask="subscribe",
            approved=False,
            name="test",
            groups=["a", "b"])

        self.assertDictEqual(
            {
                "subscription": "to",
                "ask": "subscribe",
                "name": "test",
                "groups": ["a", "b"],
            },
            item.export_as_json()
        )

        item = roster_service.Item(
            jid=self.jid,
            approved=True,
            groups=["z", "a"])

        self.assertDictEqual(
            {
                "subscription": "none",
                "approved": True,
                "groups": ["a", "z"],
            },
            item.export_as_json()
        )

    def test_update_from_json(self):
        item = roster_service.Item(jid=self.jid)

        item.update_from_json({
            "subscription": "both"
        })
        self.assertEqual("both", item.subscription)

        item.update_from_json({
            "approved": True
        })
        self.assertTrue(item.approved)
        self.assertEqual("none", item.subscription)

        item.update_from_json({
            "ask": "subscribe"
        })
        self.assertEqual("subscribe", item.ask)
        self.assertFalse(item.approved)

        item.update_from_json({
            "name": "foobar baz"
        })
        self.assertEqual("foobar baz", item.name)
        self.assertIsNone(item.ask)

        item.update_from_json({
            "groups": ["a", "b", "a"],
        })
        self.assertIsNone(item.name)
        self.assertSetEqual({"a", "b"}, item.groups)

        item.update_from_json({})
        self.assertSetEqual(set(), item.groups)


class TestService(unittest.TestCase):
    def setUp(self):
        self.cc = make_connected_client()
        self.presence_dispatcher = aioxmpp.dispatcher.SimplePresenceDispatcher(
            self.cc
        )
        self.dependencies = {
            aioxmpp.dispatcher.SimplePresenceDispatcher:
                self.presence_dispatcher,
        }
        self.s = roster_service.RosterClient(
            self.cc,
            dependencies=self.dependencies
        )

        self.user1 = structs.JID.fromstr("user@foo.example")
        self.user2 = structs.JID.fromstr("user@bar.example")

        response = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user1,
                    groups=[
                        roster_xso.Group(name="group1"),
                        roster_xso.Group(name="group3"),
                    ]
                ),
                roster_xso.Item(
                    jid=self.user2,
                    name="some bar user",
                    subscription="both",
                    groups=[
                        roster_xso.Group(name="group1"),
                        roster_xso.Group(name="group2"),
                    ]
                )
            ],
            ver="foobar"
        )

        self.cc.send.return_value = response

        run_coroutine(self.cc.before_stream_established())

        self.cc.send.reset_mock()

        self.listener = make_listener(self.s)

    def test_is_Service(self):
        self.assertIsInstance(
            self.s,
            service.Service
        )

    def test_init(self):
        # required to clear listeners of dependency
        run_coroutine(self.s.shutdown())
        s = roster_service.RosterClient(
            self.cc,
            dependencies=self.dependencies
        )
        self.assertDictEqual({}, s.items)
        self.assertEqual(None, s.version)
        self.assertDictEqual({}, s.groups)

    def test_handle_roster_push_is_decorated(self):
        self.assertTrue(
            service.is_iq_handler(
                structs.IQType.SET,
                roster_xso.Query,
                roster_service.RosterClient.handle_roster_push,
            )
        )

    def test_handle_subscribe_is_decorated(self):
        self.assertTrue(
            aioxmpp.dispatcher.is_presence_handler(
                structs.PresenceType.SUBSCRIBE,
                None,
                roster_service.RosterClient.handle_subscribe,
            )
        )

    def test_handle_subscribed_is_decorated(self):
        self.assertTrue(
            aioxmpp.dispatcher.is_presence_handler(
                structs.PresenceType.SUBSCRIBED,
                None,
                roster_service.RosterClient.handle_subscribed,
            )
        )

    def test_handle_unsubscribe_is_decorated(self):
        self.assertTrue(
            aioxmpp.dispatcher.is_presence_handler(
                structs.PresenceType.UNSUBSCRIBE,
                None,
                roster_service.RosterClient.handle_unsubscribe,
            )
        )

    def test_handle_unsubscribed_is_decorated(self):
        self.assertTrue(
            aioxmpp.dispatcher.is_presence_handler(
                structs.PresenceType.UNSUBSCRIBED,
                None,
                roster_service.RosterClient.handle_unsubscribed,
            )
        )

    def test_request_initial_roster_before_stream_established(self):
        self.assertIn(self.user1, self.s.items)
        self.assertIn(self.user2, self.s.items)
        self.assertEqual("foobar", self.s.version)

        self.assertEqual("both", self.s.items[self.user2].subscription)
        self.assertEqual("some bar user", self.s.items[self.user2].name)

    def test_handle_roster_push_rejects_push_with_nonempty_from(self):
        self.cc.local_jid = structs.JID.fromstr("foo@bar.example")

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.from_ = structs.JID.fromstr("fnord@bar.example")

        with self.assertRaises(errors.XMPPAuthError) as ctx:
            run_coroutine(self.s.handle_roster_push(iq))

        self.assertEqual(
            errors.ErrorCondition.FORBIDDEN,
            ctx.exception.condition
        )

    def test_handle_roster_push_accepts_push_from_bare_local_jid(self):
        self.cc.local_jid = structs.JID.fromstr("foo@bar.example/fnord")

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.from_ = structs.JID.fromstr("foo@bar.example")
        iq.payload = roster_xso.Query()

        run_coroutine(self.s.handle_roster_push(iq))

    def test_handle_roster_push_rejects_push_from_full_local_jid(self):
        self.cc.local_jid = structs.JID.fromstr("foo@bar.example/fnord")

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.from_ = structs.JID.fromstr("foo@bar.example/fnord")
        iq.payload = roster_xso.Query()

        with self.assertRaises(errors.XMPPAuthError) as ctx:
            run_coroutine(self.s.handle_roster_push(iq))

        self.assertEqual(
            errors.ErrorCondition.FORBIDDEN,
            ctx.exception.condition
        )

    def test_handle_roster_push_extends_roster(self):
        user1 = structs.JID.fromstr("user2@foo.example")
        user2 = structs.JID.fromstr("user2@bar.example")

        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=user1),
                roster_xso.Item(
                    jid=user2,
                    name="some bar user",
                    subscription="both"
                )
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        self.assertIsNone(
            run_coroutine(self.s.handle_roster_push(iq))
        )

        self.assertIn(user1, self.s.items)
        self.assertIn(user2, self.s.items)
        self.assertEqual("foobar", self.s.version)

        self.assertEqual("both", self.s.items[user2].subscription)
        self.assertEqual("some bar user", self.s.items[user2].name)

    def test_handle_roster_push_removes_from_roster(self):
        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user1,
                    subscription="remove"),
            ],
            ver="foobarbaz"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        self.assertIsNone(
            run_coroutine(self.s.handle_roster_push(iq))
        )

        self.assertNotIn(self.user1, self.s.items)
        self.assertIn(self.user2, self.s.items)
        self.assertEqual("foobarbaz", self.s.version)

    def test_item_objects_do_not_change_during_push(self):
        old_item = self.s.items[self.user1]

        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user1,
                    subscription="both"
                ),
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        self.assertIsNone(
            run_coroutine(self.s.handle_roster_push(iq))
        )

        self.assertIs(old_item, self.s.items[self.user1])
        self.assertEqual("both", old_item.subscription)

    def test_initial_roster_discards_information(self):
        self.cc.mock_calls.clear()

        response = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    name="some bar user",
                    subscription="both"
                )
            ],
            ver="foobar"
        )

        self.cc.send.return_value = response

        run_coroutine(self.cc.before_stream_established())
        self.assertSequenceEqual(
            [
                unittest.mock.call.send(
                    unittest.mock.ANY,
                    timeout=self.cc.negotiation_timeout.total_seconds()
                )
            ],
            self.cc.mock_calls
        )

        self.assertNotIn(self.user1, self.s.items)

    def test_initial_roster_fires_event(self):
        response = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    name="some bar user",
                    subscription="both"
                )
            ],
            ver="foobar"
        )

        cb = unittest.mock.Mock()
        cb.return_value = True

        def cb_impl():
            cb()
            # assure that the roster update is already finished
            self.assertNotIn(self.user1, self.s.items)

        self.s.on_initial_roster_received.connect(cb_impl)

        self.cc.send.return_value = response
        self.cc.send.delay = 0.05

        task = asyncio.ensure_future(self.cc.before_stream_established())

        run_coroutine(asyncio.sleep(0.01))

        self.assertSequenceEqual([], cb.mock_calls)

        run_coroutine(asyncio.sleep(0.041))

        self.assertSequenceEqual(
            [
                unittest.mock.call(),
            ],
            cb.mock_calls
        )

    def test_initial_roster_fires_group_event(self):
        response = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    name="some bar user",
                    subscription="both",
                    groups={roster_xso.Group(name="a"),
                            roster_xso.Group(name="b")}
                ),
                roster_xso.Item(
                    jid=self.user1,
                    name="some foo user",
                    subscription="both",
                    groups={roster_xso.Group(name="a"),
                            roster_xso.Group(name="c")}
                )
            ],
            ver="foobar"
        )

        self.cc.send.return_value = response

        run_coroutine(self.cc.before_stream_established())

        self.assertCountEqual(
            self.listener.on_group_added.mock_calls,
            [
                unittest.mock.call("a"),
                unittest.mock.call("b"),
                unittest.mock.call("c"),
            ]
        )

    def test_initial_roster_does_not_emit_entry_added_for_existing(self):
        old_item = self.s.items[self.user2]

        response = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    name="new name",
                    subscription="both"
                ),
                roster_xso.Item(
                    jid=self.user2.replace(localpart="user2"),
                    name="other name",
                )
            ],
            ver="foobar"
        )

        mock = unittest.mock.Mock()
        mock.return_value = False
        self.s.on_entry_added.connect(mock)

        self.cc.send.return_value = response

        run_coroutine(self.cc.before_stream_established())

        self.assertSequenceEqual(
            [
                unittest.mock.call(
                    self.s.items[self.user2.replace(localpart="user2")]
                ),
            ],
            mock.mock_calls
        )

    def test_initial_roster_keeps_existing_entries_alive(self):
        old_item = self.s.items[self.user2]

        response = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    name="new name",
                    subscription="both"
                )
            ],
            ver="foobar"
        )

        self.cc.send.return_value = response

        run_coroutine(self.cc.before_stream_established())

        self.assertIs(old_item, self.s.items[self.user2])
        self.assertEqual("new name", old_item.name)

    def test_initial_roster_removes_contact_from_groups(self):
        response = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    name="some bar user",
                    subscription="both",
                    groups=[
                        roster_xso.Group(name="group1"),
                        roster_xso.Group(name="group2"),
                    ]
                )
            ],
            ver="foobar"
        )

        self.cc.send.return_value = response

        run_coroutine(self.cc.before_stream_established())

        self.assertSetEqual(
            self.s.groups["group1"],
            {self.s.items[self.user2]},
        )

        self.assertSetEqual(
            self.s.groups["group2"],
            {self.s.items[self.user2]},
        )

        self.assertSetEqual(
            self.s.groups.get("group3", set()),
            set(),
        )

    def test_initial_roster_fires_group_removed_event_for_removed_contact(self):  # NOQA
        response = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    name="some bar user",
                    subscription="both",
                    groups=[
                        roster_xso.Group(name="group1"),
                        roster_xso.Group(name="group2"),
                    ]
                )
            ],
            ver="foobar"
        )

        self.cc.send.return_value = response

        run_coroutine(self.cc.before_stream_established())

        self.assertCountEqual(
            self.listener.on_group_removed.mock_calls,
            [
                unittest.mock.call("group3"),
            ]
        )

    def test_initial_roster_fires_group_removed_event_for_changed_contact(self):  # NOQA
        response = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    name="some bar user",
                    subscription="both",
                    groups=[
                        roster_xso.Group(name="group1"),
                        roster_xso.Group(name="group2"),
                    ]
                ),
                roster_xso.Item(
                    jid=self.user1,
                    name="some foo user",
                    subscription="both",
                    groups={roster_xso.Group(name="group1")}
                )
            ],
            ver="foobar"
        )

        self.cc.send.return_value = response

        run_coroutine(self.cc.before_stream_established())

        self.assertCountEqual(
            self.listener.on_group_removed.mock_calls,
            [
                unittest.mock.call("group3"),
            ]
        )

    def test_groups_are_cleaned_up_up_when_on_entry_removed_fires_on_initial_roster(self):  # NOQA
        response = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    name="some bar user",
                    subscription="both",
                    groups=[
                        roster_xso.Group(name="group1"),
                        roster_xso.Group(name="group2"),
                    ]
                ),
            ],
            ver="foobar"
        )

        fut = asyncio.Future()

        def handler(item):
            try:
                for group in item.groups:
                    try:
                        members = self.s.groups[group]
                    except KeyError:
                        members = set()
                    self.assertNotIn(item, members)

            except Exception as exc:
                fut.set_exception(exc)
            else:
                fut.set_result(None)

        self.cc.send.return_value = response

        self.s.on_entry_removed.connect(handler)

        run_coroutine(self.cc.before_stream_established())

        run_coroutine(fut)

    def test_on_entry_name_changed(self):
        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user1,
                    name="foobarbaz",
                ),
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        cb = unittest.mock.Mock()
        with self.s.on_entry_name_changed.context_connect(cb):
            run_coroutine(self.s.handle_roster_push(iq))
            run_coroutine(self.s.handle_roster_push(iq))

        self.assertSequenceEqual(
            [
                unittest.mock.call(self.s.items[self.user1]),
            ],
            cb.mock_calls
        )

    def test_on_entry_subscription_state_changed(self):
        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user1,
                    subscription="both",
                    approved=True,
                    ask="subscribe"
                ),
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        cb = unittest.mock.Mock()
        with self.s.on_entry_subscription_state_changed.context_connect(cb):
            run_coroutine(self.s.handle_roster_push(iq))
            run_coroutine(self.s.handle_roster_push(iq))

        self.assertSequenceEqual(
            [
                unittest.mock.call(self.s.items[self.user1]),
            ],
            cb.mock_calls
        )

    def test_on_entry_removed(self):
        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user1,
                    subscription="remove",
                ),
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        old_item = self.s.items[self.user1]

        cb = unittest.mock.Mock()
        with self.s.on_entry_removed.context_connect(cb):
            run_coroutine(self.s.handle_roster_push(iq))
            run_coroutine(self.s.handle_roster_push(iq))

        self.assertSequenceEqual(
            [
                unittest.mock.call(old_item),
            ],
            cb.mock_calls
        )

    def test_on_entry_added(self):
        new_jid = structs.JID.fromstr("fnord@foo.example")

        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=new_jid,
                    subscription="none",
                ),
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        cb = unittest.mock.Mock()
        with self.s.on_entry_added.context_connect(cb):
            run_coroutine(self.s.handle_roster_push(iq))
            run_coroutine(self.s.handle_roster_push(iq))

        self.assertSequenceEqual(
            [
                unittest.mock.call(self.s.items[new_jid]),
            ],
            cb.mock_calls
        )

    def test_on_entry_removed_called_from_initial_roster(self):
        response = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    name="some bar user",
                    subscription="both"
                )
            ],
            ver="foobar"
        )

        old_item = self.s.items[self.user1]

        self.cc.send.return_value = response

        cb = unittest.mock.Mock()
        with self.s.on_entry_removed.context_connect(cb):
            run_coroutine(self.cc.before_stream_established())

        self.assertSequenceEqual(
            [
                unittest.mock.call(old_item),
            ],
            cb.mock_calls
        )

    def test_on_group_added_for_new_contact(self):
        new_jid = structs.JID.fromstr("fnord@foo.example")

        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=new_jid,
                    subscription="none",
                    groups={
                        roster_xso.Group(name="a"),
                        roster_xso.Group(name="group1"),
                    },
                ),
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        run_coroutine(self.s.handle_roster_push(iq))

        self.listener.on_group_added.assert_called_once_with("a")

    def test_groups_are_set_up_when_on_entry_added_fires(self):
        fut = asyncio.Future()

        def handler(item):
            try:
                for group in item.groups:
                    self.assertIn(group, self.s.groups)
                    self.assertIn(item, self.s.groups[group])

            except Exception as exc:
                fut.set_exception(exc)
            else:
                fut.set_result(None)

        new_jid = structs.JID.fromstr("fnord@foo.example")

        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=new_jid,
                    subscription="none",
                    groups={
                        roster_xso.Group(name="a"),
                        roster_xso.Group(name="group1"),
                    },
                ),
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        self.s.on_entry_added.connect(handler)

        run_coroutine(self.s.handle_roster_push(iq))

        run_coroutine(fut)

    def test_on_group_added_for_existing_contact(self):
        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    subscription="none",
                    groups={
                        roster_xso.Group(name="group1"),
                        roster_xso.Group(name="group2"),
                        roster_xso.Group(name="group4"),
                    },
                ),
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        run_coroutine(self.s.handle_roster_push(iq))

        self.listener.on_group_added.assert_called_once_with("group4")

    def test_on_group_removed_for_existing_contact(self):
        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    subscription="none",
                    groups={
                        roster_xso.Group(name="group1"),
                    },
                ),
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        run_coroutine(self.s.handle_roster_push(iq))

        self.listener.on_group_removed.assert_called_once_with("group2")

    def test_on_group_removed_for_removed_contact(self):
        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    subscription="remove",
                ),
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        run_coroutine(self.s.handle_roster_push(iq))

        self.listener.on_group_removed.assert_called_once_with("group2")

    def test_groups_are_cleaned_up_up_when_on_entry_removed_fires_on_push(self):
        fut = asyncio.Future()

        def handler(item):
            try:
                for group in item.groups:
                    try:
                        members = self.s.groups[group]
                    except KeyError:
                        members = set()
                    self.assertNotIn(item, members)

            except Exception as exc:
                fut.set_exception(exc)
            else:
                fut.set_result(None)

        new_jid = structs.JID.fromstr("fnord@foo.example")

        request = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    subscription="remove",
                ),
            ],
            ver="foobar"
        )

        iq = stanza.IQ(type_=structs.IQType.SET)
        iq.payload = request

        self.s.on_entry_removed.connect(handler)

        run_coroutine(self.s.handle_roster_push(iq))

        run_coroutine(fut)

    def test_export_as_json(self):
        self.assertDictEqual(
            {
                "items": {
                    str(self.user1): {
                        "subscription": "none",
                        "groups": ["group1", "group3"],
                    },
                    str(self.user2): {
                        "subscription": "both",
                        "name": "some bar user",
                        "groups": ["group1", "group2"],
                    },
                },
                "ver": "foobar",
            },
            self.s.export_as_json()
        )

    def test_import_from_json(self):
        jid1 = structs.JID.fromstr("fnord@foo.example")
        jid2 = structs.JID.fromstr("fnord@bar.example")

        data = {
            "items": {
                str(jid1): {
                    "name": "foo fnord",
                    "subscription": "both",
                },
                str(jid2): {
                    "name": "bar fnord",
                    "subscription": "to",
                }
            },
            "ver": "foobarbaz",
        }

        # import_from_json does not fire events

        cb = unittest.mock.Mock()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                self.s.on_entry_added.context_connect(cb)
            )
            stack.enter_context(
                self.s.on_entry_removed.context_connect(cb)
            )
            self.s.import_from_json(data)

        self.assertEqual("foobarbaz", self.s.version)

        self.assertNotIn(self.user1, self.s.items)
        self.assertNotIn(self.user2, self.s.items)

        self.assertIn(jid1, self.s.items)
        self.assertIn(jid2, self.s.items)

        self.assertEqual(self.s.items[jid1].name, "foo fnord")
        self.assertEqual(self.s.items[jid1].subscription, "both")

        self.assertEqual(self.s.items[jid2].name, "bar fnord")
        self.assertEqual(self.s.items[jid2].subscription, "to")

        self.assertSequenceEqual([], cb.mock_calls)

    def test_do_not_send_versioned_request_if_not_supported_by_server(self):
        response = roster_xso.Query()

        self.cc.send.return_value = response

        run_coroutine(self.cc.before_stream_established())

        call, = self.cc.send.mock_calls
        _, call_args, call_kwargs = call

        iq_request, = call_args
        self.assertIsNone(
            iq_request.payload.ver
        )

        self.assertNotIn(self.user1, self.s.items)
        self.assertNotIn(self.user2, self.s.items)

    def test_send_versioned_request_if_not_supported_by_server(self):
        self.cc.stream_features[...] = roster_xso.RosterVersioningFeature()

        response = roster_xso.Query()

        self.cc.send.return_value = response

        run_coroutine(self.cc.before_stream_established())

        call, = self.cc.send.mock_calls
        _, call_args, call_kwargs = call

        iq_request, = call_args
        self.assertEqual(
            "foobar",
            iq_request.payload.ver
        )

    def test_process_none_response_to_versioned_request(self):
        self.cc.stream_features[...] = roster_xso.RosterVersioningFeature()

        self.cc.send.return_value = None

        cb = unittest.mock.Mock()
        cb.return_value = True

        self.s.on_initial_roster_received.connect(cb)

        run_coroutine(self.cc.before_stream_established())

        call, = self.cc.send.mock_calls
        _, call_args, call_kwargs = call

        iq_request, = call_args
        self.assertEqual(
            "foobar",
            iq_request.payload.ver
        )

        self.assertIn(self.user1, self.s.items)
        self.assertIn(self.user2, self.s.items)

        self.assertSequenceEqual(
            [
                unittest.mock.call(),
            ],
            cb.mock_calls
        )

    def test_groups_in_initial_roster(self):
        self.assertIn("group1", self.s.groups)
        self.assertIn("group2", self.s.groups)
        self.assertIn("group3", self.s.groups)

        self.assertSetEqual(
            {
                self.s.items[self.user1],
                self.s.items[self.user2],
            },
            self.s.groups["group1"]
        )

        self.assertSetEqual(
            {
                self.s.items[self.user1],
            },
            self.s.groups["group3"]
        )

        self.assertSetEqual(
            {
                self.s.items[self.user2],
            },
            self.s.groups["group2"]
        )

    def test_update_groups_on_update(self):
        request = roster_xso.Query(items=[
            roster_xso.Item(
                jid=self.user1,
                groups=[
                    roster_xso.Group(name="group4")
                ],
            )
        ])

        run_coroutine(self.s.handle_roster_push(
            stanza.IQ(
                structs.IQType.SET,
                payload=request
            )
        ))

        self.assertNotIn("group3", self.s.groups)
        self.assertSetEqual(
            {self.s.items[self.user2]},
            self.s.groups["group1"]
        )
        self.assertSetEqual(
            {self.s.items[self.user2]},
            self.s.groups["group2"]
        )
        self.assertSetEqual(
            {self.s.items[self.user1]},
            self.s.groups["group4"]
        )

    def test_groups_update_fires_events(self):
        request = roster_xso.Query(items=[
            roster_xso.Item(
                jid=self.user1,
                groups=[
                    roster_xso.Group(name="group4")
                ],
            )
        ])

        added_cb = unittest.mock.Mock()
        added_cb.return_value = False
        removed_cb = unittest.mock.Mock()
        removed_cb.return_value = False

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                self.s.on_entry_added_to_group.context_connect(added_cb)
            )
            stack.enter_context(
                self.s.on_entry_removed_from_group.context_connect(removed_cb)
            )
            run_coroutine(self.s.handle_roster_push(
                stanza.IQ(
                    structs.IQType.SET,
                    payload=request
                )
            ))

        self.assertSequenceEqual(
            [
                unittest.mock.call(self.s.items[self.user1], "group4"),
            ],
            added_cb.mock_calls
        )

        self.assertIn(
            unittest.mock.call(self.s.items[self.user1], "group1"),
            removed_cb.mock_calls
        )

        self.assertIn(
            unittest.mock.call(self.s.items[self.user1], "group3"),
            removed_cb.mock_calls
        )

    def test_import_from_json_fixes_groups(self):
        self.s.import_from_json({
            "items": {
                str(self.user1): {
                    "groups": ["a", "b"],
                },
                str(self.user2): {
                    "groups": ["b", "c"],
                }
            }
        })

        self.assertSetEqual(
            set("abc"),
            set(self.s.groups.keys())
        )

        self.assertSetEqual(
            {self.s.items[self.user1], self.s.items[self.user2]},
            self.s.groups["b"]
        )

        self.assertSetEqual(
            {self.s.items[self.user1]},
            self.s.groups["a"]
        )

        self.assertSetEqual(
            {self.s.items[self.user2]},
            self.s.groups["c"]
        )

    def test_item_removal_fixes_groups(self):
        request = roster_xso.Query(items=[
            roster_xso.Item(
                jid=self.user1,
                subscription="remove",
            )
        ])

        added_cb = unittest.mock.Mock()
        added_cb.return_value = False
        removed_cb = unittest.mock.Mock()
        removed_cb.return_value = False

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                self.s.on_entry_added_to_group.context_connect(added_cb)
            )
            stack.enter_context(
                self.s.on_entry_removed_from_group.context_connect(removed_cb)
            )
            run_coroutine(self.s.handle_roster_push(
                stanza.IQ(
                    structs.IQType.SET,
                    payload=request
                )
            ))

        self.assertSequenceEqual([], added_cb.mock_calls)
        self.assertSequenceEqual([], removed_cb.mock_calls)

        self.assertSetEqual(
            {"group1", "group2"},
            set(self.s.groups.keys())
        )

        self.assertSetEqual(
            {self.s.items[self.user2]},
            self.s.groups["group1"]
        )

        self.assertSetEqual(
            {self.s.items[self.user2]},
            self.s.groups["group2"]
        )

    def test_set_entry_name(self):
        self.cc.send.return_value = None

        run_coroutine(
            self.s.set_entry(
                self.user1,
                name="foobar",
                timeout=10
            ),
        )

        self.assertSequenceEqual(
            [
                unittest.mock.call(unittest.mock.ANY, timeout=10)
            ],
            self.cc.send.mock_calls
        )

        call, = self.cc.send.mock_calls
        _, call_args, _ = call

        request_iq, = call_args
        self.assertIsNone(request_iq.to)
        self.assertIsInstance(
            request_iq.payload,
            roster_xso.Query
        )

        query = request_iq.payload
        self.assertIsNone(query.ver)
        self.assertEqual(1, len(query.items))

        item, = query.items
        self.assertEqual(
            self.user1,
            item.jid
        )
        self.assertEqual(
            "foobar",
            item.name
        )
        self.assertSetEqual(
            {
                "group1", "group3"
            },
            {group.name for group in item.groups}
        )

        # defaults
        self.assertEqual("none", item.subscription)
        self.assertFalse(item.approved)
        self.assertIsNone(item.ask)

    def test_set_entry_groups(self):
        self.cc.send.return_value = None

        run_coroutine(
            self.s.set_entry(
                self.user2,
                add_to_groups={"a", "b"},
                remove_from_groups={"group1"},
                timeout=10
            )
        )

        self.assertSequenceEqual(
            [
                unittest.mock.call(unittest.mock.ANY, timeout=10)
            ],
            self.cc.send.mock_calls
        )

        call, = self.cc.send.mock_calls
        _, call_args, _ = call

        request_iq, = call_args
        self.assertIsNone(request_iq.to)
        self.assertIsInstance(
            request_iq.payload,
            roster_xso.Query
        )

        query = request_iq.payload
        self.assertIsNone(query.ver)
        self.assertEqual(1, len(query.items))

        item, = query.items
        self.assertEqual(
            self.user2,
            item.jid
        )
        self.assertEqual(
            "some bar user",
            item.name
        )
        self.assertSetEqual(
            {
                "a", "b", "group2"
            },
            {group.name for group in item.groups}
        )

        # defaults
        self.assertEqual("none", item.subscription)
        self.assertFalse(item.approved)
        self.assertIsNone(item.ask)

    def test_remove_entry(self):
        self.cc.send.return_value = None

        run_coroutine(
            self.s.remove_entry(
                self.user2,
                timeout=10
            )
        )

        self.assertSequenceEqual(
            [
                unittest.mock.call(unittest.mock.ANY, timeout=10)
            ],
            self.cc.send.mock_calls
        )

        call, = self.cc.send.mock_calls
        _, call_args, _ = call

        request_iq, = call_args
        self.assertIsNone(request_iq.to)
        self.assertIsInstance(
            request_iq.payload,
            roster_xso.Query
        )

        query = request_iq.payload
        self.assertIsNone(query.ver)
        self.assertEqual(1, len(query.items))

        item, = query.items
        self.assertEqual(
            self.user2,
            item.jid
        )
        self.assertEqual("remove", item.subscription)

        # defaults
        self.assertIsNone(item.ask)
        self.assertFalse(item.approved)
        self.assertFalse(item.groups)
        self.assertIsNone(item.name)

    def test_handle_subscribe_emits_event(self):
        st = stanza.Presence(
            type_=structs.PresenceType.SUBSCRIBE,
            from_=TEST_JID
        )

        mock = unittest.mock.Mock()
        self.s.on_subscribe.connect(mock)
        self.s.handle_subscribe(st)
        self.assertSequenceEqual(
            mock.mock_calls,
            [
                unittest.mock.call(st)
            ]
        )

    def test_handle_subscribed_emits_event(self):
        st = stanza.Presence(
            type_=structs.PresenceType.SUBSCRIBED,
            from_=TEST_JID
        )

        mock = unittest.mock.Mock()
        self.s.on_subscribed.connect(mock)
        self.s.handle_subscribed(st)
        self.assertSequenceEqual(
            mock.mock_calls,
            [
                unittest.mock.call(st)
            ]
        )

    def test_handle_unsubscribed_emits_event(self):
        st = stanza.Presence(
            type_=structs.PresenceType.UNSUBSCRIBED,
            from_=TEST_JID
        )

        mock = unittest.mock.Mock()
        self.s.on_unsubscribed.connect(mock)
        self.s.handle_unsubscribed(st)
        self.assertSequenceEqual(
            mock.mock_calls,
            [
                unittest.mock.call(st)
            ]
        )

    def test_handle_unsubscribe_emits_event(self):
        st = stanza.Presence(
            type_=structs.PresenceType.UNSUBSCRIBE,
            from_=TEST_JID
        )

        mock = unittest.mock.Mock()
        self.s.on_unsubscribe.connect(mock)
        self.s.handle_unsubscribe(st)
        self.assertSequenceEqual(
            mock.mock_calls,
            [
                unittest.mock.call(st)
            ]
        )

    def test_approve_sends_subscribed_presence(self):
        self.s.approve(TEST_JID)

        self.assertSequenceEqual(
            self.cc.enqueue.mock_calls,
            [
                unittest.mock.call(unittest.mock.ANY),
            ]
        )

        call, = self.cc.enqueue.mock_calls
        _, call_args, _ = call

        st, = call_args
        self.assertIsInstance(st, stanza.Presence)
        self.assertEqual(st.to, TEST_JID)
        self.assertEqual(st.type_, structs.PresenceType.SUBSCRIBED)

    def test_subscribe_sends_subscribe_presence(self):
        self.s.subscribe(TEST_JID)

        self.assertSequenceEqual(
            self.cc.enqueue.mock_calls,
            [
                unittest.mock.call(unittest.mock.ANY),
            ]
        )

        call, = self.cc.enqueue.mock_calls
        _, call_args, _ = call

        st, = call_args
        self.assertIsInstance(st, stanza.Presence)
        self.assertEqual(st.to, TEST_JID)
        self.assertEqual(st.type_, structs.PresenceType.SUBSCRIBE)

    def test_unsubscribe_sends_unsubscribe_presence(self):
        self.s.unsubscribe(TEST_JID)

        self.assertSequenceEqual(
            self.cc.enqueue.mock_calls,
            [
                unittest.mock.call(unittest.mock.ANY),
            ]
        )

        call, = self.cc.enqueue.mock_calls
        _, call_args, _ = call

        st, = call_args
        self.assertIsInstance(st, stanza.Presence)
        self.assertEqual(st.to, TEST_JID)
        self.assertEqual(st.type_, structs.PresenceType.UNSUBSCRIBE)

    def test_do_not_lose_update_during_initial_roster(self):
        self.cc.mock_calls.clear()

        initial = roster_xso.Query(
            items=[
                roster_xso.Item(
                    jid=self.user2,
                    name="some bar user",
                    subscription="both"
                )
            ],
            ver="foobar"
        )

        push = stanza.IQ(
            type_=structs.IQType.SET,
            payload=roster_xso.Query(
                items=[
                    roster_xso.Item(
                        jid=self.user1,
                        name="some foo user",
                    ),
                    roster_xso.Item(
                        jid=self.user2,
                        subscription="remove",
                    )
                ],
                ver="foobar"
            )
        )

        async def send(iq, timeout=None):
            # this is brutal, but a sure way to provoke the race
            asyncio.ensure_future(self.s.handle_roster_push(push))
            # give the roster push a chance to act
            # (we cannot await the handle_roster_push() here: in the fixed
            # version that would be a deadlock)
            await asyncio.sleep(0)
            return initial

        self.cc.send = unittest.mock.Mock()
        self.cc.send.side_effect = send

        initial_roster = asyncio.ensure_future(
            self.cc.before_stream_established()
        )

        run_coroutine(initial_roster)

        self.assertNotIn(
            self.user2,
            self.s.items,
            "initial roster processing lost a race against roster push"
        )
