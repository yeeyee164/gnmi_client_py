import os
import sys
import unittest
from unittest.mock import MagicMock, patch

try:
    import pytest
except ImportError:
    pytest = None

# Ensure project root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Provide mock fallback for external protocol transport libraries if not installed in the environment
for m in [
    'grpc', 'ncclient', 'ncclient.manager',
    'specs.gnmi.gnmi_pb2', 'specs.gnmi.gnmi_pb2_grpc',
    'google', 'google.protobuf', 'google.protobuf.text_format',
    'xmltodict', 'lxml', 'lxml.etree'
]:
    if m not in sys.modules:
        try:
            __import__(m)
        except ImportError:
            mock_obj = MagicMock()
            if m == 'grpc':
                mock_obj.__version__ = '1.78.0'
                mock_util = MagicMock()
                mock_util.first_version_is_lower = lambda v1, v2: False
                sys.modules['grpc._utilities'] = mock_util
            elif m == 'specs.gnmi.gnmi_pb2':
                mock_obj.JSON_IETF = 4
                mock_obj.JSON = 0
                mock_obj.PROTO = 2
                mock_obj.ASCII = 3
                mock_obj.BYTES = 1
            sys.modules[m] = mock_obj

from ui.cmd import (
    BaseSessionConfig,
    BaseCapabilitiesConfig,
    BaseGetConfig,
    BaseSetConfig,
    BaseSubscribeConfig,
    GNMICapabilitiesConfig,
    GNMIGetConfig,
    GNMISetConfig,
    GNMISubscribeConfig,
    NetconfCapabilitiesConfig,
    NetconfGetConfig,
    NetconfEditConfig,
    NetconfSubscribeConfig,
    SESSION_CONFIG_REGISTRY,
    create_session_config,
    SessionConfig,
    GNMISessionConfig,
    NetconfSessionConfig,
    ParsedConfig,
)
from managers.manager import BaseRPCManager, UnaryManager, SubscriptionManager, ManagerFactory
from managers.unary_worker import BaseUnaryWorker, GetWorker, SetWorker, CapabilityWorker
from managers.subscribe_session import SubscribeSession


class TestSessionConfigTargetParsing(unittest.TestCase):
    def test_ipv4_target_parsing(self):
        cfg = BaseSessionConfig(target='192.168.1.10:9339')
        self.assertEqual(cfg.target_ip, '192.168.1.10')
        self.assertEqual(cfg.target_port, 9339)

    def test_ipv6_target_parsing(self):
        cfg = BaseSessionConfig(target='[2001:db8::1]:9339')
        self.assertEqual(cfg.target_ip, '2001:db8::1')
        self.assertEqual(cfg.target_port, 9339)

    def test_no_port_target_parsing(self):
        cfg = BaseSessionConfig(target='router1.net')
        self.assertEqual(cfg.target_ip, 'router1.net')
        self.assertEqual(cfg.target_port, 0)


def build_sample_sessions():
    get_session_1 = GNMIGetConfig(
        target='10.0.0.1:9339', operation='get', protocol='gnmi',
        paths=['/interfaces/interface[name=eth0]']
    )
    get_session_2 = GNMIGetConfig(
        target='10.0.0.2:9339', operation='get', protocol='gnmi',
        paths=['/system/config']
    )
    set_session = GNMISetConfig(
        target='10.0.0.3:9339', operation='set', protocol='gnmi',
        updates=[('/system/config/hostname', 'router3')]
    )
    cap_session = GNMICapabilitiesConfig(
        target='10.0.0.4:9339', operation='capability', protocol='gnmi'
    )
    sub_session_1 = GNMISubscribeConfig(
        target='10.0.0.5:9339', operation='subscribe', protocol='gnmi',
        subscription_name='sub_telemetry', paths=['/interfaces/...']
    )
    sub_session_2 = GNMISubscribeConfig(
        target='10.0.0.6:9339', operation='poll', protocol='gnmi',
        subscription_name='sub_poll', paths=['/components/...']
    )

    return {
        'get_1': get_session_1,
        'get_2': get_session_2,
        'set': set_session,
        'cap': cap_session,
        'sub_1': sub_session_1,
        'sub_2': sub_session_2,
        'all': [get_session_1, get_session_2, set_session, cap_session, sub_session_1, sub_session_2],
    }


