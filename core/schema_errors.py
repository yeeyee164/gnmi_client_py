# -*- encoding: utf-8 -*-
"""
schema_errors.py

Typed exception hierarchy for the YANG schema management and validation subsystem.
"""


class SchemaError(Exception):
    """Base exception for all schema-related errors."""
    pass


class SchemaNotFoundError(SchemaError):
    """Raised when a requested YANG module, submodule, or schema file cannot be located."""
    pass


class SchemaDependencyError(SchemaError):
    """Raised when a schema dependency (import, include, deviation) fails to resolve."""
    pass


class SchemaProfileConflictError(SchemaError):
    """Raised when conflicting revisions or incompatible module sets collide within a profile."""
    pass


class SchemaValidationError(SchemaError):
    """Raised when a path or payload violates compiled YANG schema constraints."""
    pass


class InvalidSchemaPathError(SchemaValidationError):
    """Raised when an XPath or path selector does not resolve to a valid schema node."""
    pass


class SchemaSerializationError(SchemaError):
    """Raised when a libyang data tree cannot be serialized to the requested protocol format."""
    pass


class SchemaCacheError(SchemaError):
    """Raised when database operations, atomic caching, or checksum validations fail."""
    pass


class SchemaDiscoveryError(SchemaError):
    """Raised when protocol capabilities or model catalog entries cannot map to schema sources."""
    pass

