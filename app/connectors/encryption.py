import base64
import hashlib
from cryptography.fernet import Fernet
from app.config import settings

def _get_fernet_key() -> bytes:
    """Derives a deterministic 32-byte urlsafe base64 key from settings.connector_secret_key."""
    raw_key = settings.connector_secret_key.encode("utf-8")
    digest = hashlib.sha256(raw_key).digest()
    return base64.urlsafe_b64encode(digest)

def encrypt_token(plain_text: str) -> str:
    """Encrypts a plaintext session token or credential string into a secure ciphertext."""
    if not plain_text:
        return ""
    fernet = Fernet(_get_fernet_key())
    return fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")

def decrypt_token(cipher_text: str) -> str:
    """Decrypts a ciphertext into the original plaintext session token."""
    if not cipher_text:
        return ""
    fernet = Fernet(_get_fernet_key())
    return fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
