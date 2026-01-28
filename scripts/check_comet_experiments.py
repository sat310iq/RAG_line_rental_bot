"""Script to check Comet ML experiments and provide URLs for OPIK UI access."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config

def main():
    config = load_config()
    
    workspace = config.comet_workspace or "sat310iq"
    project_name = config.comet_project_name
    
    # Comet ML normalizes project names to lowercase
    normalized_project = project_name.lower().replace("_", "-")
    
    print("=" * 80)
    print("Comet ML / OPIK Access Information")
    print("=" * 80)
    print()
    print(f"Workspace: {workspace}")
    print(f"Project Name (configured): {project_name}")
    print(f"Project Name (normalized by Comet ML): {normalized_project}")
    print()
    print("Direct URLs:")
    print(f"  Comet ML Project: https://www.comet.com/{workspace}/{normalized_project}")
    print(f"  OPIK Projects: https://www.comet.com/opik/{workspace}/projects")
    print()
    print("Note:")
    print("  - Comet ML normalizes project names (uppercase -> lowercase, _ -> -)")
    print("  - If OPIK UI shows 'RAG_POC' but Comet ML uses 'rag-poc',")
    print("    they are the same project but displayed differently")
    print("  - Check both project names in OPIK UI:")
    print("    1. Look for 'RAG_POC' project")
    print("    2. Look for 'rag-poc' project")
    print("  - Latest experiments are recorded in Comet ML and should sync to OPIK")
    print()

if __name__ == "__main__":
    main()