def build_parsed_config(sample_sessions):
    outputs = {
        'default_output': {
            'type': 'file',
            'file-type': 'stdout',
            'format': 'json'
        }
    }
    return ParsedConfig(
        sessions=sample_sessions['all'],
        outputs=outputs,
        targets=[
            '10.0.0.1:9339', '10.0.0.2:9339', '10.0.0.3:9339',
            '10.0.0.4:9339', '10.0.0.5:9339', '10.0.0.6:9339'
        ],
        debug=False
    )


if pytest:
    @pytest.fixture
    def sample_sessions():
        return build_sample_sessions()

    @pytest.fixture
    def parsed_config(sample_sessions):
        return build_parsed_config(sample_sessions)


class TestManagerSessionScoping(unittest.TestCase):
    def setUp(self):
        self.sample_sessions = build_sample_sessions()
        self.parsed_config = build_parsed_config(self.sample_sessions)

    def test_manager_factory_partitioning(self):
        managers, handlers = ManagerFactory.create_managers(self.parsed_config)

        self.assertEqual(len(managers), 2)
        self.assertIsInstance(managers[0], UnaryManager)
        self.assertIsInstance(managers[1], SubscriptionManager)

        unary_mgr = managers[0]
        self.assertEqual(len(unary_mgr.session_configs), 4)
        self.assertEqual([s.operation for s in unary_mgr.session_configs], ['get', 'get', 'set', 'capability'])

        sub_mgr = managers[1]
        self.assertEqual(len(sub_mgr.session_configs), 2)
        self.assertEqual([s.operation for s in sub_mgr.session_configs], ['subscribe', 'poll'])

    def test_unary_manager_build_sessions_dispatch(self):
        unary_sessions = [self.sample_sessions['get_1'], self.sample_sessions['set'], self.sample_sessions['cap']]
        mock_handler = MagicMock()
        mgr = UnaryManager(sessions=unary_sessions, output_handlers=[mock_handler])

        mgr.build_sessions()

        self.assertEqual(len(mgr.sessions), 3)
        self.assertIsInstance(mgr.sessions[0], GetWorker)
        self.assertEqual(mgr.sessions[0].config, self.sample_sessions['get_1'])
        self.assertEqual(mgr.sessions[0].target_ip, '10.0.0.1')
        self.assertEqual(mgr.sessions[0].target_port, 9339)

        self.assertIsInstance(mgr.sessions[1], SetWorker)
        self.assertEqual(mgr.sessions[1].config, self.sample_sessions['set'])
        self.assertEqual(mgr.sessions[1].target_ip, '10.0.0.3')
        self.assertEqual(mgr.sessions[1].updates, [('/system/config/hostname', 'router3')])

        self.assertIsInstance(mgr.sessions[2], CapabilityWorker)
        self.assertEqual(mgr.sessions[2].config, self.sample_sessions['cap'])
        self.assertEqual(mgr.sessions[2].target_ip, '10.0.0.4')

    def test_subscription_manager_build_sessions(self):
        sub_sessions = [self.sample_sessions['sub_1'], self.sample_sessions['sub_2']]
        mock_handler = MagicMock()
        mgr = SubscriptionManager(sessions=sub_sessions, output_handlers=[mock_handler])

        mgr.build_sessions()

        self.assertEqual(len(mgr.sessions), 2)
        for s in mgr.sessions:
            self.assertIsInstance(s, SubscribeSession)

        self.assertEqual(mgr.sessions[0].config, self.sample_sessions['sub_1'])
        self.assertEqual(mgr.sessions[0].target_ip, '10.0.0.5')
        self.assertEqual(mgr.sessions[0].subscription_name, 'sub_telemetry')

        self.assertEqual(mgr.sessions[1].config, self.sample_sessions['sub_2'])
        self.assertEqual(mgr.sessions[1].target_ip, '10.0.0.6')
        self.assertEqual(mgr.sessions[1].subscription_name, 'sub_poll')

    def test_output_handlers_centralized_lifecycle(self):
        mock_mgr_unary = MagicMock(spec=UnaryManager)
        mock_mgr_sub = MagicMock(spec=SubscriptionManager)
        mock_handler = MagicMock()

        with patch.object(ManagerFactory, 'create_managers', return_value=([mock_mgr_unary, mock_mgr_sub], [mock_handler])):
            ManagerFactory.execute(self.parsed_config)

            mock_mgr_unary.run_all.assert_called_once()
            mock_mgr_sub.run_all.assert_called_once()
            mock_handler.close.assert_called_once()


