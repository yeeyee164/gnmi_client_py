import io

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