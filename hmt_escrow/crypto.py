# The MIT License (MIT)
#
# Copyright 2017-2019 Ethereum Foundation
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Source: https://github.com/ethereum/trinity/blob/master/p2p/ecies.py
import os
import struct
from hashlib import sha256
from typing import cast

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKeyWithSerialization,
)
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.constant_time import bytes_eq
from eth_keys import datatypes
from eth_keys import keys
from eth_utils import int_to_big_endian


# Length of public keys: 512 bit keys in uncompressed form, without format byte
PUBKEY_LEN = 64


class DecryptionError(Exception):
    """
    Raised when a message could not be decrypted.
    """

    pass


def pad32(value: bytes) -> bytes:
    return value.rjust(32, b"\x00")


CIPHER = algorithms.AES
MODE = modes.CTR
CURVE = ec.SECP256K1()
# ECIES using AES256 and HMAC-SHA-256-32
KEY_LEN = 32


class _InvalidPublicKey(Exception):
    """
    A custom exception raised when trying to convert bytes
    into an elliptic curve public key.
    """

    pass


def generate_privkey() -> datatypes.PrivateKey:
    """Generate a new SECP256K1 private key and return it"""
    privkey = cast(
        EllipticCurvePrivateKeyWithSerialization,
        ec.generate_private_key(CURVE, default_backend()),
    )
    return keys.PrivateKey(
        pad32(int_to_big_endian(privkey.private_numbers().private_value))
    )


def ecdh_agree(privkey: datatypes.PrivateKey, pubkey: datatypes.PublicKey) -> bytes:
    """Performs a key exchange operation using the ECDH algorithm."""
    privkey_as_int = int(cast(int, privkey))
    ec_privkey = ec.derive_private_key(privkey_as_int, CURVE, default_backend())
    pubkey_bytes = b"\x04" + pubkey.to_bytes()
    try:
        # either of these can raise a ValueError:
        pubkey_nums = ec.EllipticCurvePublicKey.from_encoded_point(CURVE, pubkey_bytes)
        ec_pubkey = pubkey_nums.public_numbers().public_key(default_backend())
    except ValueError as exc:
        # Not all bytes can be made into valid public keys, see the warning at
        # https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ec/
        # under EllipticCurvePublicNumbers(x, y)
        raise _InvalidPublicKey(str(exc)) from exc
    return ec_privkey.exchange(ec.ECDH(), ec_pubkey)


def encrypt(
    data: bytes, pubkey: datatypes.PublicKey, shared_mac_data: bytes = b""
) -> bytes:
    """Encrypt data with ECIES method to the given public key
    1) generate r = random value
    2) generate shared-secret = kdf( ecdhAgree(r, P) )
    3) generate R = rG [same op as generating a public key]
    4) 0x04 || R || AsymmetricEncrypt(shared-secret, plaintext) || tag
    """
    # 1) generate r = random value
    ephemeral = generate_privkey()

    # 2) generate shared-secret = kdf( ecdhAgree(r, P) )
    key_material = ecdh_agree(ephemeral, pubkey)
    key = kdf(key_material)
    key_enc, key_mac = key[: KEY_LEN // 2], key[KEY_LEN // 2 :]

    key_mac = sha256(key_mac).digest()
    # 3) generate R = rG [same op as generating a public key]
    ephem_pubkey = ephemeral.public_key

    # Encrypt
    algo = CIPHER(key_enc)
    iv = os.urandom(algo.block_size // 8)
    ctx = Cipher(algo, MODE(iv), default_backend()).encryptor()
    ciphertext = ctx.update(data) + ctx.finalize()

    # 4) 0x04 || R || AsymmetricEncrypt(shared-secret, plaintext) || tag
    msg = b"\x04" + ephem_pubkey.to_bytes() + iv + ciphertext

    # the MAC of a message (called the tag) as per SEC 1, 3.5.
    tag = hmac_sha256(key_mac, msg[1 + PUBKEY_LEN :] + shared_mac_data)
    return msg + tag


def decrypt(
    data: bytes, privkey: datatypes.PrivateKey, shared_mac_data: bytes = b""
) -> bytes:
    """Decrypt data with ECIES method using the given private key
    1) generate shared-secret = kdf( ecdhAgree(myPrivKey, msg[1:65]) )
    2) verify tag
    3) decrypt
    ecdhAgree(r, recipientPublic) == ecdhAgree(recipientPrivate, R)
    [where R = r*G, and recipientPublic = recipientPrivate*G]
    """
    if data[:1] != b"\x04":
        raise DecryptionError("wrong ecies header")

    #  1) generate shared-secret = kdf( ecdhAgree(myPrivKey, msg[1:65]) )
    shared = data[1 : 1 + PUBKEY_LEN]
    try:
        key_material = ecdh_agree(privkey, keys.PublicKey(shared))
    except _InvalidPublicKey as exc:
        raise DecryptionError(
            f"Failed to generate shared secret with pubkey {shared!r}: {exc}"
        ) from exc
    key = kdf(key_material)
    key_enc, key_mac = key[: KEY_LEN // 2], key[KEY_LEN // 2 :]
    key_mac = sha256(key_mac).digest()
    tag = data[-KEY_LEN:]

    # 2) Verify tag
    expected_tag = hmac_sha256(
        key_mac, data[1 + PUBKEY_LEN : -KEY_LEN] + shared_mac_data
    )
    if not bytes_eq(expected_tag, tag):
        raise DecryptionError("Failed to verify tag")

    # 3) Decrypt
    algo = CIPHER(key_enc)
    blocksize = algo.block_size // 8
    iv = data[1 + PUBKEY_LEN : 1 + PUBKEY_LEN + blocksize]
    ciphertext = data[1 + PUBKEY_LEN + blocksize : -KEY_LEN]
    ctx = Cipher(algo, MODE(iv), default_backend()).decryptor()
    return ctx.update(ciphertext) + ctx.finalize()


def kdf(key_material: bytes) -> bytes:
    """NIST SP 800-56a Concatenation Key Derivation Function (see section 5.8.1).
    Pretty much copied from geth's implementation:
    https://github.com/ethereum/go-ethereum/blob/673007d7aed1d2678ea3277eceb7b55dc29cf092/crypto/ecies/ecies.go#L167
    """
    key = b""
    hash_ = hashes.SHA256()
    # FIXME: Need to find out why mypy thinks SHA256 has no 'block_size' attribute
    hash_blocksize = hash_.block_size  # type: ignore
    reps = ((KEY_LEN + 7) * 8) / (hash_blocksize * 8)
    counter = 0
    while counter <= reps:
        counter += 1
        ctx = sha256()
        ctx.update(struct.pack(">I", counter))
        ctx.update(key_material)
        key += ctx.digest()
    return key[:KEY_LEN]


def hmac_sha256(key: bytes, msg: bytes) -> bytes:
    mac = hmac.HMAC(key, hashes.SHA256(), default_backend())
    mac.update(msg)
    return mac.finalize()
