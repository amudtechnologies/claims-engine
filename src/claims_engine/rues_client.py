"""Phase 5: client for RUES's (Registro Único Empresarial y Social) NIT
lookup — Colombia's public business registry.

RUES has no documented API. Reverse-engineered from the public search form
at rues.org.co: the request body is client-side "encrypted" (CryptoJS
AES.encrypt with a passphrase — OpenSSL-compatible `Salted__` format), but
this is obfuscation of a public-data lookup form, not real access control —
the passphrase has to ship to every browser, and was found as a plain string
literal in the site's JS (`"qwerty"`). The response itself is plain JSON,
not encrypted.

This client is deliberately conservative, not stealthy: a real, identifying
User-Agent (so RUES's operators can reach out if this traffic is a problem,
rather than us hiding it from them), and no attempt to mimic browser
fingerprints or randomize timing to look human. Request pacing lives in
`enrichment.py`, which calls this one NIT at a time.
"""

from __future__ import annotations

import hashlib
import json
import os
from base64 import b64decode, b64encode

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

BASE_URL = "https://elasticprd.rues.org.co/api/ConsultasRUES/BusquedaAvanzadaRM"
DETAIL_URL = "https://elasticprd.rues.org.co/api/Expediente/DetalleRM"
PASSPHRASE = "qwerty"
USER_AGENT = "amud-technologies-claims-engine/0.1 (RUES enrichment; contact: joamud@gmail.com)"
# The API rejects requests with `{"message":"Origen no permitido"}` (HTTP 403)
# unless Origin/Referer match the public search form at rues.org.co. This is
# an allowlist check, not fingerprinting -- User-Agent stays real and
# identifying, nothing else about the request is disguised.
ORIGIN = "https://www.rues.org.co"
REFERER = "https://www.rues.org.co/"

_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class RuesTransientError(Exception):
    """A retryable failure (rate limited or RUES's server having trouble) —
    distinct from a real client error, which should not be retried."""


def _evp_bytes_to_key(
    password: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16
) -> tuple[bytes, bytes]:
    """OpenSSL's (and CryptoJS's default) passphrase-based KDF: repeated MD5
    over (previous digest + password + salt) until there's enough output."""
    derived = block = b""
    while len(derived) < key_len + iv_len:
        block = hashlib.md5(block + password + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len : key_len + iv_len]


def encrypt(plaintext: str, passphrase: str = PASSPHRASE) -> str:
    """CryptoJS-compatible AES-CBC encrypt: random salt, `Salted__` +
    salt + ciphertext, base64 — the format `AES.encrypt(text, passphrase)`
    produces in the browser."""
    salt = os.urandom(8)
    key, iv = _evp_bytes_to_key(passphrase.encode(), salt)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return b64encode(b"Salted__" + salt + ciphertext).decode()


def decrypt(ciphertext_b64: str, passphrase: str = PASSPHRASE) -> str:
    raw = b64decode(ciphertext_b64)
    if raw[:8] != b"Salted__":
        raise ValueError("not a CryptoJS Salted__ blob")
    salt, ciphertext = raw[8:16], raw[16:]
    key, iv = _evp_bytes_to_key(passphrase.encode(), salt)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    return plain.decode("utf-8")


def build_payload(nit: int) -> dict:
    """The decrypted request shape found by capturing a real search: an
    advanced-search form with five optional fields. Only Nit is ever set for
    this radar's enrichment — everything else stays null."""
    return {"Razon": None, "Nit": nit, "Dpto": None, "Cod_Camara": None, "Matricula": None}


@retry(
    retry=retry_if_exception_type((httpx.TransportError, RuesTransientError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)
def search_by_nit(client: httpx.Client, nit: int) -> dict:
    """One NIT lookup. Raises RuesTransientError (retried) on a rate-limit
    or server-error status, and lets a real client error (4xx other than
    429) surface immediately rather than retrying something that will never
    succeed."""
    body = json.dumps(build_payload(nit))
    response = client.post(
        BASE_URL,
        json={"dataBody": encrypt(body)},
        headers={"User-Agent": USER_AGENT, "Origin": ORIGIN, "Referer": REFERER},
    )
    if response.status_code in _TRANSIENT_STATUS_CODES:
        raise RuesTransientError(f"transient status {response.status_code} for NIT {nit}")
    response.raise_for_status()
    return response.json()


def build_detail_payload(id_rm: str) -> dict:
    """The decrypted request shape for the company-detail lookup: just the
    `id_rm` a search match already carries (e.g. `registros[0]["id_rm"]`) --
    there is no separate lookup key, the detail call is keyed off the same
    identifier the search response hands back."""
    return {"id": id_rm}


@retry(
    retry=retry_if_exception_type((httpx.TransportError, RuesTransientError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)
def get_company_detail(client: httpx.Client, id_rm: str) -> dict:
    """Full registration detail for one company (address, contact info,
    economic activity, registration/renewal/cancellation dates, legal
    organization type) -- richer than the search match, and not specific to
    judicial deposits: this is core entity data any future radar over legal
    entities would also want, so it's fetched whenever a search finds a
    match, not gated behind this source."""
    body = json.dumps(build_detail_payload(id_rm))
    response = client.post(
        DETAIL_URL,
        json={"dataBody": encrypt(body)},
        headers={"User-Agent": USER_AGENT, "Origin": ORIGIN, "Referer": REFERER},
    )
    if response.status_code in _TRANSIENT_STATUS_CODES:
        raise RuesTransientError(f"transient status {response.status_code} for id_rm {id_rm}")
    response.raise_for_status()
    return response.json()
