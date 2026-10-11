# -*- encoding: utf-8 -*-
"""
schema.py

Defines first-class immutable configuration and identity structures
for YANG data modeling and schema management.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence, Union, Tuple, Dict, Any
import hashlib
import json


@dataclass(frozen=True)
class SchemaConfig:
    """
    First-class schema configuration options for a session.
    Decoupled from protocol-specific options.
    """
    yang_dirs: Tuple[Path, ...] = ()
    cache_dir: Optional[Path] = None
    profile: Optional[str] = None
    validate: bool = False
    auto_discovery: bool = True
    auto_fetch: bool = True

    def __post_init__(self):
        # Normalize yang_dirs to tuple of resolved Path objects
        if self.yang_dirs:
            norm_dirs = tuple(
                p if isinstance(p, Path) else Path(p).expanduser().resolve()
                for p in self.yang_dirs
            )
            object.__setattr__(self, 'yang_dirs', norm_dirs)
        else:
            object.__setattr__(self, 'yang_dirs', ())

        # Normalize cache_dir to Path or None
        if self.cache_dir is not None and not isinstance(self.cache_dir, Path):
            object.__setattr__(self, 'cache_dir', Path(self.cache_dir).expanduser().resolve())


@dataclass(frozen=True)
class ModuleRef:
    """Reference to a YANG module with optional revision and namespace."""
    name: str
    revision: Optional[str] = None
    namespace: Optional[str] = None


@dataclass(frozen=True)
class SubmoduleRef:
    """Reference to a YANG submodule with optional revision."""
    name: str
    revision: Optional[str] = None


@dataclass(frozen=True)
class FeatureRef:
    """Reference to a feature defined within a module."""
    module: str
    name: str


@dataclass(frozen=True)
class DeviationRef:
    """Reference to a deviation module with optional revision."""
    name: str
    revision: Optional[str] = None


@dataclass(frozen=True)
class SchemaProfile:
    """
    Canonical schema profile describing the effective schema composition of a target.
    Decoupled from connection details (host/port) to allow schema caching and reuse.
    """
    modules: Tuple[ModuleRef, ...] = ()
    submodules: Tuple[SubmoduleRef, ...] = ()
    features: Tuple[FeatureRef, ...] = ()
    deviations: Tuple[DeviationRef, ...] = ()
    datastore_schemas: Tuple[str, ...] = ()
    content_id: Optional[str] = None

    def __post_init__(self):
        # Normalize modules to tuple[ModuleRef, ...]
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
        object.__setattr__(self, 'modules', tuple(norm_mods))

        # Normalize submodules to tuple[SubmoduleRef, ...]
        norm_subs = []
        for s in self.submodules:
            if isinstance(s, SubmoduleRef):
                norm_subs.append(s)
            elif isinstance(s, dict):
                norm_subs.append(SubmoduleRef(**s))
            elif isinstance(s, (tuple, list)):
                norm_subs.append(SubmoduleRef(*s))
            else:
                norm_subs.append(SubmoduleRef(name=str(s)))
        object.__setattr__(self, 'submodules', tuple(norm_subs))

        # Normalize features to tuple[FeatureRef, ...]
        norm_feats = []
        for f in self.features:
            if isinstance(f, FeatureRef):
                norm_feats.append(f)
            elif isinstance(f, dict):
                norm_feats.append(FeatureRef(**f))
            elif isinstance(f, (tuple, list)):
                norm_feats.append(FeatureRef(*f))
            else:
                raise ValueError(f"Invalid feature reference: {f}")
        object.__setattr__(self, 'features', tuple(norm_feats))

        # Normalize deviations to tuple[DeviationRef, ...]
        norm_devs = []
        for d in self.deviations:
            if isinstance(d, DeviationRef):
                norm_devs.append(d)
            elif isinstance(d, dict):
                norm_devs.append(DeviationRef(**d))
            elif isinstance(d, (tuple, list)):
                norm_devs.append(DeviationRef(*d))
            else:
                norm_devs.append(DeviationRef(name=str(d)))
        object.__setattr__(self, 'deviations', tuple(norm_devs))

        # Normalize datastore_schemas to tuple[str, ...]
        object.__setattr__(self, 'datastore_schemas', tuple(str(ds) for ds in self.datastore_schemas))

    def to_canonical_dict(self) -> Dict[str, Any]:
        """
        Serializes the profile into a normalized, deterministically sorted dictionary.
        """
        sorted_modules = sorted(
            [
                {
                    "name": m.name,
                    "revision": m.revision if m.revision else None,
                    "namespace": m.namespace if m.namespace else None,
                }
                for m in self.modules
            ],
            key=lambda item: (item["name"], item["revision"] or "", item["namespace"] or "")
        )

        sorted_submodules = sorted(
            [
                {
                    "name": s.name,
                    "revision": s.revision if s.revision else None,
                }
                for s in self.submodules
            ],
            key=lambda item: (item["name"], item["revision"] or "")
        )

        sorted_features = sorted(
            [
                {
                    "module": f.module,
                    "name": f.name,
                }
                for f in self.features
            ],
            key=lambda item: (item["module"], item["name"])
        )

        sorted_deviations = sorted(
            [
                {
                    "name": d.name,
                    "revision": d.revision if d.revision else None,
                }
                for d in self.deviations
            ],
            key=lambda item: (item["name"], item["revision"] or "")
        )

        sorted_datastores = sorted(list(self.datastore_schemas))

        return {
            "modules": sorted_modules,
            "submodules": sorted_submodules,
            "features": sorted_features,
            "deviations": sorted_deviations,
            "datastore_schemas": sorted_datastores,
            "content_id": self.content_id if self.content_id else None,
        }

    def to_canonical_json(self) -> str:
        """Serializes the profile into deterministic canonical JSON."""
        return json.dumps(self.to_canonical_dict(), sort_keys=True, separators=(',', ':'))

    @property
    def profile_id(self) -> str:
        """
        Deterministic SHA-256 hash identifying this schema profile.
        Independent of device host/port or collection insertion order.
        """
        canonical_bytes = self.to_canonical_json().encode('utf-8')
        return hashlib.sha256(canonical_bytes).hexdigest()

