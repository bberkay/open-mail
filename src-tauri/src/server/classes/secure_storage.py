from __future__ import annotations
import base64
import copy
import os
import json
import time
import ast
from enum import Enum
from typing import TypedDict, Any, cast

import keyring
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes

from utils import safe_json_loads
from consts import APP_NAME

"""
Exceptions
"""
class AESGCMCipherNotInitializedError(Exception):
    def __init__(self, msg: str = "AESGCMCipher is not initialized.", *args, **kwargs):
        super().__init__(msg, *args, **kwargs)

class RSACipherNotInitializedError(Exception):
    def __init__(self, msg: str = "RSACipher is not initialized.", *args, **kwargs):
        super().__init__(msg, *args, **kwargs)

class NoPublicPemFoundError(Exception):
    def __init__(self, msg: str = "No public pem key has found.", *args, **kwargs):
        super().__init__(msg, *args, **kwargs)

class NoPrivatePemFoundError(Exception):
    def __init__(self, msg: str = "No private pem key has found..", *args, **kwargs):
        super().__init__(msg, *args, **kwargs)

class InvalidSecureStorageKeyError(Exception):
    def __init__(self, msg: str = "Invalid secure storage key.", *args, **kwargs):
        super().__init__(msg, *args, **kwargs)

class InvalidSecureStorageKeyValueError(Exception):
    def __init__(self, msg: str = "Invalid secure storage key value.", *args, **kwargs):
        super().__init__(msg, *args, **kwargs)

class InvalidSecureStorageKeyValueTypeError(Exception):
    def __init__(self, msg: str = "Invalid secure storage key value type.", *args, **kwargs):
        super().__init__(msg, *args, **kwargs)

class IllegalAESGCMCipherAccessError(Exception):
    def __init__(self,
        msg: str = """Illegal AESGCMCipher access.
        Only accessible through `_get_password`, `_set_password`
        and/or `_delete_password`.""",
        *args,
        **kwargs
    ):
        super().__init__(msg, *args, **kwargs)

"""
Enums, Types
"""
class SecureStorageKey(str, Enum):
    # AESGCM Keys
    AESGCMCipherKey = "aesgcm_cipher_key"
    AESGCMCipherKeyBackup = "aesgcm_cipher_key_backup"

    # RSA Keys
    PublicPem = "public_pem"
    PrivatePem = "private_pem"
    PublicPemBackup = "public_pem_backup"
    PrivatePemBackup = "private_pem_backup"

    # RSA Encrypted Keys
    Accounts = "accounts"

    @classmethod
    def keys(cls) -> list[str]:
        return [key.value for key in cls]

    def __str__(self) -> str:
        return self.value

class SecureStorageKeyValueType(str, Enum):
    AESGCMKey = "aesgcm_key"
    RSAKey = "rsa_key"
    RSAEncryptedKey = "rsa_encrypted_key"
    PlainKey = "plain_key"

    @classmethod
    def keys(cls) -> list[str]:
        return [key.value for key in cls]

    def __str__(self) -> str:
        return self.value

class SecureStorageKeyValue(TypedDict):
    value: Any
    type: SecureStorageKeyValueType
    created_at: float
    last_updated_at: float

"""
Constants
"""
SECURE_STORAGE_KEY_LIST = SecureStorageKey.keys()
SECURE_STORAGE_ILLEGAL_ACCESS_KEY_LIST = [
    SecureStorageKey.AESGCMCipherKey,
    SecureStorageKey.AESGCMCipherKeyBackup
]

# TTL in seconds
CACHE_TTL = 1800
ROTATE_KEY_TTL = 86400
ROTATE_FAILURE_TTL = ROTATE_KEY_TTL / 2

