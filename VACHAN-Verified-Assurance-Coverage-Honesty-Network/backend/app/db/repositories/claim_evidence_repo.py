"""
Claim evidence metadata repository using Psycopg 3 parameterized SQL.
Stores private storage identifiers, MIME types, cryptographic SHA-256 hashes,
and analysis states without public URLs.
"""

import json
from typing import Any, Dict, List, Optional
import psycopg

from app.core.exceptions import ConflictException, DatabaseException


def _row_to_evidence_dict(row: tuple) -> Dict[str, Any]:
    return {
        "id": str(row[0]),
        "claim_id": str(row[1]),
        "uploader_id": str(row[2]),
        "evidence_type": row[3],
        "original_filename": row[4],
        "document_storage_ref": row[5],
        "file_size_bytes": row[6],
        "mime_type": row[7],
        "document_checksum": row[8],
        "analysis_status": row[9],
        "resource_metadata": row[10] if isinstance(row[10], dict) else json.loads(row[10] or "{}"),
        "created_at": row[11].isoformat() if row[11] else None,
    }


EVIDENCE_FIELDS = """
    id, claim_id, uploader_id, evidence_type, original_filename,
    document_storage_ref, file_size_bytes, mime_type, document_checksum,
    analysis_status, resource_metadata, created_at
"""


async def create_evidence(
    conn: psycopg.AsyncConnection,
    claim_id: str,
    uploader_id: str,
    evidence_type: str,
    original_filename: str,
    document_storage_ref: str,
    file_size_bytes: int,
    mime_type: str,
    document_checksum: str,
    resource_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Records uploaded evidence metadata associated with a claim."""
    sql = f"""
    INSERT INTO claim_evidence (
        claim_id, uploader_id, evidence_type, original_filename,
        document_storage_ref, file_size_bytes, mime_type,
        document_checksum, resource_metadata
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING {EVIDENCE_FIELDS};
    """
    async with conn.cursor() as cur:
        try:
            await cur.execute(
                sql,
                (
                    claim_id,
                    uploader_id,
                    evidence_type,
                    original_filename,
                    document_storage_ref,
                    file_size_bytes,
                    mime_type,
                    document_checksum,
                    json.dumps(resource_metadata or {}),
                ),
            )
        except psycopg.errors.UniqueViolation as exc:
            raise ConflictException("This exact file has already been uploaded to this claim.") from exc
        row = await cur.fetchone()
        if not row:
            raise DatabaseException("Failed to insert claim evidence record.")
        return _row_to_evidence_dict(row)


async def lock_claim_for_evidence(
    conn: psycopg.AsyncConnection, claim_id: str
) -> None:
    """Acquires row-level FOR UPDATE lock on parent claim to serialize concurrent uploads."""
    async with conn.cursor() as cur:
        await cur.execute("SELECT id FROM claims WHERE id = %s FOR UPDATE;", (claim_id,))


async def count_evidence_by_claim(
    conn: psycopg.AsyncConnection, claim_id: str
) -> int:
    """Returns total number of evidence records currently attached to a claim."""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*) FROM claim_evidence WHERE claim_id = %s;",
            (claim_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def get_evidence_by_checksum(
    conn: psycopg.AsyncConnection, claim_id: str, document_checksum: str
) -> Optional[Dict[str, Any]]:
    """Checks whether an identical file checksum already exists for the claim."""
    sql = f"""
    SELECT {EVIDENCE_FIELDS}
    FROM claim_evidence
    WHERE claim_id = %s AND document_checksum = %s
    LIMIT 1;
    """
    async with conn.cursor() as cur:
        await cur.execute(sql, (claim_id, document_checksum))
        row = await cur.fetchone()
        return _row_to_evidence_dict(row) if row else None


async def get_evidence_by_id(
    conn: psycopg.AsyncConnection, evidence_id: str
) -> Optional[Dict[str, Any]]:
    """Retrieves an evidence item by UUID."""
    sql = f"SELECT {EVIDENCE_FIELDS} FROM claim_evidence WHERE id = %s;"
    async with conn.cursor() as cur:
        await cur.execute(sql, (evidence_id,))
        row = await cur.fetchone()
        return _row_to_evidence_dict(row) if row else None


async def list_evidence_by_claim(
    conn: psycopg.AsyncConnection, claim_id: str
) -> List[Dict[str, Any]]:
    """Lists all evidence files attached to a claim."""
    sql = f"""
    SELECT {EVIDENCE_FIELDS}
    FROM claim_evidence
    WHERE claim_id = %s
    ORDER BY created_at ASC;
    """
    async with conn.cursor() as cur:
        await cur.execute(sql, (claim_id,))
        rows = await cur.fetchall()
        return [_row_to_evidence_dict(r) for r in rows]


async def delete_evidence(
    conn: psycopg.AsyncConnection, evidence_id: str
) -> bool:
    """Deletes an evidence metadata record."""
    sql = "DELETE FROM claim_evidence WHERE id = %s RETURNING id;"
    async with conn.cursor() as cur:
        await cur.execute(sql, (evidence_id,))
        row = await cur.fetchone()
        return bool(row)
