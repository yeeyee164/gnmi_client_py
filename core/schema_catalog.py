# -*- encoding: utf-8 -*-
"""
schema_catalog.py

Protocol-neutral catalog bridging model identities (e.g. gNMI ModelData,
NETCONF capability URIs) to concrete YANG ModuleRef collections.
Enforces that gNMI ModelData.version is not mistakenly equated with YANG revision.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Sequence, Union, Any

from config.schema import ModuleRef, SchemaProfile
from core.schema_errors import SchemaDiscoveryError


@dataclass(frozen=True)
class ModelCatalogEntry:
    """
    Catalog entry defining a model identity and its associated YANG module mappings.
    """
    name: str
    organization: Optional[str] = None
    version: Optional[str] = None
    modules: Tuple[ModuleRef, ...] = ()
    source_uri: Optional[str] = None
    source_type: Optional[str] = None

    def __post_init__(self):
        norm_mods = []
        for m in self.modules:
            if isinstance(m, ModuleRef):
                norm_mods.append(m)
            elif isinstance(m, dict):
                norm_mods.append(ModuleRef(**m))
            elif isinstance(m, (tuple, list)):
                norm_mods.append(ModuleRef(*m))
            else:
                norm_mods.append(ModuleRef(name=str(m)))
        object.__setattr__(self, "modules", tuple(norm_mods))


class ModelCatalog:
    """
    Thread-safe repository of known YANG models and vendor bundles.
    """

    def __init__(self):
        self._lock = threading.RLock()
        # Key: (name, organization or "", version or "")
        self._entries: Dict[Tuple[str, str, str], ModelCatalogEntry] = {}

    def register_entry(self, entry: ModelCatalogEntry) -> None:
        with self._lock:
            key = (
                entry.name,
                entry.organization or "",
                entry.version or "",
            )
            self._entries[key] = entry

    def register_model(
        self,
        name: str,
        organization: Optional[str] = None,
        version: Optional[str] = None,
        modules: Sequence[Union[ModuleRef, Tuple[str, Optional[str]], Dict[str, Any]]] = (),
        source_uri: Optional[str] = None,
        source_type: Optional[str] = None,
    ) -> ModelCatalogEntry:
        entry = ModelCatalogEntry(
            name=name,
            organization=organization,
            version=version,
            modules=tuple(
                m if isinstance(m, ModuleRef) else (
                    ModuleRef(**m) if isinstance(m, dict) else ModuleRef(*m)
                )
                for m in modules
            ),
            source_uri=source_uri,
            source_type=source_type,
        )
        self.register_entry(entry)
        return entry

    def resolve_model(
        self,
        name: str,
        organization: Optional[str] = None,
        version: Optional[str] = None,
    ) -> Optional[ModelCatalogEntry]:
        """
        Resolves a model by its catalog identifier.
        """
        with self._lock:
            # 1. Exact match
            key = (name, organization or "", version or "")
            if key in self._entries:
                return self._entries[key]

            # 2. Match with wildcard on organization or version
            candidates = [
                entry for (entry_name, entry_org, entry_ver), entry in self._entries.items()
                if entry_name == name
                and (organization is None or entry_org == organization or entry_org == "")
                and (version is None or entry_ver == version or entry_ver == "")
            ]
            if candidates:
                return candidates[0]

            return None

    def find_module(self, name: str, revision: Optional[str] = None) -> Optional[ModuleRef]:
        """
        Searches all registered catalog entries for a specific module name and revision.
        """
        with self._lock:
            for entry in self._entries.values():
                for m in entry.modules:
                    if m.name == name:
                        if revision is None or m.revision == revision:
                            return m
            return None

    def build_profile_from_gnmi_models(
        self,
        supported_models: Sequence[Any],
        strict: bool = True,
    ) -> SchemaProfile:
        """
        Translates a list of gNMI ModelData objects into an effective SchemaProfile.
        Does NOT equate ModelData.version to YANG revision unless resolved through catalog.
        """
        resolved_modules: List[ModuleRef] = []

        with self._lock:
            for model in supported_models:
                name = getattr(model, "name", str(model))
                org = getattr(model, "organization", None)
                ver = getattr(model, "version", None)

                entry = self.resolve_model(name=name, organization=org, version=ver)
                if entry and entry.modules:
                    resolved_modules.extend(entry.modules)
                else:
                    if strict:
                        raise SchemaDiscoveryError(
                            f"gNMI ModelData '{name}' (org: {org}, ver: {ver}) cannot be resolved to "
                            f"YANG module(s). Register an entry in ModelCatalog or configure offline yang_dirs."
                        )
                    # Non-strict fallback: register model by name without revision
                    resolved_modules.append(ModuleRef(name=name, revision=None))

        # Deduplicate modules by (name, revision)
        unique_modules: Dict[Tuple[str, Optional[str]], ModuleRef] = {}
        for m in resolved_modules:
            unique_modules[(m.name, m.revision)] = m

        return SchemaProfile(modules=tuple(unique_modules.values()))