class SecureStorage:
    _instance = None
    _cache: SecureStorageCache
    _encryptor: AESGCMCipher

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._cache = SecureStorageCache()
            cls._instance._init_aesgcm_cipher()
            cls._instance._init_rsa_cipher()

        return cls._instance

    def __del__(self):
        self.clear()

    def _is_key_value_type_valid(self, key_value_type: SecureStorageKeyValueType):
        if key_value_type not in SecureStorageKeyValueType.keys():
            raise InvalidSecureStorageKeyValueTypeError(f"Invalid secure storage key value type: {key_value_type}")

    def _create_key_value_dict(self,
        key_value: str,
        key_value_type: SecureStorageKeyValueType,
        created_at: float | None = None,
        last_updated_at: float | None = None
    ) -> SecureStorageKeyValue:
        self._is_key_value_type_valid(key_value_type)
        return SecureStorageKeyValue(
            value=key_value,
            type=key_value_type,
            created_at=time.time() if created_at is None else float(created_at),
            last_updated_at=time.time() if last_updated_at is None else float(last_updated_at),
        )

    def _serialize_key_value_dict(self, key_value_dict: SecureStorageKeyValue) -> str:
        return json.dumps(key_value_dict)

    def _parse_key_value_dict(self, key_value: str) -> SecureStorageKeyValue | None:
        return safe_json_loads(key_value)

    def _is_key_valid(self, key: str | SecureStorageKey):
        if str(key) not in SECURE_STORAGE_KEY_LIST:
            raise InvalidSecureStorageKeyError(f"Invalid secure storage key: {key}")

    def _is_key_legal(self, key: str | SecureStorageKey):
        if str(key) in SECURE_STORAGE_ILLEGAL_ACCESS_KEY_LIST:
            raise IllegalAESGCMCipherAccessError(f"Access to {key} is denied: Legal key list is {",".join(SECURE_STORAGE_ILLEGAL_ACCESS_KEY_LIST)}")

    def _get_password(self, key: SecureStorageKey) -> SecureStorageKeyValue | None:
        self._is_key_valid(key)
        return self._parse_key_value_dict(keyring.get_password(APP_NAME, key) or "") or None

    def _set_password(self, key: SecureStorageKey, value: SecureStorageKeyValue) -> None:
        self._is_key_valid(key)
        keyring.set_password(APP_NAME, key, self._serialize_key_value_dict(value))

    def _delete_password(self, key: SecureStorageKey) -> None:
        self._is_key_valid(key)
        keyring.delete_password(APP_NAME, key)

    def _init_aesgcm_cipher(self) -> None:
        key = self._get_password(SecureStorageKey.AESGCMCipherKey)
        if not key:
            key = self._create_key_value_dict(os.urandom(32).hex(), SecureStorageKeyValueType.AESGCMKey)
            self._set_password(SecureStorageKey.AESGCMCipherKey, key)
            self._encryptor = AESGCMCipher(bytes.fromhex(key["value"]))
        else:
            self._encryptor = AESGCMCipher(bytes.fromhex(key["value"]))
            if key["last_updated_at"] + ROTATE_KEY_TTL < time.time():
                self._rotate_aesgcm_cipher()

    def _rotate_aesgcm_cipher(self) -> None:
        print("Rotating AESGCM cipher...")
        self.clear()

        aesgcm_cipher_key_backup = self._get_password(SecureStorageKey.AESGCMCipherKey)
        if not aesgcm_cipher_key_backup:
            raise AESGCMCipherNotInitializedError

        self._set_password(SecureStorageKey.AESGCMCipherKeyBackup, aesgcm_cipher_key_backup)

        temp_store = {}
        for key_name in SECURE_STORAGE_KEY_LIST:
            try:
                self._is_key_legal(key_name)
                key_value = self.get_key_value(cast(SecureStorageKey, key_name), use_cache=False)
                if key_value:
                    temp_store[key_name] = key_value
            except Exception as e:
                print(f"`{key_name}` value could not be retrieved. Skipping...")

        try:
            self._delete_password(SecureStorageKey.AESGCMCipherKey)
            self._init_aesgcm_cipher()
            for key_name, key_value in temp_store.items():
                self.update_key(key_name, key_value)

            print("AESGCM cipher rotation completed successfully.")
        except Exception as e:
            print("Rotation failed. Restoring AESGCM cipher key...",)

            aesgcm_cipher_key_backup["last_updated_at"] = time.time() - ROTATE_FAILURE_TTL
            self._set_password(SecureStorageKey.AESGCMCipherKey, aesgcm_cipher_key_backup)
            self._init_aesgcm_cipher()
            for key_name, key_value in temp_store.items():
                self.update_key(key_name, key_value)

            print("AESGCM cipher rotation completed unsuccessfully.")
            raise e
        finally:
            for key_name in temp_store.keys():
                temp_store[key_name] = None
            del temp_store

    def _init_rsa_cipher(self) -> None:
        private_pem = self._get_password(SecureStorageKey.PrivatePem)
        public_pem = self._get_password(SecureStorageKey.PublicPem)
        if not private_pem or not public_pem:
            rsa_cipher = RSACipher()
            self.update_key(
                SecureStorageKey.PrivatePem,
                self._create_key_value_dict(
                    rsa_cipher.get_private_pem(),
                    SecureStorageKeyValueType.RSAKey
                )
            )
            self.update_key(
                SecureStorageKey.PublicPem,
                self._create_key_value_dict(
                    rsa_cipher.get_public_pem(),
                    SecureStorageKeyValueType.RSAKey
                )
            )
        else:
            if private_pem["last_updated_at"] + ROTATE_KEY_TTL < time.time():
                self._rotate_rsa_cipher()
            elif public_pem["last_updated_at"] + ROTATE_KEY_TTL < time.time():
                self._rotate_rsa_cipher()

    def _rotate_rsa_cipher(self) -> None:
        print("Rotating RSA cipher...")
        self.clear()

        private_pem_backup = self.get_key_value(SecureStorageKey.PrivatePem, use_cache=False)
        public_pem_backup = self.get_key_value(SecureStorageKey.PublicPem, use_cache=False)
        if not private_pem_backup:
            raise NoPrivatePemFoundError
        if not public_pem_backup:
            raise NoPublicPemFoundError

        self.update_key(SecureStorageKey.PrivatePemBackup, private_pem_backup)
        self.update_key(SecureStorageKey.PublicPemBackup, public_pem_backup)

        temp_store = {}
        for key_name in SECURE_STORAGE_KEY_LIST:
            try:
                key_value = self.get_key_value(cast(SecureStorageKey, key_name), use_cache=False)
                if key_value and key_value["type"] == SecureStorageKeyValueType.RSAEncryptedKey:
                    temp_store[key_name] = RSACipher().decrypt_password(key_value["value"], private_pem_backup["value"])
            except Exception as e:
                print(f"`{key_name}` value could not be retrieved. Skipping...")

        try:
            self.delete_key(SecureStorageKey.PrivatePem)
            self.delete_key(SecureStorageKey.PublicPem)

            self._init_rsa_cipher()
            new_public_pem = self.get_key_value(SecureStorageKey.PublicPem, use_cache=False)
            if not new_public_pem:
                raise NoPublicPemFoundError
            for key_name, key_value in temp_store.items():
                key_value["value"] = RSACipher().encrypt_password(key_value["value"], new_public_pem["value"])
                self.update_key(key_name, key_value)

            print("RSA cipher rotation completed successfully.")
        except Exception as e:
            print("Rotation failed. Restoring RSA cipher key...")

            private_pem_backup["last_updated_at"] = time.time() - ROTATE_FAILURE_TTL
            self.update_key(SecureStorageKey.PrivatePem, private_pem_backup)
            public_pem_backup["last_updated_at"] = time.time() - ROTATE_FAILURE_TTL
            self.update_key(SecureStorageKey.PublicPem, public_pem_backup)

            self._init_rsa_cipher()
            for key_name, key_value in temp_store.items():
                key_value["value"] = RSACipher().encrypt_password(key_value["value"], public_pem_backup["value"])
                self.update_key(key_name, key_value)

            print("RSA cipher rotation completed unsuccessfully.")
            raise e
        finally:
            for key_name in temp_store.keys():
                temp_store[key_name] = None
            del temp_store

    def get_key_value(self,
        key_name: SecureStorageKey,
        associated_data: bytes | None = None,
        decrypt: bool = True,
        use_cache: bool = True
    ) -> SecureStorageKeyValue | None:
        self._is_key_valid(key_name)
        self._is_key_legal(key_name)

        key_value = self._cache.get(key_name) if use_cache else None
        if not key_value:
            key_value = self._get_password(key_name)
            if not key_value:
                return None
            if use_cache: self._cache.set(key_name, key_value)

        if decrypt:
            if self._encryptor:
                key_value["value"] = self._encryptor.decrypt(key_value["value"], associated_data)
            else:
                raise AESGCMCipherNotInitializedError

        return key_value

    def add_key(self,
        key_name: SecureStorageKey,
        value: Any,
        type: SecureStorageKeyValueType,
        associated_data: bytes | None = None
    ) -> None:
        if not self._encryptor:
            raise AESGCMCipherNotInitializedError

        self._is_key_legal(key_name)

        key_value = self._create_key_value_dict(value, type)
        key_value["value"] = self._encryptor.encrypt(key_value["value"], associated_data)
        self._set_password(key_name, key_value)
        self._cache.set(key_name, key_value)

    def update_key(self,
        key_name: SecureStorageKey,
        key_value: SecureStorageKeyValue,
        associated_data: bytes | None = None
    ) -> None:
        if not self._encryptor:
            raise AESGCMCipherNotInitializedError

        self.delete_key(key_name)

        if "last_updated_at" in key_value:
            key_value["last_updated_at"] = time.time()

        key_value["value"] = self._encryptor.encrypt(key_value["value"], associated_data)
        self._set_password(key_name, key_value)
        self._cache.set(key_name, key_value)

    def delete_key(self, key_name: SecureStorageKey) -> None:
        self._is_key_legal(key_name)
        self._delete_password(key_name)
        self._cache.delete(key_name)

    def clear(self) -> None:
        self._cache.destroy()

    def destroy(self) -> None:
        if self._cache:
            self._cache.destroy()

        for key in SECURE_STORAGE_KEY_LIST:
            try:
                self._delete_password(cast(SecureStorageKey, key))
            except keyring.errors.PasswordDeleteError:
                print(f"`{key}` could not found in keyring to delete. Skipping...")
                pass

