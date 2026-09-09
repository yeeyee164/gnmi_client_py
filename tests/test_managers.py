import os
import sys
import pytest
from unittest.mock import MagicMock, patch

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


class TestSessionConfigTargetParsing:
    def test_ipv4_target_parsing(self):
        cfg = BaseSessionConfig(target='192.168.1.10:9339')
        assert cfg.target_ip == '192.168.1.10'
        assert cfg.target_port == 9339

    def test_ipv6_target_parsing(self):
        cfg = BaseSessionConfig(target='[2001:db8::1]:9339')
        assert cfg.target_ip == '2001:db8::1'
        assert cfg.target_port == 9339

    def test_no_port_target_parsing(self):
        cfg = BaseSessionConfig(target='router1.net')
        assert cfg.target_ip == 'router1.net'
        assert cfg.target_port == 0


@pytest.fixture
def sample_sessions():
    get_session_1 = GNMISessionConfig(
        target='10.0.0.1:9339', operation='get', protocol='gnmi',
        paths=['/interfaces/interface[name=eth0]']
    )
    get_session_2 = GNMISessionConfig(
        target='10.0.0.2:9339', operation='get', protocol='gnmi',
        paths=['/system/config']
    )
    set_session = GNMISessionConfig(
        target='10.0.0.3:9339', operation='set', protocol='gnmi',
        updates=[('/system/config/hostname', 'router3')]
    )
    cap_session = GNMISessionConfig(
        target='10.0.0.4:9339', operation='capability', protocol='gnmi'
    )
    sub_session_1 = GNMISessionConfig(
        target='10.0.0.5:9339', operation='subscribe', protocol='gnmi',
        subscription_name='sub_telemetry', paths=['/interfaces/...']
    )
    sub_session_2 = GNMISessionConfig(
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


@pytest.fixture
def parsed_config(sample_sessions):
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


class TestManagerSessionScoping:
    def test_manager_factory_partitioning(self, parsed_config):
        managers, handlers = ManagerFactory.create_managers(parsed_config)

        assert len(managers) == 2
        assert isinstance(managers[0], UnaryManager)
        assert isinstance(managers[1], SubscriptionManager)

        unary_mgr = managers[0]
        assert len(unary_mgr.session_configs) == 4
        assert [s.operation for s in unary_mgr.session_configs] == ['get', 'get', 'set', 'capability']

        sub_mgr = managers[1]
        assert len(sub_mgr.session_configs) == 2
        assert [s.operation for s in sub_mgr.session_configs] == ['subscribe', 'poll']

    def test_unary_manager_build_sessions_dispatch(self, sample_sessions):
        unary_sessions = [sample_sessions['get_1'], sample_sessions['set'], sample_sessions['cap']]
        mock_handler = MagicMock()
        mgr = UnaryManager(sessions=unary_sessions, output_handlers=[mock_handler])

        mgr.build_sessions()

        assert len(mgr.sessions) == 3
        assert isinstance(mgr.sessions[0], GetWorker)
        assert mgr.sessions[0].config == sample_sessions['get_1']
        assert mgr.sessions[0].target_ip == '10.0.0.1'
        assert mgr.sessions[0].target_port == 9339

        assert isinstance(mgr.sessions[1], SetWorker)
        assert mgr.sessions[1].config == sample_sessions['set']
        assert mgr.sessions[1].target_ip == '10.0.0.3'
        assert mgr.sessions[1].updates == [('/system/config/hostname', 'router3')]

        assert isinstance(mgr.sessions[2], CapabilityWorker)
        assert mgr.sessions[2].config == sample_sessions['cap']
        assert mgr.sessions[2].target_ip == '10.0.0.4'

    def test_subscription_manager_build_sessions(self, sample_sessions):
        sub_sessions = [sample_sessions['sub_1'], sample_sessions['sub_2']]
        mock_handler = MagicMock()
        mgr = SubscriptionManager(sessions=sub_sessions, output_handlers=[mock_handler])

        mgr.build_sessions()

        assert len(mgr.sessions) == 2
        for s in mgr.sessions:
            assert isinstance(s, SubscribeSession)

        assert mgr.sessions[0].config == sample_sessions['sub_1']
        assert mgr.sessions[0].target_ip == '10.0.0.5'
        assert mgr.sessions[0].subscription_name == 'sub_telemetry'

        assert mgr.sessions[1].config == sample_sessions['sub_2']
        assert mgr.sessions[1].target_ip == '10.0.0.6'
        assert mgr.sessions[1].subscription_name == 'sub_poll'

    def test_output_handlers_centralized_lifecycle(self, parsed_config):
        mock_mgr_unary = MagicMock(spec=UnaryManager)
        mock_mgr_sub = MagicMock(spec=SubscriptionManager)
        mock_handler = MagicMock()

        with patch.object(ManagerFactory, 'create_managers', return_value=([mock_mgr_unary, mock_mgr_sub], [mock_handler])):
            ManagerFactory.execute(parsed_config)

            mock_mgr_unary.run_all.assert_called_once()
            mock_mgr_sub.run_all.assert_called_once()
            mock_handler.close.assert_called_once()
