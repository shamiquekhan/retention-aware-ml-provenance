"""Read-only provider adapters."""

from .github_actions import GitHubActionsClient, GitHubActionsCollection
from .ghcr import GHCRClient, GHCRCollection

__all__ = ["GHCRClient", "GHCRCollection", "GitHubActionsClient", "GitHubActionsCollection"]
