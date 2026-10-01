import os
import sys
import unittest
from unittest.mock import MagicMock
from dataclasses import FrozenInstanceError

# Ensure project root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import (
    Protocol,
    OutputFormat,
    OutputType,
    OutputConfig,
    ConnectionConfig,
    ExecutionConfig,
    SessionConfig,
    Selector,
    PathSelector,
    FilterSelector,
    DeliveryMode,
    DeliveryPolicy,
    OperationConfig,
    CapabilitiesOperation,
    GetSchemaOperation,
    GetOperation,
    ChangeType,
    Change,
    SetOperation,
    SubscribeOperation,
    GNMIOptions,
    GnmiOptions,
    BaseProtocolOptions,
    NetconfOptions,
    RootConfig,
    DeliveryConfig,
    SelectorConfig,
)
from modules.security import SecurityProfile


class TestConfigModels(unittest.TestCase):

    def test_protocol_enum(self):
        self.assertEqual(Protocol.GNMI, "gnmi")
        self.assertEqual(Protocol.NETCONF, "netconf")
        self.assertEqual(Protocol.RESTCONF, "restconf")

    def test_connection_config_and_target_properties(self):
        conn = ConnectionConfig(target="192.168.1.1:9339", username="admin", password="pwd")
        self.assertEqual(conn.target_ip, "192.168.1.1")
        self.assertEqual(conn.target_port, 9339)
        self.assertEqual(conn.username, "admin")
        self.assertFalse(conn.insecure)

        # IPv6 target
        conn_v6 = ConnectionConfig(target="[2001:db8::1]:830")
        self.assertEqual(conn_v6.target_ip, "2001:db8::1")
        self.assertEqual(conn_v6.target_port, 830)

        # Hostname target without port
        conn_host = ConnectionConfig(target="router.local")
        self.assertEqual(conn_host.target_ip, "router.local")
        self.assertEqual(conn_host.target_port, 0)

        # Immutability
        with self.assertRaises(FrozenInstanceError):
            conn.username = "new_admin"

    def test_execution_config(self):
        exec_cfg = ExecutionConfig(timeout=60, times=3)
        self.assertEqual(exec_cfg.timeout, 60)
        self.assertEqual(exec_cfg.times, 3)
        self.assertEqual(exec_cfg.retry_count, 0)

        with self.assertRaises(FrozenInstanceError):
            exec_cfg.timeout = 10

    def test_selectors(self):
        # PathSelector with list
        ps1 = PathSelector(paths=["/interfaces/interface", "/system"])
        self.assertEqual(ps1.paths, ("/interfaces/interface", "/system"))
        self.assertEqual(ps1.prefix, "")

        # PathSelector with string
        ps2 = PathSelector(paths="/interfaces/interface", prefix="/openconfig")
        self.assertEqual(ps2.paths, ("/interfaces/interface",))
        self.assertEqual(ps2.prefix, "/openconfig")

        # FilterSelector
        fs = FilterSelector(expression="<filter/>", filter_type="subtree")
        self.assertEqual(fs.expression, "<filter/>")
        self.assertEqual(fs.filter_type, "subtree")

        with self.assertRaises(FrozenInstanceError):
            ps1.prefix = "change"

    def test_delivery_policy(self):
        dp = DeliveryPolicy(mode=DeliveryMode.ON_CHANGE, interval=10, heartbeat=30, suppress_redundant=True)
        self.assertEqual(dp.mode, DeliveryMode.ON_CHANGE)
        self.assertEqual(dp.interval, 10)
        self.assertEqual(dp.heartbeat, 30)
        self.assertTrue(dp.suppress_redundant)

        with self.assertRaises(FrozenInstanceError):
            dp.interval = 5

    def test_operations_and_changes(self):
        # Capabilities
        cap = CapabilitiesOperation()
        self.assertIsInstance(cap, OperationConfig)

        # GetSchema
        schema_op = GetSchemaOperation(identifier="ietf-interfaces", version="2018-02-20")
        self.assertEqual(schema_op.identifier, "ietf-interfaces")
        self.assertEqual(schema_op.version, "2018-02-20")
        self.assertEqual(schema_op.format, "yang")

        # GetOperation
        get_op = GetOperation(selector=PathSelector(paths=["/interfaces"]), read_scope="config")
        self.assertEqual(get_op.read_scope, "config")
        self.assertEqual(get_op.selector.paths, ("/interfaces",))

        # Change & SetOperation
        c1 = Change(path="/interfaces/interface[name=eth0]/config/enabled", operation=ChangeType.MERGE, value=True)
        c2 = Change(path="/interfaces/interface[name=eth1]", operation=ChangeType.DELETE)
        set_op = SetOperation(changes=[c1, c2])
        self.assertEqual(len(set_op.changes), 2)
        self.assertEqual(set_op.changes[0].operation, ChangeType.MERGE)
        self.assertEqual(set_op.changes[1].operation, ChangeType.DELETE)

        # SubscribeOperation
        sub_op = SubscribeOperation(
            selector=PathSelector(paths=["/interfaces"]),
            delivery=DeliveryPolicy(mode=DeliveryMode.PERIODIC, interval=5),
            subscription_name="test_sub"
        )
        self.assertEqual(sub_op.subscription_name, "test_sub")
        self.assertEqual(sub_op.delivery.mode, DeliveryMode.PERIODIC)

    def test_protocol_options(self):
        gnmi_opts = GNMIOptions(encoding="proto", updates_only=True)
        self.assertEqual(gnmi_opts.encoding, "proto")
        self.assertTrue(gnmi_opts.updates_only)

        nc_opts = NetconfOptions(target_datastore="running", default_operation="replace")
        self.assertEqual(nc_opts.target_datastore, "running")
        self.assertEqual(nc_opts.default_operation, "replace")

    def test_polymorphic_protocol_options_and_root_config(self):
        # Base class inheritance and to_dict
        gnmi_opts = GnmiOptions(
            encoding="json_ietf",
            sub_mode="sample",
            sample_interval_ns=1000000,
            heartbeat_interval_ns=5000000,
            suppress_redundant=True,
        )
        self.assertIsInstance(gnmi_opts, BaseProtocolOptions)
        gnmi_opts.validate()
        d = gnmi_opts.to_dict()
        self.assertEqual(d["encoding"], "json_ietf")
        self.assertEqual(d["sub_mode"], "sample")
        self.assertEqual(d["sample_interval_ns"], 1000000)

        # GnmiOptions validation errors
        with self.assertRaises(ValueError):
            GnmiOptions(encoding="invalid_enc").validate()
        with self.assertRaises(ValueError):
            GnmiOptions(sub_mode="invalid_mode").validate()
        with self.assertRaises(ValueError):
            GnmiOptions(sample_interval_ns=-1).validate()
        with self.assertRaises(ValueError):
            GnmiOptions(heartbeat_interval_ns=-1).validate()

        # NetconfOptions inheritance, synchronization, and to_dict
        nc_opts = NetconfOptions(
            target_datastore="candidate",
            source="running",
            default_operation="merge",
            error_option="stop-on-error",
            lock_target=True,
        )
        self.assertIsInstance(nc_opts, BaseProtocolOptions)
        self.assertEqual(nc_opts.source_datastore, "running")
        nc_opts.validate()
        nc_dict = nc_opts.to_dict()
        self.assertEqual(nc_dict["target_datastore"], "candidate")
        self.assertTrue(nc_dict["lock_target"])

        # NetconfOptions validation errors
        with self.assertRaises(ValueError):
            NetconfOptions(target_datastore="invalid_ds").validate()
        with self.assertRaises(ValueError):
            NetconfOptions(source="invalid_source").validate()
        with self.assertRaises(ValueError):
            NetconfOptions(default_operation="invalid_op").validate()
        with self.assertRaises(ValueError):
            NetconfOptions(error_option="invalid_err").validate()

        # RootConfig validation
        root_cfg = RootConfig(
            delivery=DeliveryConfig(mode=DeliveryMode.PERIODIC, interval=10),
            operation=SubscribeOperation(
                selector=PathSelector(paths=["/interfaces"]),
                delivery=DeliveryPolicy(),
                protocol_options=gnmi_opts,
            ),
            selectors=[SelectorConfig()],
            protocol_options=gnmi_opts,
        )
        root_cfg.validate()

        # RootConfig invalid protocol_options triggers ValueError
        root_invalid = RootConfig(
            protocol_options=GnmiOptions(sample_interval_ns=-10)
        )
        with self.assertRaises(ValueError):
            root_invalid.validate()

    def test_session_config_delegation(self):
        conn = ConnectionConfig(target="10.0.0.1:9339", username="admin", password="pwd", insecure=True)
        op = CapabilitiesOperation()
        exec_cfg = ExecutionConfig(times=2)
        session = SessionConfig(
            connection=conn,
            protocol=Protocol.GNMI,
            operation=op,
            execution=exec_cfg
        )

        self.assertEqual(session.target, "10.0.0.1:9339")
        self.assertEqual(session.target_ip, "10.0.0.1")
        self.assertEqual(session.target_port, 9339)
        self.assertEqual(session.username, "admin")
        self.assertEqual(session.password, "pwd")
        self.assertTrue(session.insecure)
        self.assertEqual(session.times, 2)
        self.assertEqual(session.protocol, Protocol.GNMI)
        self.assertIs(session.operation, op)

        with self.assertRaises(FrozenInstanceError):
            session.protocol = Protocol.NETCONF


