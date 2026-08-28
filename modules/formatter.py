import json
import base64
import datetime
from abc import ABC, abstractmethod

from google.protobuf import text_format
from modules.path import gnmi_path_to_xpath
from specs.gnmi.gnmi_pb2 import GetResponse, SetResponse, CapabilityResponse, SubscribeResponse
from util.utils import GNMI_ENCODING_TO_STR

class ProtocolFormatter(ABC):
    """
    Abstract base class for Protocl formatters

    Ensures that any future northbound protocol can securely
    translate its native payloads into standard representations.
    """

    @abstractmethod
    def format_json(self, raw_data):
        """Translates the native protocol data into JSON/Python dict"""
        pass

    @abstractmethod
    def format_text(self, raw_data):
        """
        Translates the native protocol data into text
        
        For all protocol except gNMI, it will prints exactly same format as
        that protocol intended.
        """
        pass

    @abstractmethod
    def format_xml(self, raw_data):
        """Translates the native protocol data into XML"""
        pass

# =====================
# gNMI output formatter
# =====================

class GNMIFormatter(ProtocolFormatter):
    """
    Handles gNMI-specific Protobuf translations, including RFC 7951 (json_ietf) 
    formatting and deeply-nested Base64 JSON decoding.
    """

    def extract_value(self, tv):
        """Safely extracts and unpacks a gnmi_pb2.TypedValue"""
        if tv.HasField('json_val'):
            try: return json.loads(tv.json_val.decode('utf-8'))
            except: return tv.json_val.decode('utf-8')
        elif tv.HasField('json_ietf_val'):
            try: return json.loads(tv.json_ietf_val.decode('utf-8'))
            except: return tv.json_ietf_val.decode('utf-8')
        elif tv.HasField('string_val'): return tv.string_val
        elif tv.HasField('int_val'): return tv.int_val
        elif tv.HasField('uint_val'): return tv.uint_val
        elif tv.HasField('bool_val'): return tv.bool_val
        elif tv.HasField('bytes_val'): return tv.bytes_val.hex()
        elif tv.HasField('float_val'): return tv.float_val
        elif tv.HasField('decimal_val'): return tv.decimal_val
        elif tv.HasField('leaflist_val'): 
            return [self.extract_value(e) for e in tv.leaflist_val.element]
        elif tv.HasField('any_val'): return str(tv.any_val)
        elif tv.HasField('ascii_val'): return tv.ascii_val
        return None
    
    def _format_get(self, resp: GetResponse, meta):
        """
        Formats a gNMI GetResponse.

        The `resp` object is expected to contain:
        - **Notification**:
            - timestamp
            - prefix
            - update (repeated): path, val (TypedValue), duplicates

        Supported Extensions (gnmi_ext.proto):
        - registered_ext, master_arbitration, history, commit, depth, config_subscription.
        """

        res = []
        # loop Notifications
        for notif in resp.notification:
            n_dict = {}
            if meta: n_dict.update(meta)

            n_dict['timestamp'] = notif.timestamp
            n_dict['time'] = datetime.datetime.fromtimestamp(notif.timestamp / 1e9, tz=datetime.timezone.utc).isoformat()
            if notif.HasField('prefix'):
                n_dict['prefix'] = gnmi_path_to_xpath(notif.prefix)

            n_dict['updates'] = []
            for upt in notif.update:
                p_str = gnmi_path_to_xpath(upt.path)
                p_str_no_key = gnmi_path_to_xpath(upt.path, no_keys=True)
                val = self.extract_value(upt.val)
                n_dict['updates'].append({
                    'Path': p_str,
                    'values': { p_str_no_key: val }
                })
            res.append(n_dict)
        return res

    def _format_set(self, resp:SetResponse, meta):
        """
        Formats a gNMI SetResponse.

        The `resp` object is expected to contain below:
        - **prefix**
        - **response**
            - path
            - op(Operation)
        - **timestamp**

        Supported extension(gnmi_ext.proto)
        - None

        """
        res = {}
        if meta: res.update(meta)

        res['timestamp'] = resp.timestamp
        op_map = {
            0: 'INVALID',
            1: 'DELETE',
            2: 'REPLACE',
            3: 'UPDATE',
        }

        for r in resp.response:
            res['responses'].append({
                'path': r.path,
                'op': op_map.get(r.op, str(r.op))
            })
        return res

    def _format_capability(self, resp: CapabilityResponse, meta):
        """
        Formats a gNMI CapabilityResponse.

        The `resp` object is expected to contain below:
        - **supported_models**
        - **supported_encoding**
        - **gNMI_version**

        Supported extension(gnmi_ext.proto)
        - None
        """

        res = {}
        if meta: res.update(meta)
        res['gNMI_version'] = resp.gNMI_version
        res['supported_models'] = []

        for m in resp.supported_models:
            res['supported_models'].append({
                'name': m.name,
                'organization': m.organization,
                'version': m.version
            })

        res['supported_encodings'] = [GNMI_ENCODING_TO_STR.get(e, str(e)).upper() 
                                      for e in resp.supported_encodings]
        return res

    def _format_subscribe(self, resp:SubscribeResponse, meta):
        """
        Formats a gNMI SubscribeResponse.

        The `resp` object is expected to contain one of the following:
        - **Notification**:
            - timestamp
            - prefix
            - update (repeated): path, val (TypedValue), duplicates
        - **sync_response**

        Supported Extensions (gnmi_ext.proto):
        - registered_ext, master_arbitration, history, commit, depth, config_subscription.
        """
        if resp.HasField('update'):
            # get Notification in Response
            notif = resp.update
            res = {}
            if meta:
                res.update(meta)

            res['timestamp'] = notif.timestamp
            res['time'] = datetime.datetime.fromtimestamp(notif.timestamp / 1e9, tz=datetime.timezone.utc).isoformat()

            if notif.HasField('prefix'):
                res['prefix'] = gnmi_path_to_xpath(notif.prefix)

            res['updates'] = []
            for upt in notif.update:
                p_str = gnmi_path_to_xpath(upt.path)
                p_str_no_key = gnmi_path_to_xpath(upt.path, no_keys=True)
                val = self.extract_value(upt.val)
                res['updates'].append({
                    'Path': p_str,
                    'values': { p_str_no_key: val }
                })

            # for ON_CHANGE notification
            res['deletes'] = [gnmi_path_to_xpath(d) for d in notif.delete]

            # cleanup fields 
            if len(res['updates']) == 0: res.pop('updates')
            if len(res['deletes']) == 0: res.pop('deletes')

            return res
        elif resp.HasField('sync_response'):
            res = {'sync_response': resp.sync_response}
            return res

        return {}

    def format_json(self, raw_data, rpc:str, meta=None):
        """
        format_json constructs gNMI 'Response' protobuf message into
        JSON-formatted string.
        
        All formats were depending on `rpc`.
        """

        rpc = rpc.lower()
        if rpc == 'subscribe':
            return self._format_subscribe(raw_data, meta)
        elif rpc == 'get':
            return self._format_get(raw_data, meta)
        if rpc == 'set':
            return self._format_set(raw_data, meta)
        if rpc == 'capability':
            return self._format_capability(raw_data, meta)

        # If it already forms dict/json, just return itself
        return str(raw_data)

    def format_text(self, raw_data):
        if hasattr(raw_data, 'DESCRIPTOR'):
            return text_format.MessageToString(raw_data)
        return str(raw_data)

    def format_xml(self, raw_data):
        raise NotImplementedError("Not supported yet!")

