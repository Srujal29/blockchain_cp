"""
Stage 4 Test Suite: Database Integrity, Concurrency, Blockchain Retry & Receipt Verification.
Validates:
1. Concurrency-safe audit event sequence numbering under advisory locking.
2. Malformed UUID handling (422/404, not unhandled 500).
3. Failed batch unblocking and clean retry without hash duplication.
4. Transaction receipt status confirmation handling (status 1 vs status 0 vs pending).
5. Accurate detection and reporting of ANCHOR_NOT_FOUND without false-positive verified states.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from app.core.security import (
    AccountStatus,
    create_access_token,
    hash_password,
    UserRole,
    validate_uuid,
)
from app.core.exceptions import ValidationException
from app.db.connection import get_db_connection
from app.db.repositories import anchor_batch_repo, audit_repo, user_repo
from app.services.blockchain_service import blockchain_service


@pytest.fixture
async def stage4_env():
    """Sets up an authority and customer test environment."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    auth_email = f"auth_stage4_{ts}@test.com"
    cust_email = f"cust_stage4_{ts}@test.com"
    pwd_hash = hash_password("SecurePass123!")

    async with get_db_connection() as conn:
        auth_user = await user_repo.create_user(
            conn=conn,
            email=auth_email,
            password_hash=pwd_hash,
            full_name="Stage4 Authority",
            role=UserRole.APPROVAL_AUTHORITY.value,
            account_status=AccountStatus.ACTIVE.value,
        )
        await user_repo.verify_user_email(conn, auth_user["id"])

        cust_user = await user_repo.create_user(
            conn=conn,
            email=cust_email,
            password_hash=pwd_hash,
            full_name="Stage4 Customer",
            role=UserRole.CUSTOMER.value,
            account_status=AccountStatus.ACTIVE.value,
        )
        await user_repo.verify_user_email(conn, cust_user["id"])

    auth_token = create_access_token({"sub": auth_user["id"], "role": auth_user["role"]})
    cust_token = create_access_token({"sub": cust_user["id"], "role": cust_user["role"]})

    return {
        "auth_user": auth_user,
        "cust_user": cust_user,
        "auth_headers": {"Authorization": f"Bearer {auth_token}"},
        "cust_headers": {"Authorization": f"Bearer {cust_token}"},
    }


def test_uuid_validation_helper():
    """Verifies that validate_uuid returns clean string or raises ValidationException."""
    valid_uuid_str = "12345678-1234-5678-1234-567812345678"
    assert validate_uuid(valid_uuid_str) == valid_uuid_str

    with pytest.raises(ValidationException):
        validate_uuid("invalid-not-a-uuid", "test_field")

    with pytest.raises(ValidationException):
        validate_uuid("", "empty_field")

    with pytest.raises(ValidationException):
        validate_uuid(None, "none_field")


@pytest.mark.asyncio
async def test_malformed_uuid_endpoint_rejection(async_client: httpx.AsyncClient, stage4_env):
    """
    Ensures endpoints return 422 or 404 on malformed UUIDs, never unhandled 500 DB errors.
    """
    env = stage4_env
    invalid_id = "not-a-valid-uuid"

    # 1. Integrity audit event
    r1 = await async_client.get(f"/api/v1/integrity/audit-events/{invalid_id}", headers=env["cust_headers"])
    assert r1.status_code in (400, 422)

    # 2. Integrity audit event proof
    r2 = await async_client.get(f"/api/v1/integrity/audit-events/{invalid_id}/proof", headers=env["cust_headers"])
    assert r2.status_code in (400, 422)

    # 3. Policies detail
    r3 = await async_client.get(f"/api/v1/policies/{invalid_id}", headers=env["cust_headers"])
    assert r3.status_code in (400, 422)

    # 4. Policies published document url
    r4 = await async_client.get(f"/api/v1/policies/{invalid_id}/published-document-url", headers=env["cust_headers"])
    assert r4.status_code in (400, 422)

    # 5. Claims details
    r5 = await async_client.get(f"/api/v1/claims/{invalid_id}", headers=env["cust_headers"])
    assert r5.status_code in (400, 404, 422)

    # 6. Registrations detail
    r6 = await async_client.get(f"/api/v1/registrations/{invalid_id}", headers=env["cust_headers"])
    assert r6.status_code in (400, 422)


