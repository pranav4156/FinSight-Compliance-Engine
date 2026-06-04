import uuid

import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hashing():
    hashed = hash_password("mypassword")
    assert hashed != "mypassword"
    assert verify_password("mypassword", hashed)
    assert not verify_password("wrongpassword", hashed)


def test_token_create_and_decode():
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    token = create_access_token(user_id, "compliance_analyst", tenant_id)
    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["role"] == "compliance_analyst"
    assert payload["tenant_id"] == str(tenant_id)


def test_tampered_token_raises():
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    token = create_access_token(user_id, "admin", tenant_id)
    tampered = token[:-5] + "XXXXX"

    with pytest.raises(ValueError):
        decode_access_token(tampered)


def test_invalid_token_raises():
    with pytest.raises(ValueError):
        decode_access_token("not.a.real.token")
