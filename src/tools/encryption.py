import os
import re
import binascii
from typing import Optional, Dict

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from secrets import token_bytes

# Default to this if env variable is not set
DEFAULT_ENCRYPTION_KEY = (
    "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
)

ENCRYPTION_KEY = os.getenv("CLIENT_IP_ENCRYPTION_KEY", DEFAULT_ENCRYPTION_KEY)
ALGORITHM = "AES-256-CBC"  # Just for reference


def validate_encryption_key(key: str) -> bool:
    """Validates the key is exactly 64 hex characters (32 bytes)."""
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", key))


def encrypt_client_ip(client_ip: str) -> str:
    """Encrypt the client IP using AES-256-CBC and return iv:ciphertext in hex."""
    if not validate_encryption_key(ENCRYPTION_KEY):
        print("Invalid encryption key format. Must be 64 hex characters.")
        return client_ip  # Fallback to plain IP

    try:
        key_bytes = binascii.unhexlify(ENCRYPTION_KEY)
        iv = token_bytes(16)

        cipher = Cipher(
            algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend()
        )
        encryptor = cipher.encryptor()

        # Pad to 16-byte block size (PKCS7-style)
        pad_len = 16 - (len(client_ip.encode("utf-8")) % 16)
        padded_ip = client_ip + chr(pad_len) * pad_len
        encrypted = encryptor.update(padded_ip.encode("utf-8")) + encryptor.finalize()

        return f"{iv.hex()}:{encrypted.hex()}"
    except Exception as e:
        print(f"Error encrypting client IP: {e}")
        return client_ip  # Fallback


def generate_headers(
    client_ip: Optional[str] = None, extra_headers: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    headers = extra_headers.copy() if extra_headers else {}
    if client_ip:
        headers["mcp-client-ip"] = encrypt_client_ip(client_ip)
    return headers
