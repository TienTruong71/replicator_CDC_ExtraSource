"""
Deduplication Engine for Multi-Source Insert-Only Sync

This module implements hash-based duplicate detection logic with memory cache
and persistent storage integration. It tracks processed records to prevent
duplicate insertions across multiple sources.

Requirements: 3.1, 3.2, 3.3
"""

import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, NamedTuple
from collections import OrderedDict
from threading import RLock
import pyodbc

try:
    from logger import Logger
    from content_hasher import ContentHasher
    from db_utils import connect_db
except ImportError:
    from .logger import Logger
    from .content_hasher import ContentHasher
    from .db_utils import connect_db


class CleanupStats(NamedTuple):
    """Statistics from cleanup operations."""
    dedup_records_removed: int
    audit_records_removed: int
    execution_time_seconds: float
    errors_count: int


class DeduplicationEngine:
    """
    Hash-based duplicate detection engine with memory cache and persistent storage.

    This class provides efficient duplicate detection by:
    - Computing content hashes using ContentHasher
    - Checking memory cache first for recently processed records
    - Falling back to database deduplication tracker for older records
    - Logging duplicate events with detailed information
    - Supporting cleanup of old tracking data
    """

    def __init__(self, cache_size_limit: int = 1000000, cache_ttl_seconds: int = 3600):
        """
        Initialize the deduplication engine.

        Args:
            cache_size_limit: Maximum number of entries in memory cache (default: 1M)
            cache_ttl_seconds: Time-to-live for cache entries in seconds (default: 1 hour)
        """
        self.hasher = ContentHasher()
        self.logger = Logger
        self._cache_lock = RLock()

        # Memory cache configuration
        self.cache_size_limit = cache_size_limit
        self.cache_ttl_seconds = cache_ttl_seconds

        # LRU cache implementation using OrderedDict
        # Format: hash_key -> (timestamp, source_id, table_name)
        self._cache: OrderedDict[str, tuple[float, str, str]] = OrderedDict()

        # Statistics
        self._cache_hits = 0
        self._cache_misses = 0
        self._database_hits = 0
        self._total_checks = 0
        self._duplicates_found = 0

        self.logger.info("DeduplicationEngine initialized with cache limit: {}, TTL: {}s".format(
            cache_size_limit, cache_ttl_seconds))

    def is_duplicate(self, table: str, record: Dict[str, Any], source_id: str) -> bool:
        """
        Check if a record is a duplicate based on content hash.

        This method:
        1. Computes content hash for the record
        2. Checks memory cache first for performance
        3. Falls back to database lookup if not in cache
        4. Updates cache with new findings
        5. Logs duplicate detection events

        Args:
            table: Name of the table the record belongs to
            record: Dictionary containing the record data
            source_id: Identifier of the source database

        Returns:
            bool: True if the record is a duplicate, False otherwise
        """
        if not record:
            self.logger.warn(f"Empty record provided for duplicate check in {table}")
            return False

        try:
            # Compute content hash
            record_hash = self.hasher.compute_hash(record, table)

            with self._cache_lock:
                self._total_checks += 1

                # Check memory cache first
                cache_key = f"{table}:{record_hash}"

                if self._check_memory_cache(cache_key):
                    self._cache_hits += 1
                    self._duplicates_found += 1

                    # Move to end for LRU behavior
                    cached_data = self._cache.pop(cache_key)
                    self._cache[cache_key] = cached_data

                    original_source = cached_data[1]
                    self.logger.info(f"Duplicate detected in cache: {table} (hash: {record_hash[:12]}...) "
                                   f"from {source_id}, originally from {original_source}")
                    return True

                self._cache_misses += 1

            # Check persistent storage
            if self._check_database_storage(table, record_hash, source_id):
                self._database_hits += 1
                self._duplicates_found += 1

                # Add to cache for future lookups
                self._add_to_cache(cache_key, source_id, table)

                self.logger.info(f"Duplicate detected in database: {table} (hash: {record_hash[:12]}...) "
                               f"from {source_id}")
                return True

            # Not a duplicate - record this hash for future checks
            self.mark_processed(table, record_hash, source_id)

            return False

        except Exception as e:
            self.logger.error(f"Error checking duplicate for {table} from {source_id}", exc=e)
            # On error, allow the record through to avoid blocking valid data
            return False

    def mark_processed(self, table: str, record_hash: str, source_id: str) -> None:
        """
        Mark a record as processed by storing its hash in both cache and database.

        Args:
            table: Name of the table
            record_hash: Content hash of the record
            source_id: Identifier of the source database
        """
        try:
            # Add to memory cache
            cache_key = f"{table}:{record_hash}"
            self._add_to_cache(cache_key, source_id, table)

            # Store in persistent database
            self._store_in_database(table, record_hash, source_id)

            # self.logger.debug(f"Marked as processed: {table} (hash: {record_hash[:12]}...) from {source_id}")

        except Exception as e:
            self.logger.error(f"Failed to mark record as processed: {table} from {source_id}", exc=e)

    def cleanup_old_entries(self, retention_days: int) -> CleanupStats:
        """
        Clean up old deduplication tracking entries from database and expired cache entries.

        Args:
            retention_days: Number of days to retain tracking data

        Returns:
            CleanupStats: Statistics about the cleanup operation
        """
        start_time = time.time()
        dedup_removed = 0
        audit_removed = 0
        errors = 0

        try:
            self.logger.info(f"Starting cleanup: removing entries older than {retention_days} days")

            # Calculate cutoff date
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            cutoff_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S')

            # First, ensure the deduplication tracker table exists
            self._ensure_dedup_tracker_table()

            # Try to get a database connection (we'll use KINGDOM prefix as fallback)
            # In a real deployment, this should use the target database connection
            conn = None
            try:
                conn = connect_db("KINGDOM", target=True)
                cursor = conn.cursor()

                # Clean up old deduplication tracker entries
                try:
                    cursor.execute("""
                        DELETE FROM dbo.sync_dedup_tracker
                        WHERE created_at < ?
                    """, (cutoff_str,))
                    dedup_removed = cursor.rowcount
                    self.logger.info(f"Removed {dedup_removed} old deduplication tracking entries")
                except Exception as e:
                    errors += 1
                    self.logger.error("Failed to cleanup deduplication tracker entries", exc=e)

                # Clean up old processed audit log entries (optional, based on requirements)
                try:
                    cursor.execute("""
                        DELETE FROM dbo.sync_audit_log
                        WHERE status = 'processed' AND processed_at < ?
                    """, (cutoff_str,))
                    audit_removed = cursor.rowcount
                    self.logger.info(f"Removed {audit_removed} old processed audit log entries")
                except Exception as e:
                    errors += 1
                    self.logger.error("Failed to cleanup processed audit log entries", exc=e)

                conn.commit()

            except Exception as e:
                errors += 1
                self.logger.error("Failed to connect to database for cleanup", exc=e)
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
            finally:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass

            self._cleanup_expired_cache()

            execution_time = time.time() - start_time

            stats = CleanupStats(
                dedup_records_removed=dedup_removed,
                audit_records_removed=audit_removed,
                execution_time_seconds=execution_time,
                errors_count=errors
            )

            self.logger.success(f"Cleanup completed in {execution_time:.2f}s: "
                              f"dedup={dedup_removed}, audit={audit_removed}, errors={errors}")

            return stats

        except Exception as e:
            errors += 1
            execution_time = time.time() - start_time
            self.logger.error("Cleanup operation failed", exc=e)

            return CleanupStats(
                dedup_records_removed=dedup_removed,
                audit_records_removed=audit_removed,
                execution_time_seconds=execution_time,
                errors_count=errors
            )

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get memory cache and deduplication statistics.

        Returns:
            Dict containing cache performance metrics
        """
        with self._cache_lock:
            hit_rate = (self._cache_hits / max(1, self._total_checks)) * 100

            return {
                'cache_size': len(self._cache),
                'cache_limit': self.cache_size_limit,
                'cache_usage_percent': (len(self._cache) / self.cache_size_limit) * 100,
                'total_checks': self._total_checks,
                'cache_hits': self._cache_hits,
                'cache_misses': self._cache_misses,
                'database_hits': self._database_hits,
                'duplicates_found': self._duplicates_found,
                'hit_rate_percent': hit_rate,
                'cache_ttl_seconds': self.cache_ttl_seconds
            }

    def _check_memory_cache(self, cache_key: str) -> bool:
        """
        Check if a hash exists in memory cache and is not expired.

        Args:
            cache_key: The cache key to check

        Returns:
            bool: True if found and not expired, False otherwise
        """
        if cache_key not in self._cache:
            return False

        timestamp, source_id, table_name = self._cache[cache_key]
        current_time = time.time()

        if current_time - timestamp > self.cache_ttl_seconds:
            del self._cache[cache_key]
            return False

        return True

    def _add_to_cache(self, cache_key: str, source_id: str, table_name: str) -> None:
        """
        Add an entry to the memory cache, managing size limits.

        Args:
            cache_key: The cache key
            source_id: Source database identifier
            table_name: Table name for logging
        """
        with self._cache_lock:
            current_time = time.time()

            if cache_key in self._cache:
                del self._cache[cache_key]

            self._cache[cache_key] = (current_time, source_id, table_name)

            while len(self._cache) > self.cache_size_limit:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

    def _cleanup_expired_cache(self) -> int:
        """
        Remove expired entries from memory cache.

        Returns:
            int: Number of entries removed
        """
        with self._cache_lock:
            current_time = time.time()
            expired_keys = []

            for key, (timestamp, _, _) in self._cache.items():
                if current_time - timestamp > self.cache_ttl_seconds:
                    expired_keys.append(key)

            for key in expired_keys:
                del self._cache[key]

            if expired_keys:
                self.logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")

            return len(expired_keys)

    def _check_database_storage(self, table: str, record_hash: str, source_id: str) -> bool:
        """
        Check if a hash exists in the persistent deduplication tracker.

        Args:
            table: Table name
            record_hash: Content hash to check
            source_id: Source database identifier

        Returns:
            bool: True if hash exists in database, False otherwise
        """
        try:

            self._ensure_dedup_tracker_table()

            conn = connect_db("KINGDOM", target=True)
            cursor = conn.cursor()

            try:
                cursor.execute("""
                    SELECT source_id, created_at
                    FROM dbo.sync_dedup_tracker
                    WHERE table_name = ? AND record_hash = ?
                """, (table, record_hash))

                result = cursor.fetchone()
                if result:
                    original_source, created_at = result
                    # Duplicate found in database (debug log removed)

                    cursor.execute("""
                        UPDATE dbo.sync_dedup_tracker
                        SET last_seen_at = GETDATE()
                        WHERE table_name = ? AND record_hash = ?
                    """, (table, record_hash))
                    conn.commit()

                    return True

                return False

            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            self.logger.error(f"Error checking database storage for {table}", exc=e)
            return False

    def _store_in_database(self, table: str, record_hash: str, source_id: str) -> None:
        """
        Store a processed record hash in the persistent deduplication tracker.

        Args:
            table: Table name
            record_hash: Content hash to store
            source_id: Source database identifier
        """
        try:
            self._ensure_dedup_tracker_table()

            conn = connect_db("KINGDOM", target=True)
            cursor = conn.cursor()

            try:
                cursor.execute("""
                    MERGE dbo.sync_dedup_tracker AS target
                    USING (SELECT ? as table_name, ? as record_hash, ? as source_id) AS source
                    ON (target.table_name = source.table_name AND target.record_hash = source.record_hash)
                    WHEN MATCHED THEN
                        UPDATE SET last_seen_at = GETDATE()
                    WHEN NOT MATCHED THEN
                        INSERT (table_name, record_hash, source_id, created_at, last_seen_at)
                        VALUES (source.table_name, source.record_hash, source.source_id, GETDATE(), GETDATE());
                """, (table, record_hash, source_id))

                conn.commit()

            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            self.logger.error(f"Error storing hash in database for {table}", exc=e)

    def _ensure_dedup_tracker_table(self) -> None:
        """
        Ensure the deduplication tracker table exists in the target database.

        This method creates the table and indexes if they don't exist.
        """
        try:
            conn = connect_db("KINGDOM", target=True)
            cursor = conn.cursor()

            try:
                cursor.execute("""
                    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'sync_dedup_tracker' AND schema_id = SCHEMA_ID('dbo'))
                    BEGIN
                        CREATE TABLE dbo.sync_dedup_tracker (
                            id BIGINT IDENTITY(1,1) PRIMARY KEY,
                            table_name NVARCHAR(255) NOT NULL,
                            record_hash VARCHAR(64) NOT NULL,
                            source_id VARCHAR(50) NOT NULL,
                            created_at DATETIME2 DEFAULT GETDATE(),
                            last_seen_at DATETIME2 DEFAULT GETDATE(),

                            CONSTRAINT UQ_sync_dedup_tracker_hash UNIQUE (table_name, record_hash)
                        );
                        PRINT 'Created sync_dedup_tracker table';
                    END
                """)

                cursor.execute("""
                    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_sync_dedup_tracker_table_hash'
                                   AND object_id = OBJECT_ID('dbo.sync_dedup_tracker'))
                    BEGIN
                        CREATE INDEX IX_sync_dedup_tracker_table_hash
                        ON dbo.sync_dedup_tracker (table_name, record_hash);
                        PRINT 'Created hash lookup index';
                    END
                """)

                cursor.execute("""
                    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_sync_dedup_tracker_cleanup'
                                   AND object_id = OBJECT_ID('dbo.sync_dedup_tracker'))
                    BEGIN
                        CREATE INDEX IX_sync_dedup_tracker_cleanup
                        ON dbo.sync_dedup_tracker (created_at);
                        PRINT 'Created cleanup index';
                    END
                """)

                cursor.execute("""
                    IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_sync_dedup_tracker_source'
                                   AND object_id = OBJECT_ID('dbo.sync_dedup_tracker'))
                    BEGIN
                        CREATE INDEX IX_sync_dedup_tracker_source
                        ON dbo.sync_dedup_tracker (source_id, created_at);
                        PRINT 'Created source index';
                    END
                """)

                conn.commit()

            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            self.logger.error("Failed to ensure deduplication tracker table exists", exc=e)
            raise



def create_deduplication_engine(config: Dict[str, Any] = None) -> DeduplicationEngine:
    """
    Factory function to create a configured DeduplicationEngine instance.

    Args:
        config: Optional configuration dictionary with cache_size_limit and cache_ttl_seconds

    Returns:
        DeduplicationEngine: Configured deduplication engine instance
    """
    config = config or {}

    cache_size = config.get('cache_size_limit', 1000000)  # 1M default
    cache_ttl = config.get('cache_ttl_seconds', 3600)     # 1 hour default

    return DeduplicationEngine(cache_size_limit=cache_size, cache_ttl_seconds=cache_ttl)


def validate_deduplication_setup() -> bool:
    """
    Validate that the deduplication system is properly set up.

    Returns:
        bool: True if setup is valid, False otherwise
    """
    try:
        engine = DeduplicationEngine()
        test_record = {'id': 1, 'name': 'test'}
        test_result = engine.is_duplicate('test_table', test_record, 'TEST_SOURCE')

        Logger.success("Deduplication engine validation passed")
        return True

    except Exception as e:
        Logger.error("Deduplication engine validation failed", exc=e)
        return False


