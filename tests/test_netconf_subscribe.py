import os
import sys
import time
import threading
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.protocol_options.netconf import NetconfOptions
from config.selectors import PathSelector, FilterSelector
from config.operations import SubscribeOperation
from config.delivery import DeliveryPolicy, DeliveryMode
from config.model import Protocol, SessionConfig
from specs.base_client import UnsupportedOperationError
from specs.stream_types import StreamContext, StreamEvent
from specs.netconf_client import NetconfClient
from specs.netconf_validator import NetconfValidator
from modules.validate import PathValidationError
from ui.cmd import build_args, parse_args


class DummyNotification:
    def __init__(self, xml_content: str, event_time: str = "2026-10-14T12:00:00Z"):
        self.notification_xml = xml_content
        self.event_time = event_time


class TestNetconfOptionsSubscription:
    def test_valid_default_options(self):
        opts = NetconfOptions()
        opts.validate()
        assert opts.stream_name == "NETCONF"
        assert opts.start_time is None
        assert opts.stop_time is None
        assert opts.poll_timeout == 1.0

    def test_valid_replay_options(self):
        opts = NetconfOptions(
            stream_name="ALARMS",
            start_time="2026-10-14T10:00:00Z",
            stop_time="2026-10-14T12:00:00Z",
            poll_timeout=0.5,
        )
        opts.validate()
        assert opts.stream_name == "ALARMS"
        assert opts.start_time == "2026-10-14T10:00:00Z"
        assert opts.stop_time == "2026-10-14T12:00:00Z"
        assert opts.poll_timeout == 0.5

    def test_stop_time_without_start_time_fails(self):
        opts = NetconfOptions(stop_time="2026-10-14T12:00:00Z")
        with pytest.raises(ValueError, match="RFC 5277 constraint violation"):
            opts.validate()

    def test_stop_time_before_start_time_fails(self):
        opts = NetconfOptions(
            start_time="2026-10-14T12:00:00Z",
            stop_time="2026-10-14T10:00:00Z",
        )
        with pytest.raises(ValueError, match="must be strictly later"):
            opts.validate()

    def test_stop_time_equal_start_time_fails(self):
        opts = NetconfOptions(
            start_time="2026-10-14T12:00:00Z",
            stop_time="2026-10-14T12:00:00Z",
        )
        with pytest.raises(ValueError, match="must be strictly later"):
            opts.validate()

    def test_invalid_poll_timeout_fails(self):
        opts = NetconfOptions(poll_timeout=0.0)
        with pytest.raises(ValueError, match="Invalid poll_timeout"):
            opts.validate()

        opts_neg = NetconfOptions(poll_timeout=-1.5)
        with pytest.raises(ValueError, match="Invalid poll_timeout"):
            opts_neg.validate()


class TestNetconfFilterBuilding:
    def test_filter_building(self):
        client = NetconfClient(target="127.0.0.1:830")

        # None selector
        assert client._build_subscription_filter(None) is None

        # FilterSelector xpath
        sel_xpath = FilterSelector(expression="/interfaces/interface", filter_type="xpath")
        assert client._build_subscription_filter(sel_xpath) == ("xpath", "/interfaces/interface")

        # FilterSelector subtree
        sel_sub = FilterSelector(expression="<interfaces/>", filter_type="subtree")
        assert client._build_subscription_filter(sel_sub) == "<interfaces/>"

        # PathSelector single xpath
        sel_p1 = PathSelector(paths=("/interfaces/interface[name='eth0']",))
        assert client._build_subscription_filter(sel_p1) == ("xpath", "/interfaces/interface[name='eth0']")

        # PathSelector xml string
        sel_pxml = PathSelector(paths=("<interfaces><interface/></interfaces>",))
        assert client._build_subscription_filter(sel_pxml) == "<interfaces><interface/></interfaces>"

        # String selector
        assert client._build_subscription_filter("<filter/>") == "<filter/>"
        assert client._build_subscription_filter("/system/state") == ("xpath", "/system/state")


class TestNetconfEventTimeParsing:
    def test_parse_event_time_to_posix(self):
        client = NetconfClient(target="127.0.0.1:830")

        # Standard Z suffix
        ts = client._parse_event_time_to_posix("2026-10-14T12:00:00Z")
        assert isinstance(ts, float)
        assert ts > 0

        # Offset suffix
        ts_offset = client._parse_event_time_to_posix("2026-10-14T12:00:00+00:00")
        assert ts_offset == ts

        # Fallback for None or invalid
        now = time.time()
        fallback_none = client._parse_event_time_to_posix(None)
        assert abs(fallback_none - now) < 5

        fallback_bad = client._parse_event_time_to_posix("invalid-timestamp")
        assert abs(fallback_bad - now) < 5


