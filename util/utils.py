import io
import os

from specs.gnmi import gnmi_pb2

# gNMI encoding mapper
GNMI_ENCODING_TO_STR = {
    gnmi_pb2.JSON_IETF: "json_ietf",
    gnmi_pb2.JSON: "json",
    gnmi_pb2.PROTO: "proto",
    gnmi_pb2.ASCII: "ascii",
    gnmi_pb2.BYTES: "bytes",
}

def str_to_bytes(text: str, encoding: str = "utf-8") -> bytes:
    """
    Convert a string into a byte stream.

    Args:
        text (str): The input string to convert.
        encoding (str): Character encoding to use (default: UTF-8).

    Returns:
        io.BytesIO: A byte stream containing the encoded string.
    """

    if not isinstance(text, str):
        raise TypeError("input must be a string")
    
    try:
        byte_data = text.encode(encoding)
    except LookupError:
        raise ValueError(f'Unknown encoding: {encoding}')
    
    return byte_data

def read_payload(value: str) -> str:
    """
    Checks if the provided string is a valid file path.
    If it is, returns the file contents (great for XML configs/filters).
    Otherwise, returns the string as-is.
    """
    if value and os.path.isfile(value):
        try:
            with open(value, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception as e:
            print(f"[CLI Warning] Failed to read payload file '{value}': {e}")
    return value