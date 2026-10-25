"""Retention-aware ML provenance research components."""

from .schema import EvidenceObject, EvidenceEdge, InventorySnapshot, ReleaseRequirement
from .planner import DecisionPlan, PlanAction, plan_retention
from .generator import generate_inventory, generate_inventories
from .providers.github_actions import GitHubActionsClient, GitHubActionsCollection
from .providers.ghcr import GHCRClient, GHCRCollection
from .archive import ArchiveVerification, verify_archive, verify_archive_content
from .merge import CrossServiceReference, JoinResult, attach_references, merge_snapshots

__all__ = [
    "DecisionPlan",
    "EvidenceEdge",
    "EvidenceObject",
    "InventorySnapshot",
    "PlanAction",
    "ReleaseRequirement",
    "generate_inventory",
    "generate_inventories",
    "GitHubActionsClient",
    "GitHubActionsCollection",
    "GHCRClient",
    "GHCRCollection",
    "ArchiveVerification",
    "CrossServiceReference",
    "JoinResult",
    "attach_references",
    "merge_snapshots",
    "verify_archive",
    "verify_archive_content",
    "plan_retention",
]
