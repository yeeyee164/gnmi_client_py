import sys
import unittest
from unittest.mock import MagicMock, patch

# Provide mock fallback for external protocol transport libraries if not installed in the environment
for m in [
    'grpc', 'ncclient', 'ncclient.manager',
    'specs.gnmi.gnmi_pb2', 'specs.gnmi.gnmi_pb2_grpc',
    'google', 'google.protobuf', 'google.protobuf.text_format',
    'xmltodict', 'lxml', 'lxml.etree'
]:
    if m not in sys.modules:
        mock_obj = MagicMock()
        if m == 'grpc':
            mock_obj.__version__ = '1.50.0'
        elif m == 'specs.gnmi.gnmi_pb2':
            mock_obj.JSON_IETF = 4
            mock_obj.JSON = 0
            mock_obj.PROTO = 2
            mock_obj.ASCII = 3
            mock_obj.BYTES = 1
        sys.modules[m] = mock_obj

from ui.cmd import BaseSessionConfig, GNMISessionConfig, NetconfSessionConfig, ParsedConfig
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


class TestManagerSessionScoping(unittest.TestCase):
    def setUp(self):
        self.get_session_1 = GNMISessionConfig(
            target='10.0.0.1:9339', operation='get', protocol='gnmi',
            paths=['/interfaces/interface[name=eth0]']
        )
        self.get_session_2 = GNMISessionConfig(
            target='10.0.0.2:9339', operation='get', protocol='gnmi',
            paths=['/system/config']
        )
        self.set_session = GNMISessionConfig(
            target='10.0.0.3:9339', operation='set', protocol='gnmi',
            updates=[('/system/config/hostname', 'router3')]
        )
        self.cap_session = GNMISessionConfig(
            target='10.0.0.4:9339', operation='capability', protocol='gnmi'
        )
        self.sub_session_1 = GNMISessionConfig(
            target='10.0.0.5:9339', operation='subscribe', protocol='gnmi',
            subscription_name='sub_telemetry', paths=['/interfaces/...']
        )
        self.sub_session_2 = GNMISessionConfig(
            target='10.0.0.6:9339', operation='poll', protocol='gnmi',
            subscription_name='sub_poll', paths=['/components/...']
        )

        self.all_sessions = [
            self.get_session_1,
            self.get_session_2,
            self.set_session,
            self.cap_session,
            self.sub_session_1,
            self.sub_session_2
        ]

        self.outputs = {
            'default_output': {
                'type': 'file',
                'file-type': 'stdout',
                'format': 'json'
            }
        }

        self.parsed_config = ParsedConfig(
            sessions=self.all_sessions,
            outputs=self.outputs,
            targets=[
                '10.0.0.1:9339', '10.0.0.2:9339', '10.0.0.3:9339',
                '10.0.0.4:9339', '10.0.0.5:9339', '10.0.0.6:9339'
            ],
            debug=False
        )

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
        unary_sessions = [self.get_session_1, self.set_session, self.cap_session]
        mock_handler = MagicMock()
        mgr = UnaryManager(sessions=unary_sessions, output_handlers=[mock_handler])

        mgr.build_sessions()

        self.assertEqual(len(mgr.sessions), 3)
        self.assertIsInstance(mgr.sessions[0], GetWorker)
        self.assertEqual(mgr.sessions[0].config, self.get_session_1)
        self.assertEqual(mgr.sessions[0].target_ip, '10.0.0.1')
        self.assertEqual(mgr.sessions[0].target_port, 9339)

        self.assertIsInstance(mgr.sessions[1], SetWorker)
        self.assertEqual(mgr.sessions[1].config, self.set_session)
        self.assertEqual(mgr.sessions[1].target_ip, '10.0.0.3')
        self.assertEqual(mgr.sessions[1].updates, [('/system/config/hostname', 'router3')])

        self.assertIsInstance(mgr.sessions[2], CapabilityWorker)
        self.assertEqual(mgr.sessions[2].config, self.cap_session)
        self.assertEqual(mgr.sessions[2].target_ip, '10.0.0.4')

    def test_subscription_manager_build_sessions(self):
        sub_sessions = [self.sub_session_1, self.sub_session_2]
        mock_handler = MagicMock()
        mgr = SubscriptionManager(sessions=sub_sessions, output_handlers=[mock_handler])

        mgr.build_sessions()

        self.assertEqual(len(mgr.sessions), 2)
        for s in mgr.sessions:
            self.assertIsInstance(s, SubscribeSession)

        self.assertEqual(mgr.sessions[0].config, self.sub_session_1)
        self.assertEqual(mgr.sessions[0].target_ip, '10.0.0.5')
        self.assertEqual(mgr.sessions[0].subscription_name, 'sub_telemetry')

        self.assertEqual(mgr.sessions[1].config, self.sub_session_2)
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


if __name__ == '__main__':
    unittest.main()
