"""
Explicit, optional, idempotent demo policy seeding script for InsureChain VoiceGuard.
Never executed automatically at application startup.

Usage (from backend/ directory):
    .venv\\Scripts\\python.exe -m scripts.seed_demo_policies
"""

import asyncio
from datetime import date, datetime, timezone
import hashlib
import json
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db.connection import close_db_pool, get_db_connection, init_db_pool


DEMO_POLICIES = [
    {
        "insurer_name": "Care Premier Health",
        "policy_name": "Care Premier Health Shield",
        "policy_code": "VG-HLT-01",
        "category": "HOSPITALIZATION",
        "description": (
            "Comprehensive family hospitalization cover including ICU care, "
            "day-care procedures, and pre/post-hospitalization expenses."
        ),
        "coverage_limit": "1500000.00",
        "waiting_period_days": 30,
        "claim_filing_window_days": 45,
        "document_storage_ref": "policies/care_premier_health_shield_v1.pdf",
        "terms_json": {
            "room_rent_cap": "Up to 1% of sum insured per day; ICU up to 2%",
            "waiting_period_general_days": 30,
            "waiting_period_pre_existing_months": 24,
            "co_payment_percentage": 10,
            "exclusions": ["Cosmetic surgery", "Self-inflicted injury", "Experimental treatments"],
        },
    },
    {
        "insurer_name": "DriveProtect General",
        "policy_name": "Comprehensive Auto DriveProtect",
        "policy_code": "VG-MOT-02",
        "category": "VEHICLE",
        "description": (
            "Zero-depreciation motor insurance with collision repair, theft protection, "
            "and third-party liability coverage."
        ),
        "coverage_limit": "850000.00",
        "waiting_period_days": 0,
        "claim_filing_window_days": 30,
        "document_storage_ref": "policies/auto_driveprotect_v1.pdf",
        "terms_json": {
            "zero_depreciation": True,
            "deductible_compulsory": 1000,
            "roadside_assistance": "24x7 within 100 km",
            "exclusions": ["Driving under influence", "Unlicensed driver", "Consequential engine damage"],
        },
    },
    {
        "insurer_name": "Life Horizon Assurance",
        "policy_name": "Life Horizon Secure Term",
        "policy_code": "VG-GEN-03",
        "category": "GENERIC",
        "description": (
            "Pure term life and critical illness protection with guaranteed lump-sum payout "
            "and accidental disability rider."
        ),
        "coverage_limit": "5000000.00",
        "waiting_period_days": 0,
        "claim_filing_window_days": 60,
        "document_storage_ref": "policies/life_horizon_secure_term_v1.pdf",
        "terms_json": {
            "term_years": 20,
            "accidental_death_rider": True,
            "suicide_exclusion_months": 12,
            "exclusions": ["Non-disclosure of material facts", "Active war participation"],
        },
    },
]


async def seed_demo_policies() -> None:
    await init_db_pool()
    inserted_policies = 0
    inserted_versions = 0

    try:
        async with get_db_connection() as conn:
            async with conn.cursor() as cur:
                for item in DEMO_POLICIES:
                    await cur.execute(
                        "SELECT id FROM policies WHERE policy_code = %s;",
                        (item["policy_code"],),
                    )
                    existing = await cur.fetchone()

                    if existing:
                        policy_id = existing[0]
                    else:
                        await cur.execute(
                            """
                            INSERT INTO policies (
                                insurer_name, policy_name, policy_code, category,
                                description, coverage_limit, waiting_period_days,
                                claim_filing_window_days, is_active
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                            RETURNING id;
                            """,
                            (
                                item["insurer_name"],
                                item["policy_name"],
                                item["policy_code"],
                                item["category"],
                                item["description"],
                                item["coverage_limit"],
                                item["waiting_period_days"],
                                item["claim_filing_window_days"],
                            ),
                        )
                        policy_id = (await cur.fetchone())[0]
                        inserted_policies += 1

                    await cur.execute(
                        """
                        SELECT id FROM policy_versions
                        WHERE policy_id = %s AND version_number = 1;
                        """,
                        (policy_id,),
                    )
                    version_row = await cur.fetchone()
                    if not version_row:
                        terms_str = json.dumps(item["terms_json"], sort_keys=True)
                        checksum = hashlib.sha256(terms_str.encode("utf-8")).hexdigest()
                        await cur.execute(
                            """
                            INSERT INTO policy_versions (
                                policy_id, version_number, document_storage_ref,
                                document_checksum, effective_date, terms_json,
                                is_published, published_at
                            )
                            VALUES (%s, 1, %s, %s, %s, %s::jsonb, TRUE, %s);
                            """,
                            (
                                policy_id,
                                item["document_storage_ref"],
                                checksum,
                                date.today(),
                                terms_str,
                                datetime.now(timezone.utc),
                            ),
                        )
                        inserted_versions += 1

        print(
            f"Demo policy seeding complete: {inserted_policies} policy(ies) inserted, "
            f"{inserted_versions} published version(s) inserted."
        )
    finally:
        await close_db_pool()


if __name__ == "__main__":
    asyncio.run(seed_demo_policies())
