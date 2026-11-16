"""Locate root-level project assets in checkouts, frozen bundles and wheels."""
from pathlib import Path


def project_root():
    package = Path(__file__).resolve().parent
    checkout = package.parents[1]
    if (checkout / "agent_skills" / "index.json").is_file():
        return checkout
    return package / "_assets"


PROJECT = project_root()


def asset_files():
    for directory in ("agent_skills", "models", "library", "references"):
        for path in (PROJECT / directory).rglob("*"):
            if (path.is_file() and path.suffix in (".json", ".md", ".txt")
                    and not path.name.endswith(".local.json")):
                yield path
