"""ID mapping utility for evaluation.

This module provides functions to map expected document IDs to actual document IDs
used in the RAG system. It handles different ID formats for FAQ and PDFs.

Strict vs canonical (normalized):
- **Strict** mapping: PDF filename remap + FAQ intent table only (no eval YAML aliases).
- **Canonical** mapping: applies `data/eval/expected_id_aliases.yaml` first, then the same rules.
"""

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional

from src.config import Config


def _load_eval_aliases_yaml(path: Path) -> Dict[str, str]:
    """Load `aliases:` block from a minimal YAML file (no PyYAML dependency)."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    m = re.search(r"aliases:\s*\n((?:[ \t]+[^\n]+\n?)+)", text)
    if not m:
        return {}
    out: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        val = rest.strip().strip('"').strip("'")
        if key and val:
            out[key] = val
    return out


class EvalIDMapper:
    """Maps expected document IDs to actual document IDs."""

    def __init__(self, config: Config):
        """Initialize ID mapper.

        Args:
            config: Application configuration
        """
        self.config = config
        self._faq_intents: Dict[str, str] = {}
        self._pdf_filename_mapping: Dict[str, str] = {}
        self._eval_aliases: Dict[str, str] = {}
        self._load_eval_aliases()
        self._load_faq_intents()
        self._load_pdf_filename_mapping()

    def _load_eval_aliases(self) -> None:
        path = self.config.get_expected_id_aliases_path()
        try:
            self._eval_aliases = _load_eval_aliases_yaml(path)
        except Exception as e:
            print(f"Warning: Failed to load eval ID aliases from {path}: {e}")

    def _load_faq_intents(self) -> None:
        """Load FAQ intent mappings from CSV."""
        csv_path = self.config.get_kb_csv_path()
        if not csv_path.exists():
            return

        try:
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    intent = row.get("intent", "").strip()
                    if intent:
                        self._faq_intents[intent] = intent
        except Exception as e:
            print(f"Warning: Failed to load FAQ intents: {e}")

    def _load_pdf_filename_mapping(self) -> None:
        """Load PDF filename mappings with priority-based matching.

        Priority 1: Property name + document type (most reliable)
        Priority 2: Document type only (fallback with warning)
        """
        pdf_dir = self.config.get_pdf_documents_dir()
        if not pdf_dir.exists():
            return

        pdf_files = list(pdf_dir.glob("*.pdf"))

        for pdf_file in pdf_files:
            filename = pdf_file.name
            if "グランマーレ" in filename and "契約書" in filename:
                self._pdf_filename_mapping["contract.pdf"] = filename
                break

        if "contract.pdf" not in self._pdf_filename_mapping:
            contract_files = [f for f in pdf_files if "契約書" in f.name]
            if len(contract_files) > 1:
                import warnings

                warnings.warn(
                    f"Multiple contract files found: {[f.name for f in contract_files]}. "
                    f"Using first: {contract_files[0].name}"
                )
            if contract_files:
                self._pdf_filename_mapping["contract.pdf"] = contract_files[0].name

        for pdf_file in pdf_files:
            filename = pdf_file.name
            if "重説" in filename:
                self._pdf_filename_mapping["prospectus.pdf"] = filename
                break

    def apply_eval_alias(self, expected_id: str) -> str:
        """Return canonical eval slug after YAML alias (identity if none)."""
        if not expected_id or not expected_id.strip():
            return ""
        s = expected_id.strip()
        return self._eval_aliases.get(s, s)

    def map_expected_id(self, expected_id: str, source_type: Optional[str] = None) -> List[str]:
        """Map expected ID to actual document ID(s) (canonical / normalized path).

        Applies eval YAML aliases, then PDF / FAQ rules.
        """
        if not expected_id or not expected_id.strip():
            return []
        canonical = self.apply_eval_alias(expected_id)
        return self._map_expected_id_without_alias(canonical, source_type)

    def map_expected_id_strict(self, expected_id: str, source_type: Optional[str] = None) -> List[str]:
        """Map expected ID without eval YAML aliases (strict scoring baseline)."""
        if not expected_id or not expected_id.strip():
            return []
        return self._map_expected_id_without_alias(expected_id.strip(), source_type)

    def _map_expected_id_without_alias(self, expected_id: str, source_type: Optional[str] = None) -> List[str]:
        """Core mapping: PDF `filename pN` remap, then FAQ intent table."""
        expected_id = expected_id.strip()

        if " p" in expected_id:
            parts = expected_id.rsplit(" p", 1)
            if len(parts) == 2:
                expected_filename = parts[0]
                page = parts[1]

                if expected_filename in self._pdf_filename_mapping:
                    actual_filename = self._pdf_filename_mapping[expected_filename]
                    return [f"{actual_filename} p{page}"]

                if expected_filename in self._pdf_filename_mapping.values():
                    return [expected_id]

            return [expected_id]

        if expected_id in self._faq_intents:
            return [self._faq_intents[expected_id]]

        if source_type == "faq":
            if expected_id in self._faq_intents:
                return [self._faq_intents[expected_id]]

        return [expected_id]

    def map_expected_ids(self, expected_ids: List[str], source_type: Optional[str] = None) -> List[str]:
        """Map multiple expected IDs to actual document IDs (canonical path)."""
        mapped_ids: List[str] = []
        for expected_id in expected_ids:
            mapped = self.map_expected_id(expected_id, source_type)
            mapped_ids.extend(mapped)
        return mapped_ids

    def map_expected_ids_strict(self, expected_ids: List[str], source_type: Optional[str] = None) -> List[str]:
        """Map multiple expected IDs without eval YAML aliases."""
        mapped_ids: List[str] = []
        for expected_id in expected_ids:
            mapped = self.map_expected_id_strict(expected_id, source_type)
            mapped_ids.extend(mapped)
        return mapped_ids


def create_id_mapper(config: Optional[Config] = None) -> EvalIDMapper:
    """Create an ID mapper instance.

    Args:
        config: Optional configuration (if None, loads from environment)

    Returns:
        EvalIDMapper instance
    """
    if config is None:
        from src.config import load_config

        config = load_config()
    return EvalIDMapper(config)
