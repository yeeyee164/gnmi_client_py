# -*- encoding: utf-8 -*-
"""
schema_resolver.py

Recursive schema resolver navigating dependency graphs (imports, includes, submodules)
and loading complete module closures into isolated libyang contexts in deterministic order.
"""
from __future__ import annotations
import re
import logging
from pathlib import Path
from typing import Optional, List, Tuple, Set, Sequence, Callable, Dict, Union

from config.schema import SchemaProfile, ModuleRef
from core.schema_context import SchemaContext
from core.schema_db import SchemaDB
from core.schema_errors import SchemaNotFoundError, SchemaDependencyError

logger = logging.getLogger(__name__)

# Regular expressions for scanning dependencies in raw YANG source
_IMPORT_BLOCK_RE = re.compile(
    r'(?:^|\s)import\s+([a-zA-Z0-9_\-\.]+)\s*\{([^}]*)\}',
    re.MULTILINE | re.DOTALL,
)
_INCLUDE_BLOCK_RE = re.compile(
    r'(?:^|\s)include\s+([a-zA-Z0-9_\-\.]+)\s*(?:\{([^}]*)\}|;)',
    re.MULTILINE | re.DOTALL,
)
_REVISION_DATE_RE = re.compile(r'revision-date\s+["\']?([0-9]{4}-[0-9]{2}-[0-9]{2})["\']?\s*;')