class TestClientSemanticExecution(unittest.TestCase):
    def test_gnmi_client_execute_capabilities(self):
        from specs.gnmi_client import GNMIClient
        client = GNMIClient(target="10.0.0.1:9339", insecure=True)
        client.stub = MagicMock()
        cap_op = CapabilitiesOperation()
        client.execute_capabilities(cap_op)
        client.stub.Capabilities.assert_called_once()

    def test_gnmi_client_execute_get(self):
        from specs.gnmi_client import GNMIClient
        client = GNMIClient(target="10.0.0.1:9339", insecure=True)
        client.stub = MagicMock()
        get_op = GetOperation(
            selector=PathSelector(paths=["/interfaces/interface[name=eth0]"], prefix="/openconfig"),
            read_scope="config",
            protocol_options=GNMIOptions(encoding="json")
        )
        client.execute_get(get_op)
        client.stub.Get.assert_called_once()
        req = client.stub.Get.call_args[0][0]
        self.assertEqual(len(req.path), 1)

    def test_gnmi_client_execute_set(self):
        from specs.gnmi_client import GNMIClient
        client = GNMIClient(target="10.0.0.1:9339", insecure=True)
        client.stub = MagicMock()
        set_op = SetOperation(changes=[
            Change(path="/interfaces/interface[name=eth0]/config/description", operation=ChangeType.MERGE, value="Test"),
            Change(path="/interfaces/interface[name=eth1]", operation=ChangeType.DELETE),
            Change(path="/interfaces/interface[name=eth2]/config", operation=ChangeType.REPLACE, value={"enabled": True}),
        ])
        client.execute_set(set_op)
        client.stub.Set.assert_called_once()
        req = client.stub.Set.call_args[0][0]
        self.assertEqual(len(req.update), 1)
        self.assertEqual(len(req.delete), 1)
        self.assertEqual(len(req.replace), 1)

    def test_netconf_client_execute_capabilities(self):
        from specs.netconf_client import NetconfClient
        client = NetconfClient(target="10.0.0.1:830", username="admin", password="pwd")
        mock_session = MagicMock()
        mock_session.server_capabilities = ["urn:ietf:params:netconf:base:1.0"]
        client.session = mock_session
        res = client.execute_capabilities(CapabilitiesOperation())
        self.assertEqual(res, ["urn:ietf:params:netconf:base:1.0"])

    def test_netconf_client_execute_get_config(self):
        from specs.netconf_client import NetconfClient
        client = NetconfClient(target="10.0.0.1:830", username="admin", password="pwd")
        mock_session = MagicMock()
        client.session = mock_session
        get_op = GetOperation(
            selector=FilterSelector(expression="<filter/>"),
            read_scope="config",
            protocol_options=NetconfOptions(source="running")
        )
        client.execute_get(get_op)
        mock_session.get_config.assert_called_once_with(source="running", filter="<filter/>")

    def test_netconf_client_execute_schema(self):
        from specs.netconf_client import NetconfClient
        client = NetconfClient(target="10.0.0.1:830", username="admin", password="pwd")
        mock_session = MagicMock()
        client.session = mock_session
        schema_op = GetSchemaOperation(identifier="ietf-interfaces", version="2018-02-20", format="yang")
        client.execute_schema(schema_op)
        mock_session.get_schema.assert_called_once_with(identifier="ietf-interfaces", version="2018-02-20", format=None)

    def test_netconf_client_execute_set(self):
        from specs.netconf_client import NetconfClient
        client = NetconfClient(target="10.0.0.1:830", username="admin", password="pwd")
        mock_session = MagicMock()
        mock_session.server_capabilities = [
            'urn:ietf:params:netconf:base:1.0',
            'urn:ietf:params:netconf:capability:candidate:1.0'
        ]
        client.session = mock_session
        set_op = SetOperation(
            changes=[Change(path="/test", operation=ChangeType.MERGE, value="<test>val</test>")],
            protocol_options=NetconfOptions(target_datastore="candidate", commit=True)
        )
        client.execute_set(set_op)
        mock_session.edit_config.assert_called_once()
        mock_session.commit.assert_called_once()


