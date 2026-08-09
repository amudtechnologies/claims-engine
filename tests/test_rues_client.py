import json

import httpx
import pytest

from claims_engine.rues_client import (
    build_detail_payload,
    build_payload,
    decrypt,
    encrypt,
    get_company_detail,
    search_by_nit,
)

# Captured live from the real RUES search form (see the phase-5 planning
# conversation) -- a real regression test for the CryptoJS-compatible
# decrypt, not a synthetic example.
REAL_CIPHERTEXT = (
    "U2FsdGVkX1/OuWVoeg1ZeW8hIrjVsjhQUcJFYV9otkK+/m1nuNunC4RBtALEjp49"
    "CuNkbKkmoOTmXmeyZgf6W0/y1jAyI+GG/KvxLJDDBci7LZ7Y7zRP8p0mJcwW18w/"
)

# Captured live from the real RUES "Ver Detalle" form for a search match's
# id_rm (Bavaria & Cia S.C.A) -- same provenance as REAL_CIPHERTEXT above.
REAL_DETAIL_CIPHERTEXT = "U2FsdGVkX186Pc8OfsBQ7JTibGWS7nwvlax5R0I97zkJkNk2CHcPDFwERxLwn0N2"


def test_decrypt_real_captured_ciphertext():
    plain = decrypt(REAL_CIPHERTEXT, "qwerty")
    assert json.loads(plain) == {
        "Razon": None,
        "Nit": 901484254,
        "Dpto": None,
        "Cod_Camara": None,
        "Matricula": None,
    }


def test_decrypt_real_captured_detail_ciphertext():
    plain = decrypt(REAL_DETAIL_CIPHERTEXT, "qwerty")
    assert json.loads(plain) == {"id": "40000019772"}


def test_encrypt_decrypt_round_trip():
    plaintext = '{"hello":"world"}'
    assert decrypt(encrypt(plaintext)) == plaintext


def test_encrypt_uses_a_random_salt_each_time():
    assert encrypt("same text") != encrypt("same text")


def test_build_payload():
    assert build_payload(900123456) == {
        "Razon": None,
        "Nit": 900123456,
        "Dpto": None,
        "Cod_Camara": None,
        "Matricula": None,
    }


def test_search_by_nit_sends_encrypted_payload_and_parses_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["user_agent"] = request.headers.get("user-agent")
        captured["origin"] = request.headers.get("origin")
        captured["referer"] = request.headers.get("referer")
        return httpx.Response(200, json={"registros": [], "cant_registros": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = search_by_nit(client, 900123456)

    assert result == {"registros": [], "cant_registros": 0}
    assert "dataBody" in captured["body"]
    decrypted = json.loads(decrypt(captured["body"]["dataBody"]))
    assert decrypted["Nit"] == 900123456
    assert "amud-technologies-claims-engine" in captured["user_agent"]
    assert captured["origin"] == "https://www.rues.org.co"
    assert captured["referer"] == "https://www.rues.org.co/"


def test_search_by_nit_retries_transient_status_then_succeeds():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"registros": [], "cant_registros": 0})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = search_by_nit(client, 900123456)

    assert calls["count"] == 2
    assert result == {"registros": [], "cant_registros": 0}


def test_search_by_nit_does_not_retry_a_real_client_error():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(400)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        search_by_nit(client, 900123456)

    assert calls["count"] == 1


def test_build_detail_payload():
    assert build_detail_payload("40000019772") == {"id": "40000019772"}


def test_get_company_detail_sends_encrypted_payload_and_parses_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"registros": {"razon_social": "BAVARIA & CIA S.C.A"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = get_company_detail(client, "40000019772")

    assert result == {"registros": {"razon_social": "BAVARIA & CIA S.C.A"}}
    assert captured["url"] == "https://elasticprd.rues.org.co/api/Expediente/DetalleRM"
    decrypted = json.loads(decrypt(captured["body"]["dataBody"]))
    assert decrypted == {"id": "40000019772"}


def test_get_company_detail_retries_transient_status_then_succeeds():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"registros": {}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = get_company_detail(client, "40000019772")

    assert calls["count"] == 2
    assert result == {"registros": {}}
