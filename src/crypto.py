"""Encrypt private roster-derived dashboard report before publishing to GitHub Pages."""
import base64
import json
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITERATIONS = 310_000


def b64(data):
    return base64.b64encode(data).decode("ascii")


def unb64(data):
    return base64.b64decode(data, validate=True)


def key_from_password(password, salt, iterations=ITERATIONS):
    if not password or len(password) < 16:
        raise ValueError("REPORT_PASSPHRASE must be 16+ characters")
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations).derive(password.encode("utf-8"))


def encrypt(document, password):
    salt, nonce = os.urandom(16), os.urandom(12)
    key = key_from_password(password, salt)
    plain = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    cipher = AESGCM(key).encrypt(nonce, plain, b"FantasyInjuryWatch:v1")
    return {"version": 1, "iterations": ITERATIONS, "salt": b64(salt), "nonce": b64(nonce), "ciphertext": b64(cipher)}


def decrypt(document, password):
    if document.get("version") != 1:
        raise ValueError("Unknown encrypted report version")
    key = key_from_password(password, unb64(document["salt"]), int(document["iterations"]))
    plaintext = AESGCM(key).decrypt(unb64(document["nonce"]), unb64(document["ciphertext"]), b"FantasyInjuryWatch:v1")
    return json.loads(plaintext)
