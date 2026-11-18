"""
API endpoints for InsureChain VoiceGuard demonstration scenarios (Phase 6 Stage 3).
Allows listing, seeding, inspecting, and cleanly purging demonstration scenarios.
"""

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_active_user, require_active_authority
from app.db.connection import get_db_connection
from app.schemas.demo import (
    DemoCleanupRequest,
    DemoCleanupResult,
    DemoScenarioDefinition,
    DemoSeedResult,
    DemoTamperCheckResult,
)
from app.services.demo_scenario_service import demo_scenario_service

router = APIRouter(prefix="/demo", tags=["Demonstration Scenarios"])


@router.get(
    "/scenarios",
    response_model=List[DemoScenarioDefinition],
    summary="List all available demonstration scenarios",
)
async def list_scenarios() -> List[DemoScenarioDefinition]:
    """Returns the catalogue of all 15 pre-packaged demonstration scenarios."""
    return demo_scenario_service.get_all_scenarios()


@router.get(
    "/scenarios/{scenario_id}",
    response_model=DemoScenarioDefinition,
    summary="Get scenario details by ID",
)
async def get_scenario(scenario_id: str) -> DemoScenarioDefinition:
    """Returns metadata and expected evaluation for a single scenario."""
    scn = demo_scenario_service.get_scenario_definition(scenario_id)
    if not scn:
        from app.core.exceptions import NotFoundException
        raise NotFoundException(f"Scenario '{scenario_id}' not found.")
    return scn


@router.post(
    "/scenarios/{scenario_id}/seed",
    response_model=DemoSeedResult,
    status_code=status.HTTP_200_OK,
    summary="Seed single demonstration scenario idempotently",
)
async def seed_single_scenario(scenario_id: str) -> DemoSeedResult:
    """
    Seeds a specific scenario idempotently.
    If the scenario already exists, preserves existing records without duplication or wiping.
    """
    async with get_db_connection() as conn:
        return await demo_scenario_service.seed_scenario(conn, scenario_id)


@router.post(
    "/seed-all",
    response_model=List[DemoSeedResult],
    status_code=status.HTTP_200_OK,
    summary="Seed all 15 demonstration scenarios idempotently",
)
async def seed_all_scenarios() -> List[DemoSeedResult]:
    """
    Seeds all 15 scenarios in deterministic order.
    Preserves any scenarios that are already present.
    """
    async with get_db_connection() as conn:
        return await demo_scenario_service.seed_all_scenarios(conn)


@router.get(
    "/audit-tamper-check",
    response_model=DemoTamperCheckResult,
    summary="Execute Scenario 15 tamper-evident Merkle verification",
)
async def run_audit_tamper_check() -> DemoTamperCheckResult:
    """
    Verifies an in-memory synthetic Merkle tree fixture.
    Proves inclusion proof correctness and demonstrates tamper detection without modifying DB or blockchain.
    """
    return demo_scenario_service.verify_synthetic_merkle_fixture()


@router.post(
    "/cleanup",
    response_model=DemoCleanupResult,
    status_code=status.HTTP_200_OK,
    summary="Purge all demonstration data (Authority role required)",
)
async def cleanup_demo_data(
    payload: DemoCleanupRequest,
    current_user: Dict[str, Any] = Depends(require_active_authority),
) -> DemoCleanupResult:
    """
    Destructive operation requiring Authority credentials and explicit confirmation.
    Deletes all records matching demo tags in strict foreign-key safe cascade order.
    Leaves non-demo user and audit data untouched.
    """
    async with get_db_connection() as conn:
        return await demo_scenario_service.cleanup_demo_data(conn, confirm=payload.confirm)