class SchemaResolver:
    """
    Resolves and compiles module dependency closures into a target SchemaContext.
    """

    def __init__(self, schema_db: SchemaDB):
        self.schema_db = schema_db

    @staticmethod
    def extract_dependencies(yang_content: str) -> List[Tuple[str, Optional[str], str]]:
        """
        Parses YANG source text to extract imported and included dependencies.
        Returns list of (module_name, revision_or_none, kind: 'import'|'include').
        """
        deps: List[Tuple[str, Optional[str], str]] = []

        # Find imports
        for match in _IMPORT_BLOCK_RE.finditer(yang_content):
            mod_name = match.group(1).strip()
            block_body = match.group(2)
            rev_match = _REVISION_DATE_RE.search(block_body)
            rev = rev_match.group(1) if rev_match else None
            deps.append((mod_name, rev, "import"))

        # Find includes
        for match in _INCLUDE_BLOCK_RE.finditer(yang_content):
            sub_name = match.group(1).strip()
            block_body = match.group(2) or ""
            rev_match = _REVISION_DATE_RE.search(block_body)
            rev = rev_match.group(1) if rev_match else None
            deps.append((sub_name, rev, "include"))

        return deps

    def _find_module_file(
        self,
        name: str,
        revision: Optional[str],
        search_dirs: Sequence[Path],
    ) -> Optional[Path]:
        """
        Searches configured directories for a matching YANG file following standard naming.
        """
        for d in search_dirs:
            if not d.is_dir():
                continue
            # 1. Exact name@revision.yang
            if revision:
                exact_path = d / f"{name}@{revision}.yang"
                if exact_path.is_file():
                    return exact_path
            # 2. Base name.yang (only if revision is None or matches content)
            base_path = d / f"{name}.yang"
            if base_path.is_file():
                if revision is None:
                    return base_path
                # Check revision in file content
                try:
                    content = base_path.read_text(encoding="utf-8")
                    if f"revision {revision}" in content or f'revision "{revision}"' in content or f"revision '{revision}'" in content:
                        return base_path
                except OSError:
                    pass

            # 3. Any name@*.yang
            if revision is None:
                matches = list(d.glob(f"{name}@*.yang"))
                if matches:
                    return sorted(matches, reverse=True)[0]

        return None

    def ensure_module(
        self,
        context: SchemaContext,
        module_name: str,
        revision: Optional[str] = None,
        search_dirs: Sequence[Union[str, Path]] = (),
        fetch_callback: Optional[Callable[[str, Optional[str]], Optional[str]]] = None,
        visited: Optional[Set[Tuple[str, Optional[str]]]] = None,
    ) -> None:
        """
        Recursively resolves dependencies and loads a module into the SchemaContext.
        Order of lookup:
          1. Active libyang Context
          2. Configured search_dirs
          3. Local SQLite cache (SchemaDB)
          4. Protocol-specific fetch_callback (e.g. NETCONF <get-schema>)
          5. Raise SchemaNotFoundError / SchemaDependencyError
        """
        if visited is None:
            visited = set()

        key = (module_name, revision)
        if key in visited:
            return
        visited.add(key)

        norm_search_dirs = [Path(d).expanduser().resolve() for d in search_dirs]
        for d in context.search_dirs:
            if d not in norm_search_dirs:
                norm_search_dirs.append(d)

        # 1. Active Context Check
        if context.has_module(module_name, revision):
            # Also ensure file is present in search path if on disk
            existing_p = self._find_module_file(module_name, revision, norm_search_dirs)
            if existing_p is None:
                existing_p = self.schema_db.find_module(name=module_name, revision=revision)
            if existing_p is not None:
                context.add_search_dir(existing_p.parent)
                logger.debug(f"[Resolver] Module '{module_name}' ({revision}) already loaded in context.")
                return
            if fetch_callback is None:
                logger.debug(f"[Resolver] Module '{module_name}' ({revision}) already loaded in context.")
                return

        module_path: Optional[Path] = None

        # 2. Configured search_dirs
        module_path = self._find_module_file(module_name, revision, norm_search_dirs)

        # 3. Local Cache DB
        if module_path is None:
            module_path = self.schema_db.find_module(name=module_name, revision=revision)

        # 4. Protocol Fetch Callback
        if module_path is None and fetch_callback is not None:
            logger.info(f"[Resolver] Fetching missing module '{module_name}' ({revision}) via protocol...")
            fetched_content = fetch_callback(module_name, revision)
            if fetched_content:
                # Save to cache DB atomically (without strict libyang validation because dependencies not yet present)
                is_sub = bool(re.search(r'^\s*submodule\s+', fetched_content, re.MULTILINE))
                module_path = self.schema_db.store_module_content(
                    name=module_name,
                    content=fetched_content,
                    revision=revision,
                    kind="submodule" if is_sub else "module",
                    source="protocol_discovery",
                    verify_with_libyang=False,
                )

        if module_path is None or not module_path.is_file():
            raise SchemaNotFoundError(
                f"Cannot locate YANG module '{module_name}' (rev: {revision or 'any'}). "
                f"Searched dirs: {[str(d) for d in norm_search_dirs]}, Cache: {self.schema_db.models_dir}"
            )

        context.add_search_dir(module_path.parent)

        # Read content and inspect dependencies before parsing into context
        try:
            content = module_path.read_text(encoding="utf-8")
        except OSError as e:
            raise SchemaNotFoundError(f"Failed to read YANG file '{module_path}': {e}") from e

        is_submodule = bool(re.search(r'^\s*submodule\s+', content, re.MULTILINE))

        deps = self.extract_dependencies(content)
        for dep_name, dep_rev, dep_kind in deps:
            try:
                self.ensure_module(
                    context=context,
                    module_name=dep_name,
                    revision=dep_rev,
                    search_dirs=norm_search_dirs,
                    fetch_callback=fetch_callback,
                    visited=visited,
                )
            except SchemaNotFoundError as err:
                raise SchemaDependencyError(
                    f"Dependency resolution failed for '{module_name}' -> requires {dep_kind} "
                    f"'{dep_name}' ({dep_rev or 'any'}): {err}"
                ) from err

        # Load file into context (submodules are included via parent module search path)
        if not is_submodule:
            try:
                context.parse_module_file(module_path)
                logger.debug(f"[Resolver] Successfully parsed '{module_name}' into context.")
            except Exception as e:
                # If already loaded in context, ignore duplicate load
                if not context.has_module(module_name, revision):
                    raise SchemaDependencyError(f"libyang compilation failed for '{module_name}': {e}") from e
        else:
            logger.debug(f"[Resolver] Submodule '{module_name}' registered in search path for inclusion.")

    def ensure_profile(
        self,
        context: SchemaContext,
        profile: SchemaProfile,
        search_dirs: Sequence[Union[str, Path]] = (),
        fetch_callback: Optional[Callable[[str, Optional[str]], Optional[str]]] = None,
    ) -> None:
        """
        Loads all modules in a SchemaProfile into the SchemaContext.
        """
        for mod in profile.modules:
            self.ensure_module(
                context=context,
                module_name=mod.name,
                revision=mod.revision,
                search_dirs=search_dirs,
                fetch_callback=fetch_callback,
            )