class TestNetconfClientExecuteSubscribe:
    def test_missing_notification_capability_raises(self):
        client = NetconfClient(target="127.0.0.1:830")
        mock_session = MagicMock()
        mock_session.server_capabilities = [
            "urn:ietf:params:netconf:base:1.0",
            "urn:ietf:params:netconf:base:1.1",
        ]
        client.session = mock_session

        context = StreamContext()
        with pytest.raises(UnsupportedOperationError, match="does not support RFC 5277"):
            client.execute_subscribe(context=context)

    def test_continuous_stream_notifications(self):
        client = NetconfClient(target="127.0.0.1:830")
        mock_session = MagicMock()
        mock_session.server_capabilities = [
            "urn:ietf:params:netconf:base:1.0",
            "urn:ietf:params:netconf:capability:notification:1.0",
        ]
        mock_reply = MagicMock()
        mock_reply.ok = True
        mock_session.create_subscription.return_value = mock_reply

        notif1 = DummyNotification(
            '<notification xmlns="urn:ietf:params:xml:ns:netconf:notification:1.0">'
            '<eventTime>2026-10-14T12:00:00Z</eventTime>'
            '<linkDown xmlns="urn:test"><ifIndex>1</ifIndex></linkDown>'
            '</notification>',
            event_time="2026-10-14T12:00:00Z"
        )
        notif2 = DummyNotification(
            '<notification xmlns="urn:ietf:params:xml:ns:netconf:notification:1.0">'
            '<eventTime>2026-10-14T12:00:05Z</eventTime>'
            '<linkUp xmlns="urn:test"><ifIndex>1</ifIndex></linkUp>'
            '</notification>',
            event_time="2026-10-14T12:00:05Z"
        )

        # Return notif1, notif2, then None
        mock_session.take_notification.side_effect = [notif1, notif2, None, None]
        client.session = mock_session

        context = StreamContext()
        gen = client.execute_subscribe(context=context)

        # First event
        ev1 = next(gen)
        assert isinstance(ev1, StreamEvent)
        assert ev1.protocol == "netconf"
        assert "<linkDown" in ev1.raw_payload
        assert ev1.data is not None
        assert not ev1.is_sync_marker

        # Second event
        ev2 = next(gen)
        assert isinstance(ev2, StreamEvent)
        assert "<linkUp" in ev2.raw_payload

        # Cancel context to terminate loop cleanly
        context.cancel()
        with pytest.raises(StopIteration):
            next(gen)

    def test_bounded_replay_with_completion(self):
        client = NetconfClient(target="127.0.0.1:830")
        mock_session = MagicMock()
        mock_session.server_capabilities = [
            "urn:ietf:params:netconf:base:1.0",
            "urn:ietf:params:netconf:capability:notification:1.0",
        ]
        mock_reply = MagicMock()
        mock_reply.ok = True
        mock_session.create_subscription.return_value = mock_reply

        notif_data = DummyNotification(
            '<notification xmlns="urn:ietf:params:xml:ns:netconf:notification:1.0">'
            '<eventTime>2026-10-14T10:05:00Z</eventTime>'
            '<eventData>Sample</eventData>'
            '</notification>'
        )
        notif_replay_done = DummyNotification(
            '<notification xmlns="urn:ietf:params:xml:ns:netconf:notification:1.0">'
            '<eventTime>2026-10-14T10:10:00Z</eventTime>'
            '<replayComplete/>'
            '</notification>'
        )
        notif_complete = DummyNotification(
            '<notification xmlns="urn:ietf:params:xml:ns:netconf:notification:1.0">'
            '<eventTime>2026-10-14T10:10:00Z</eventTime>'
            '<notificationComplete/>'
            '</notification>'
        )

        mock_session.take_notification.side_effect = [notif_data, notif_replay_done, notif_complete]
        client.session = mock_session

        opts = NetconfOptions(start_time="2026-10-14T10:00:00Z", stop_time="2026-10-14T10:10:00Z")
        op = SubscribeOperation(
            selector=PathSelector(paths=()),
            delivery=DeliveryPolicy(mode=DeliveryMode.EVENT_DRIVEN),
            protocol_options=opts,
        )

        events = list(client.execute_subscribe(operation=op))
        assert len(events) == 3
        assert not events[0].is_sync_marker
        assert events[1].is_sync_marker  # <replayComplete/> sets is_sync_marker=True
        assert "<notificationComplete" in events[2].raw_payload

    def test_create_subscription_rpc_error(self):
        client = NetconfClient(target="127.0.0.1:830")
        mock_session = MagicMock()
        mock_session.server_capabilities = [
            "urn:ietf:params:netconf:capability:notification:1.0",
        ]
        mock_session.create_subscription.side_effect = Exception("Transport error on create-subscription")
        client.session = mock_session

        events = list(client.execute_subscribe())
        assert len(events) == 1
        assert events[0].error is not None
        assert "Transport error" in str(events[0].error)


