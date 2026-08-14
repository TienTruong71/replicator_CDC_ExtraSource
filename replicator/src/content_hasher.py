"""
Content Hashing Algorithm for Multi-Source Insert-Only Sync

This module implements deterministic content hashing for record deduplication.
Uses SHA-256 for cryptographic strength and collision resistance, normalizes
record content for consistent hashing, and excludes metadata columns.

Requirements: 3.4, 3.5
"""

import hashlib
import json
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, Any, Optional, List, Union

try:
    from logger import Logger
except ImportError:
    from .logger import Logger


class ContentHasher:
    """
    Deterministic content hasher for database records.

    Provides SHA-256 based hashing that:
    - Excludes metadata columns (timestamps, source identifiers)
    - Normalizes string values for consistency
    - Handles different data types uniformly
    - Produces deterministic results regardless of input order
    """

    METADATA_COLUMNS = {
        'created_at', 'updated_at', 'source_id', 'sync_timestamp',
        'processed_at', 'last_modified', 'insert_time', 'update_time',
        'system_created', 'system_updated', 'audit_timestamp',
        'row_version', 'etag', 'modified_by', 'created_by'
    }

    def __init__(self):
        """Initialize the content hasher."""
        self.logger = Logger

    def compute_hash(self, record: Dict[str, Any], table_name: str) -> str:
        """
        Compute a deterministic SHA-256 hash for a database record.

        Args:
            record: Dictionary containing record data
            table_name: Name of the table (used for logging context)

        Returns:
            SHA-256 hex string representing the record content

        Raises:
            ValueError: If record is empty or invalid
            TypeError: If record contains unhashable types
        """
        if not record:
            raise ValueError("Record cannot be empty for hash computation")

        try:
            cleaned_record = self.exclude_metadata_columns(record)

            if not cleaned_record:
                self.logger.warn(f"All columns in {table_name} record are metadata - using table name for hash")
                cleaned_record = {'_table_name': table_name}

            normalized_record = self._normalize_record(cleaned_record)

            json_str = json.dumps(normalized_record, sort_keys=True, separators=(',', ':'))

            # Compute SHA-256 hash
            hash_obj = hashlib.sha256(json_str.encode('utf-8'))
            content_hash = hash_obj.hexdigest()

            # Log hash computation (only in verbose mode to avoid spam)
            return content_hash

        except Exception as e:
            self.logger.error(f"Failed to compute hash for {table_name} record", exc=e)
            raise

    def exclude_metadata_columns(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove metadata columns from record data.

        Args:
            record: Original record dictionary

        Returns:
            New dictionary with metadata columns removed
        """
        cleaned = {}
        excluded_count = 0

        for key, value in record.items():
            # Case-insensitive metadata column check
            if key.lower() in self.METADATA_COLUMNS:
                excluded_count += 1
                continue

            # Also exclude columns ending with common metadata suffixes
            key_lower = key.lower()
            if (key_lower.endswith('_at') or
                key_lower.endswith('_time') or
                key_lower.endswith('_timestamp') or
                key_lower.endswith('_id') and 'source' in key_lower):
                excluded_count += 1
                continue

            cleaned[key] = value

        # Log excluded columns only if significant number
        if excluded_count > 2:
            self.logger.info(f"Excluded {excluded_count} metadata columns from hash")

        return cleaned

    def normalize_value(self, value: Any) -> Union[str, int, float, bool, None]:
        """
        Normalize a single value for consistent hashing.

        Args:
            value: Value to normalize

        Returns:
            Normalized value suitable for JSON serialization
        """
        if value is None:
            return None

        # Handle string values
        if isinstance(value, str):
            # Strip whitespace and convert to lowercase for consistency
            normalized = value.strip().lower()
            return normalized if normalized else None

        # Handle numeric types
        if isinstance(value, (int, bool)):
            return value

        if isinstance(value, float):
            # Handle special float values
            if str(value).lower() in ('nan', 'inf', '-inf'):
                return str(value).lower()
            return value

        if isinstance(value, Decimal):
            return float(value)

        # Handle date/datetime objects
        if isinstance(value, (datetime, date)):
            # Convert to ISO format string for consistency
            return value.isoformat()

        # Handle bytes
        if isinstance(value, bytes):
            try:
                return value.decode('utf-8').strip().lower()
            except UnicodeDecodeError:
                # For binary data, use hex representation
                return value.hex().lower()

        # Handle lists and tuples
        if isinstance(value, (list, tuple)):
            return [self.normalize_value(item) for item in value]

        # Handle dictionaries (nested records)
        if isinstance(value, dict):
            return {k: self.normalize_value(v) for k, v in value.items()}

        # For any other type, convert to string and normalize
        return str(value).strip().lower()

    def _normalize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize all values in a record for consistent hashing.

        Args:
            record: Record to normalize

        Returns:
            Record with all values normalized
        """
        normalized = {}

        for key, value in record.items():
            # Normalize the key as well (case-insensitive, stripped)
            normalized_key = key.strip().lower()
            normalized_value = self.normalize_value(value)

            # Only include non-None values to reduce hash variation
            if normalized_value is not None:
                normalized[normalized_key] = normalized_value

        return normalized

    def validate_hash_determinism(self, record: Dict[str, Any], table_name: str, iterations: int = 5) -> bool:
        """
        Validate that hash computation is deterministic by computing multiple times.

        Args:
            record: Record to test
            table_name: Table name for context
            iterations: Number of iterations to test

        Returns:
            True if all iterations produce the same hash, False otherwise
        """
        if iterations < 2:
            return True

        try:
            first_hash = self.compute_hash(record, table_name)

            for i in range(1, iterations):
                current_hash = self.compute_hash(record, table_name)
                if current_hash != first_hash:
                    self.logger.error(f"Hash determinism failure on iteration {i}: {first_hash} != {current_hash}")
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Hash determinism validation failed for {table_name}", exc=e)
            return False

    def get_hash_info(self, record: Dict[str, Any], table_name: str) -> Dict[str, Any]:
        """
        Get detailed information about hash computation for debugging.

        Args:
            record: Record to analyze
            table_name: Table name for context

        Returns:
            Dictionary with hash computation details
        """
        try:
            original_columns = len(record)
            cleaned_record = self.exclude_metadata_columns(record)
            cleaned_columns = len(cleaned_record)
            excluded_columns = original_columns - cleaned_columns

            normalized_record = self._normalize_record(cleaned_record)
            content_hash = self.compute_hash(record, table_name)

            return {
                'table_name': table_name,
                'content_hash': content_hash,
                'original_columns': original_columns,
                'cleaned_columns': cleaned_columns,
                'excluded_columns': excluded_columns,
                'excluded_column_names': [k for k in record.keys()
                                        if k not in cleaned_record],
                'normalized_record': normalized_record,
                'hash_input_size': len(json.dumps(normalized_record, sort_keys=True))
            }

        except Exception as e:
            self.logger.error(f"Failed to get hash info for {table_name}", exc=e)
            return {
                'table_name': table_name,
                'error': str(e),
                'content_hash': None
            }