class TestPerRPCSessionConfigHierarchy(unittest.TestCase):
    def test_attribute_isolation_gnmi(self):
        cap_cfg = GNMICapabilitiesConfig(target="10.0.0.1:9339")
        self.assertFalse(hasattr(cap_cfg, 'paths'))
        self.assertFalse(hasattr(cap_cfg, 'updates'))
        self.assertFalse(hasattr(cap_cfg, 'sample_interval'))

        get_cfg = GNMIGetConfig(target="10.0.0.1:9339", paths=["/interfaces"])
        self.assertEqual(get_cfg.paths, ["/interfaces"])
        self.assertFalse(hasattr(get_cfg, 'updates'))
        self.assertFalse(hasattr(get_cfg, 'sample_interval'))

        set_cfg = GNMISetConfig(target="10.0.0.1:9339", updates=[("/path", "val")])
        self.assertEqual(set_cfg.updates, [("/path", "val")])
        self.assertFalse(hasattr(set_cfg, 'paths'))
        self.assertFalse(hasattr(set_cfg, 'sample_interval'))

        sub_cfg = GNMISubscribeConfig(target="10.0.0.1:9339", sample_interval=30)
        self.assertEqual(sub_cfg.sample_interval, 30)
        self.assertFalse(hasattr(sub_cfg, 'updates'))

    def test_create_session_config_filtering(self):
        # Passing extraneous kwargs should be safely filtered
        cfg = create_session_config(
            "gnmi", "capability",
            target="10.0.0.1:9339",
            paths=["/invalid"],
            updates=[("invalid", "val")],
            sample_interval=100
        )
        self.assertIsInstance(cfg, GNMICapabilitiesConfig)
        self.assertEqual(cfg.target, "10.0.0.1:9339")
        self.assertFalse(hasattr(cfg, 'paths'))
        self.assertFalse(hasattr(cfg, 'sample_interval'))

    def test_create_session_config_netconf(self):
        cap_cfg = create_session_config("netconf", "capability", target="10.0.0.1:830")
        self.assertIsInstance(cap_cfg, NetconfCapabilitiesConfig)

        get_cfg = create_session_config("netconf", "get-config", target="10.0.0.1:830", source="running", filter="<xml/>")
        self.assertIsInstance(get_cfg, NetconfGetConfig)
        self.assertEqual(get_cfg.source, "running")
        self.assertEqual(get_cfg.filter, "<xml/>")

        edit_cfg = create_session_config("netconf", "edit-config", target="10.0.0.1:830", target_datastore="candidate")
        self.assertIsInstance(edit_cfg, NetconfEditConfig)
        self.assertEqual(edit_cfg.target_datastore, "candidate")

        sub_cfg = create_session_config("netconf", "subscribe", target="10.0.0.1:830", stream_name="NETCONF")
        self.assertIsInstance(sub_cfg, NetconfSubscribeConfig)
        self.assertEqual(sub_cfg.stream_name, "NETCONF")

    def test_backward_compatibility_aliases(self):
        self.assertIs(SessionConfig, BaseSessionConfig)
        self.assertIs(GNMISessionConfig, BaseSessionConfig)
        self.assertIs(NetconfSessionConfig, BaseSessionConfig)


if __name__ == '__main__':
    unittest.main()