class SecureStorageCache:
    class CachedData(TypedDict):
        data: SecureStorageKeyValue
        created_at: float

    _instance = None
    _store: dict[SecureStorageKey, CachedData]

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._store = {}

        return cls._instance

    def __del__(self):
        self.destroy()

    def _is_expired(self, timestamp: float) -> bool:
        return time.time() - timestamp > CACHE_TTL

    def get(self, key: SecureStorageKey) -> Any:
        if key not in self._store:
            return None

        store_data: SecureStorageCache.CachedData = self._store[key]
        if self._is_expired(store_data["created_at"]):
            self.delete(key)

        return copy.deepcopy(store_data["data"])

    def set(self, key: SecureStorageKey, value: SecureStorageKeyValue):
        self._store[key] = {
            "data": copy.deepcopy(value),
            "created_at": time.time()
        }

    def delete(self, key: SecureStorageKey):
        if key in self._store:
            random_bytes = os.urandom(len(str(self._store[key])))
            self._store[key] = random_bytes.hex()
            del self._store[key]

    def destroy(self):
        for key in list(self._store.keys()):
            self.delete(key)

        self._store = {}

class AESGCMCipher:
    def __init__(self, key: bytes):
        if len(key) not in [16, 24, 32]:
            raise ValueError("Key length must be 16, 24, or 32 bytes.")

        try:
            self._cipher = AESGCM(key)
        finally:
            random_bytes = os.urandom(len(str(key)))
            key = random_bytes.hex()

    def encrypt(self, plain_text: str, associated_data: bytes | None = None) -> str:
        if not isinstance(plain_text, str):
            plain_text = json.dumps(plain_text)

        nonce = os.urandom(12)
        cipher_text = self._cipher.encrypt(nonce, plain_text.encode(), associated_data)
        return base64.b64encode(nonce + cipher_text).decode('utf-8')

    def decrypt(self, encrypted_text: str, associated_data: bytes | None = None) -> str:
        if not isinstance(encrypted_text, str):
            encrypted_text = json.dumps(encrypted_text)

        encrypted_text = base64.b64decode(encrypted_text)
        nonce = encrypted_text[:12]
        cipher_text = encrypted_text[12:]
        return self._cipher.decrypt(nonce, cipher_text, associated_data).decode('utf-8')