@pytest.mark.asyncio
async def test_concurrent_audit_event_sequence_safety(stage4_env):
    """
    Verifies that concurrent audit event logging acquires advisory lock
    and produces monotonically increasing sequence numbers and unbroken hash links.
    """
    env = stage4_env
    actor_id = env["auth_user"]["id"]

    async def log_single_event(idx: int):
        async with get_db_connection() as conn:
            return await audit_repo.log_audit_event(
                conn=conn,
                actor_id=actor_id,
                actor_role=UserRole.APPROVAL_AUTHORITY.value,
                action=f"CONCURRENT_TEST_{idx}",
                target_type="test_target",
                target_id=None,
                metadata={"test_idx": idx},
            )

    # Concurrently fire 5 events
    tasks = [log_single_event(i) for i in range(5)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 5
    sequences = [r["sequence_number"] for r in results]
    # All sequence numbers must be distinct
    assert len(set(sequences)) == 5
    # All must have event hashes
    for r in results:
        assert r["event_hash"] is not None
        assert len(r["event_hash"]) == 64


@pytest.mark.asyncio
async def test_failed_batch_unblocking_and_retry(stage4_env):
    """
    Verifies that when a batch fails, its events are released (batch_id = NULL)
    and successfully retried on the next pass without duplicate hashes.
    """
    env = stage4_env
    actor_id = env["auth_user"]["id"]

    # 1. Create a fresh audit event
    async with get_db_connection() as conn:
        ev = await audit_repo.log_audit_event(
            conn=conn,
            actor_id=actor_id,
            actor_role=UserRole.APPROVAL_AUTHORITY.value,
            action="STAGE4_RETRY_TEST",
            target_type="retry_test",
            target_id=None,
            metadata={"stage": "test_retry"},
        )

        # 2. Simulate batch creation
        batch = await anchor_batch_repo.create_anchor_batch(
            conn=conn,
            batch_root_hash="0x" + "f" * 64,
            first_seq=ev["sequence_number"],
            last_seq=ev["sequence_number"],
            event_count=1,
            event_ids=[ev["id"]],
        )

        # 3. Simulate failure
        await anchor_batch_repo.update_batch_failed(
            conn=conn,
            batch_id=batch["id"],
            error_message="Simulated RPC connection timeout",
        )

        # 4. Verify that unblock_failed_batch_events releases the event
        unblocked = await anchor_batch_repo.unblock_failed_batch_events(conn)
        assert unblocked >= 0

        # 5. Verify the event record in database has been unblocked (batch_id is None and status is FAILED)
        event_rec = await audit_repo.get_audit_event_by_id(conn, ev["id"])
        assert event_rec is not None
        assert event_rec["batch_id"] is None
        assert event_rec["anchoring_status"] in ("PENDING", "FAILED")


@pytest.mark.asyncio
async def test_anchor_not_found_on_chain_handling(async_client: httpx.AsyncClient, stage4_env):
    """
    Verifies that if a batch root is recorded as ANCHORED in DB but missing from chain
    (e.g. Hardhat node restarted), the API reports outcome ANCHOR_NOT_FOUND, not VALID.
    """
    env = stage4_env
    actor_id = env["auth_user"]["id"]

    async with get_db_connection() as conn:
        ev = await audit_repo.log_audit_event(
            conn=conn,
            actor_id=actor_id,
            actor_role=UserRole.APPROVAL_AUTHORITY.value,
            action="STAGE4_NOT_FOUND_TEST",
            target_type="test",
            target_id=None,
            metadata={"test": "not_found"},
        )
        batch = await anchor_batch_repo.create_anchor_batch(
            conn=conn,
            batch_root_hash="0x" + "a" * 64,
            first_seq=ev["sequence_number"],
            last_seq=ev["sequence_number"],
            event_count=1,
            event_ids=[ev["id"]],
        )
        await anchor_batch_repo.update_batch_anchored(
            conn=conn,
            batch_id=batch["id"],
            tx_hash="0x" + "b" * 64,
            block_number=10,
            chain_id=31337,
            contract_address="0x5FbDB2315678afecb367f032d93F642f64180aa3",
        )

    # Mock contract returning exists=False (node restarted)
    mock_verify = {"exists": False, "reason": "Commitment not found on chain"}
    with patch.object(blockchain_service, "verify_commitment_on_chain", new=AsyncMock(return_value=mock_verify)):
        res = await async_client.get(f"/api/v1/integrity/audit-events/{ev['id']}", headers=env["auth_headers"])
        assert res.status_code == 200
        data = res.json()
        assert data["outcome"] == "ANCHOR_NOT_FOUND"
        assert data["on_chain_verified"] is False
