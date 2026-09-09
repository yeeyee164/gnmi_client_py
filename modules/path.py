# -*- encoding: utf-8 -*-
"""
path.py

It checks given string-typed paths to transform protocol-understandable data such as:
* gNMI Path defined from gnmi.proto.
* XML data for NETCONF
* else...


All of functions related gNMI are referenced at https://github.com/openconfig/gnmic
"""


import re
from typing import List, Optional, Dict, Tuple
try:
    from specs.gnmi.gnmi_pb2 import Path, PathElem
except ImportError:
    Path = None
    PathElem = None

# Custom Exceptions to match Go errors
class MalformedXPathError(Exception): pass
class MalformedXPathKeyError(Exception): pass
class EmptyPathElemNameError(Exception): pass

def create_prefix(prefix: str, target: str) -> Optional[Path]:
    """Creates a gnmi.Path out of a prefix and an optional target."""
    if not prefix and not target:
        return None
    
    try:
        p = parse_path(prefix)
    except Exception as e:
        raise e
    
    if target:
        p.target = target
    return p

def parse_path(p_str: str) -> Path:
    """
    Parses a path string into a gnmi.Path. 
    Supports origin:path format (e.g., "openconfig:/interfaces/interface").
    """
    if not p_str:
        return Path()

    origin = ""
    # Check for origin: prefix
    if ":" in p_str:
        idx = p_str.find(":")
        # Logic: not starting with '/', no '/' before ':', and is either end of string or followed by '/'
        if p_str[0] != '/' and '/' not in p_str[:idx]:
            if idx + 1 == len(p_str) or p_str[idx+1] == '/':
                origin = p_str[:idx]
                p_str = p_str[idx+1:]

    elems = to_path_elems(p_str)
    return Path(origin=origin, elem=elems)

def to_path_elems(p_str: str) -> List[PathElem]:
    """Parses the xpath part of the string into a list of PathElem."""
    if not p_str:
        return []

    # Ensure path ends with / for consistent splitting
    if not p_str.endswith('/'):
        p_str += '/'

    prev_c = ''
    in_key = False
    
    # We use a placeholder to handle '/' inside brackets (escaped or otherwise)
    placeholder = '\x00'
    result_chars = []

    for r in p_str:
        if r == '[':
            if in_key and prev_c != '\\':
                raise MalformedXPathError("malformed xpath")
            if prev_c != '\\':
                in_key = True
        elif r == ']':
            if not in_key and prev_c != '\\':
                raise MalformedXPathError("malformed xpath")
            if prev_c != '\\':
                in_key = False
        elif r == '/':
            if not in_key:
                result_chars.append(placeholder)
                prev_c = r
                continue
        
        result_chars.append(r)
        prev_c = r

    if in_key:
        raise MalformedXPathError("malformed xpath")

    # Split by placeholder and process each element
    string_elems = "".join(result_chars).split(placeholder)
    p_elems = []
    for s in string_elems:
        if not s:
            continue
        p_elems.append(to_path_elem(s))
    
    return p_elems

def to_path_elem(s: str) -> PathElem:
    """Parses a single element like 'interfaces[name=eth0]'."""
    idx = -1
    prev_c = ''
    # find a starting point of key
    for i, r in enumerate(s):
        if r == '[' and prev_c != '\\':
            idx = i
            break
        prev_c = r

    kvs = None
    if idx > 0:
        kvs = parse_xpath_keys(s[idx:])
        s = s[:idx]
    elif idx == 0:
        raise EmptyPathElemNameError("empty path element name")

    if not s:
        raise EmptyPathElemNameError("empty path element name")

    return PathElem(name=s, key=kvs if kvs else {})

def parse_xpath_keys(s: str) -> Dict[str, str]:
    """Parses keys [k1=v1][k2=v2] into a dictionary."""
    if not s:
        return {}

    kvs = {}
    in_key = False
    start = 0
    prev_c = ''

    for i, r in enumerate(s):
        if r == '[':
            if prev_c == '\\':
                prev_c = r
                continue
            if in_key:
                raise MalformedXPathKeyError("malformed xpath key")
            in_key = True
            start = i + 1
        elif r == ']':
            if prev_c == '\\':
                prev_c = r
                continue
            if not in_key:
                raise MalformedXPathKeyError("malformed xpath key")
            
            content = s[start:i]
            if '=' not in content:
                raise MalformedXPathKeyError("malformed xpath key")
            
            k, v = content.split('=', 1)
            if not k or not v:
                raise MalformedXPathKeyError("malformed xpath key")
            
            # Replace escaped brackets: \] -> ] and \[ -> [
            k = k.replace(r'\]', ']').replace(r'\[', '[')
            v = v.replace(r'\]', ']').replace(r'\[', '[')
            kvs[k] = v
            in_key = False
        else:
            if not in_key:
                raise MalformedXPathKeyError("malformed xpath key")
        prev_c = r

    if in_key:
        raise MalformedXPathKeyError("malformed xpath key")
    
    return kvs

def gnmi_path_to_xpath(p: Path, no_keys: bool = False) -> str:
    """Converts a gnmi.Path object back into an xpath string."""
    if not p:
        return ""

    parts = []
    if p.origin:
        parts.append(f"{p.origin}:/")
    
    elem_strings = []
    for pe in p.elem:
        s = pe.name
        if not no_keys and pe.key:
            # Sort keys alphabetically to match Go's sort.Strings(keys)
            sorted_keys = sorted(pe.key.keys())
            for k in sorted_keys:
                s += f"[{k}={pe.key[k]}]"
        elem_strings.append(s)
    
    path_str = "/".join(elem_strings)
    
    # Handle the joining of origin and elements
    if parts and path_str:
        return parts[0] + path_str
    elif parts:
        return parts[0]
    return path_str