class TestNetconfValidatorSubscription:
    def test_validate_subscription(self):
        val = NetconfValidator()

        # Valid
        val.validate_subscription(stream_name="NETCONF")
        val.validate_subscription(
            stream_name="NETCONF",
            start_time="2026-10-14T10:00:00Z",
            stop_time="2026-10-14T12:00:00Z",
            filter_str="<interfaces/>",
            filter_type="subtree"
        )

        # Empty stream name
        with pytest.raises(PathValidationError, match="stream_name cannot be empty"):
            val.validate_subscription(stream_name="")

        # Stop without start
        with pytest.raises(PathValidationError, match="stop_time cannot be specified without start_time"):
            val.validate_subscription(stop_time="2026-10-14T12:00:00Z")

        # Stop <= start
        with pytest.raises(PathValidationError, match="must be strictly later than start_time"):
            val.validate_subscription(start_time="2026-10-14T12:00:00Z", stop_time="2026-10-14T10:00:00Z")


class TestNetconfCLISubscribe:
    def test_cli_netconf_subscribe_parsing(self):
        args = [
            "-t", "10.0.0.1:830",
            "-u", "admin",
            "-p", "admin",
            "netconf",
            "subscribe",
            "--stream", "ALARMS",
            "--start-time", "2026-10-14T00:00:00Z",
            "--stop-time", "2026-10-14T01:00:00Z",
            "--filter", "<alarms/>",
            "--poll-timeout", "2.5",
        ]
        parsed = parse_args(args)
        assert len(parsed.sessions) == 1
        sess = parsed.sessions[0]
        assert sess.protocol == Protocol.NETCONF
        assert isinstance(sess.operation, SubscribeOperation)
        assert sess.operation.subscription_name == "ALARMS"
        assert sess.operation.delivery.mode == DeliveryMode.EVENT_DRIVEN

        po = sess.operation.protocol_options
        assert isinstance(po, NetconfOptions)
        assert po.stream_name == "ALARMS"
        assert po.start_time == "2026-10-14T00:00:00Z"
        assert po.stop_time == "2026-10-14T01:00:00Z"
        assert po.poll_timeout == 2.5

    def test_yaml_netconf_subscribe_parsing(self):
        args = ["netconf", "-c", "tests/netconf_subscribe_test.yaml"]
        parsed = parse_args(args)
        assert len(parsed.sessions) == 1
        sess = parsed.sessions[0]
        assert sess.protocol == Protocol.NETCONF
        assert sess.connection.target == "172.20.20.2:830"
        assert isinstance(sess.operation, SubscribeOperation)
        assert sess.operation.subscription_name == "srl_alarms"
        assert sess.operation.delivery.mode == DeliveryMode.EVENT_DRIVEN

        po = sess.operation.protocol_options
        assert isinstance(po, NetconfOptions)
        assert po.stream_name == "NETCONF"
        assert po.start_time == "2026-10-14T00:00:00Z"
        assert po.stop_time == "2026-10-14T12:00:00Z"
        assert po.poll_timeout == 1.0



@pytest.mark.live
class TestLiveNokiaSRLinuxNetconfSubscription:
    """
    Live target verification against Nokia SR Linux (172.20.20.2:830).
    Verifies that NetconfClient connects, examines server capabilities, and
    raises UnsupportedOperationError because Nokia SR Linux does not advertise
    RFC 5277 :notification:1.0.
    """
    def test_live_srl_notification_capability_check(self):
        client = NetconfClient(
            target="172.20.20.2:830",
            username="admin",
            password="NokiaSrl1!",
        )

        # Enter client context manager to connect
        with client:
            assert client.session is not None
            assert client.session.connected

            # Verify that Nokia SR Linux server capabilities do not have :notification:1.0
            server_caps = list(client.session.server_capabilities)
            has_notification_cap = any("urn:ietf:params:netconf:capability:notification:1.0" in c for c in server_caps)
            assert not has_notification_cap, "Nokia SR Linux should not advertise RFC 5277 :notification:1.0"

            # Verify execute_subscribe correctly catches missing capability and raises UnsupportedOperationError
            context = StreamContext()
            with pytest.raises(UnsupportedOperationError, match="does not support RFC 5277"):
                client.execute_subscribe(context=context)