class RSACipher:
    def __init__(self):
        self._create_private_key()
        self._create_public_key()

    def _create_private_key(self):
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self._private_pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

    def _create_public_key(self):
        if not self._private_key:
            raise RSACipherNotInitializedError

        self._public_key = self._private_key.public_key()
        self._public_pem = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

    def get_public_pem(self) -> str:
        return self._public_pem.decode("utf-8") if isinstance(self._public_pem, bytes) else self._public_pem

    def get_private_pem(self) -> str:
        return self._private_pem.decode("utf-8") if isinstance(self._private_pem, bytes) else self._private_pem

    @staticmethod
    def encrypt_password(
        plain_text_password: str,
        public_pem: str | bytes
    ) -> str:
        if isinstance(public_pem, str):
            public_pem = public_pem.encode('utf-8')

        if not isinstance(plain_text_password, str):
            plain_text_password = json.dumps(plain_text_password)

        public_key = serialization.load_pem_public_key(public_pem)
        encrypted_b64_password = public_key.encrypt(
            plain_text_password.encode("utf-8"),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        return base64.b64encode(encrypted_b64_password).decode("utf-8")

    @staticmethod
    def decrypt_password(
        encrypted_b64_password: str,
        private_pem: str | bytes
    ) -> str:
        if isinstance(private_pem, str):
            private_pem = private_pem.encode('utf-8')

        if not isinstance(encrypted_b64_password, str):
            encrypted_b64_password = json.dumps(encrypted_b64_password)

        private_key = serialization.load_pem_private_key(private_pem, password=None)
        return private_key.decrypt(
            base64.b64decode(encrypted_b64_password),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        ).decode("utf-8")

__all__ = [
    "SecureStorage",
    "SecureStorageKey",
    "AESGCMCipher",
    "RSACipher",
    "RSACipherNotInitializedError",
    "AESGCMCipherNotInitializedError",
    "InvalidSecureStorageKeyError",
    "IllegalAESGCMCipherAccessError"
]