# ========================
# NETCONF output formatter(TODO)
# ========================

import xmltodict
import xml.dom.minidom

class NETCONFFormatter(ProtocolFormatter):
    """
    Custom parser that translates raw NETCONFF XML responses into clean dictionaries
    using xmltodict, matching the standard output style of the framework.
    """
    def format_json(self, raw_data, **meta):
        res = {}
        if meta:
            res.update(meta)

        rpc = res.get('rpc')

        if rpc == 'capability':
            res['data'] = raw_data

        # ncclient returns RPCReply objects
        xml_node = getattr(raw_data, 'xml', raw_data)

        # ncclient's RPCError stores the raw XML as an lxml Element
        if not isinstance(xml_node, str):
            try:
                # in response of <hello> message
                from lxml import etree
                if isinstance(xml_node, etree._Element):
                    xml_str = etree.tostring(xml_node, encoding='unicode')
                else:
                    xml_str = str(xml_node)
                parsed = xmltodict.parse(xml_str)
                res['data'] = parsed
            except Exception as e:
                res['data'] = str(xml_node)
                res['error'] = f"XML Parsing failed: {e}"

        return res

    def format_text(self, raw_data, **meta):
        """print the output AS-IS presented"""
        # ncclient returns RPCReply objects
        xml_node = getattr(raw_data, 'xml', raw_data)

        # ncclient's RPCError stores the raw XML as an lxml Element
        if not isinstance(xml_node, str):
            try:
                # in response of <hello> message
                from lxml import etree
                if isinstance(xml_node, etree._Element):
                    xml_str = etree.tostring(xml_node, encoding='unicode')
                else:
                    xml_str = str(xml_node)
            except Exception:
                xml_str = str(xml_node)
        
        return xml_str

    def format_xml(self, raw_data, **meta):
        """Uses minidom to return beautify indented XML."""
        rpc = meta.get('rpc')

        # in response of <hello> message
        if rpc == 'capability':
            return raw_data

        xml_str = getattr(raw_data, 'xml', str(raw_data))

        try:
            dom = xml.dom.minidom.parseString(xml_str)
            return dom.toprettyxml(indend='  ')
        except Exception:
            return xml_str