class TestWorkersAndManagersSemanticIntegration(unittest.TestCase):
    def test_manager_factory_with_semantic_sessions(self):
        from managers.manager import ManagerFactory, UnaryManager, SubscriptionManager
        from ui.cmd import ParsedConfig

        conn = ConnectionConfig(target="10.0.0.1:9339")
        get_sess = SessionConfig(connection=conn, protocol=Protocol.GNMI, operation=GetOperation(selector=PathSelector(paths=["/interfaces"])))
        sub_sess = SessionConfig(
            connection=conn,
            protocol=Protocol.GNMI,
            operation=SubscribeOperation(
                selector=PathSelector(paths=["/interfaces"]),
                delivery=DeliveryPolicy(mode=DeliveryMode.PERIODIC, interval=10)
            )
        )
        parsed = ParsedConfig(
            sessions=[get_sess, sub_sess],
            outputs=[OutputConfig(
                format = OutputFormat.JSON,
                output_type = OutputType.STDOUT,
            )],
        )
        managers, handlers = ManagerFactory.create_managers(parsed)
        self.assertEqual(len(managers), 2)
        self.assertIsInstance(managers[0], UnaryManager)
        self.assertIsInstance(managers[1], SubscriptionManager)

    def test_unary_manager_worker_resolution_semantic(self):
        from managers.manager import UnaryManager
        from managers.unary_worker import GetWorker, SetWorker, CapabilityWorker

        conn = ConnectionConfig(target="10.0.0.1:9339")
        get_sess = SessionConfig(connection=conn, protocol=Protocol.GNMI, operation=GetOperation(selector=PathSelector(paths=["/interfaces"])))
        set_sess = SessionConfig(connection=conn, protocol=Protocol.GNMI, operation=SetOperation(changes=[Change(path="/test", operation=ChangeType.MERGE, value="val")]))
        cap_sess = SessionConfig(connection=conn, protocol=Protocol.GNMI, operation=CapabilitiesOperation())

        mgr = UnaryManager(sessions=[get_sess, set_sess, cap_sess], output_handlers=[MagicMock()])
        mgr.build_sessions()

        self.assertEqual(len(mgr.sessions), 3)
        self.assertIsInstance(mgr.sessions[0], GetWorker)
        self.assertIsInstance(mgr.sessions[1], SetWorker)
        self.assertIsInstance(mgr.sessions[2], CapabilityWorker)

    def test_set_worker_semantic_execution(self):
        from managers.unary_worker import SetWorker

        conn = ConnectionConfig(target="10.0.0.1:9339", insecure=True)
        set_sess = SessionConfig(
            connection=conn,
            protocol=Protocol.GNMI,
            operation=SetOperation(changes=[Change(path="/interfaces/interface[name=eth0]/config", operation=ChangeType.MERGE, value="active")])
        )
        worker = SetWorker(config=set_sess)
        with unittest.mock.patch.object(worker, '_get_client') as mock_get_client:
            mock_client = MagicMock()
            mock_client.execute_set.return_value = "SET_SUCCESS"
            mock_get_client.return_value.__enter__.return_value = mock_client
            res = worker.start()
            self.assertEqual(res['data'], "SET_SUCCESS")
            mock_client.execute_set.assert_called_once_with(set_sess.operation)

    def test_subscribe_session_poll_mode(self):
        from managers.subscribe_session import SubscribeSession

        conn = ConnectionConfig(target="10.0.0.1:9339")
        sub_sess_periodic = SessionConfig(
            connection=conn,
            protocol=Protocol.GNMI,
            operation=SubscribeOperation(
                selector=PathSelector(paths=["/interfaces"]),
                delivery=DeliveryPolicy(mode=DeliveryMode.PERIODIC)
            )
        )
        sub_sess_poll = SessionConfig(
            connection=conn,
            protocol=Protocol.GNMI,
            operation=SubscribeOperation(
                selector=PathSelector(paths=["/interfaces"]),
                delivery=DeliveryPolicy(mode=DeliveryMode.POLL)
            )
        )
        s1 = SubscribeSession(config=sub_sess_periodic)
        s2 = SubscribeSession(config=sub_sess_poll)
        self.assertFalse(s1.is_poll_mode())
        self.assertTrue(s2.is_poll_mode())


if __name__ == "__main__":
    unittest.main()


