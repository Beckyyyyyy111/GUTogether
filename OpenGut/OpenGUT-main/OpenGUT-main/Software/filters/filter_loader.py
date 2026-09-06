"""Utility for discovering and loading filter plugins."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
from typing import List


@dataclass
class LoadedFilter:
    module_name: str
    file_stem: str
    file_path: Path
    instance: object


def discover_filters(filters_dir: Path) -> List[LoadedFilter]:
    """Discover filter plugin modules in a directory."""
    results: List[LoadedFilter] = []

    if not filters_dir.exists():
        return results

    for path in sorted(filters_dir.glob("*.py")):
        if path.name in {"__init__.py", "template_filter.py", "filter_loader.py"}:
            continue

        module_name = f"filters.{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            continue

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        filter_cls = getattr(module, "FilterUnit", None)
        if filter_cls is None:
            continue

        instance = filter_cls()
        results.append(
            LoadedFilter(
                module_name=module_name,
                file_stem=path.stem,
                file_path=path,
                instance=instance,
            )
        )

    return results
