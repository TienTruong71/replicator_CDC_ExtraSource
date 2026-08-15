import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
import pyodbc
import time
from threading import Lock

try:
    from logger import Logger
except ImportError:
    from .logger import Logger

try:
    from db_utils import connect_db
except ImportError:
    from .db_utils import connect_db


@dataclass
class SourceConfig:
    """Configuration for a single database source."""
    prefix: str
    host: str
    port: int
    database: str
    username: str
    password: str
    source_id: str
    insert_only: bool = False
    batch_size: int = 500
    poll_interval: float = 1.0

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.host:
            raise ValueError(f"Host is required for source {self.prefix}")
        if not self.database:
            raise ValueError(f"Database is required for source {self.prefix}")
        if not self.username:
            raise ValueError(f"Username is required for source {self.prefix}")
        if self.port <= 0:
            raise ValueError(f"Port must be positive for source {self.prefix}")


@dataclass
class ValidationResult:
    """Result of configuration validation."""
    is_valid: bool
    source_results: Dict[str, bool]
    errors: Dict[str, str]

    def __post_init__(self):
        """Calculate overall validity based on source results."""
        self.is_valid = len(self.source_results) > 0 and all(self.source_results.values())


class MultiSourceConfig:
    """
    Manages configuration for multiple database sources with validation and hot-reloading.

    This class parses environment variables with different prefixes (SOURCEA_, SOURCEB_, etc.)
    and provides validated source configurations for the replicator.
    """

    def __init__(self):
        self._config_lock = Lock()
        self._sources: Dict[str, SourceConfig] = {}
        self._last_load_time = 0
        self._env_file_mtime = 0
        load_dotenv()

    def load_sources(self) -> Dict[str, SourceConfig]:
        """
        Load and parse all configured sources from environment variables.

        Returns:
            Dict[str, SourceConfig]: Dictionary mapping source_id to SourceConfig
        """
        with self._config_lock:
            self._sources.clear()

            try:
                from db_utils import get_source_prefix
                prefix = get_source_prefix()
            except ImportError:
                prefix = "SOURCE"

            source_prefixes = [prefix]

            Logger.info(f"Loading configurations for sources: {', '.join(source_prefixes)}")

            for prefix in source_prefixes:
                try:
                    source_config = self._load_source_config(prefix)
                    if source_config:
                        self._sources[source_config.source_id] = source_config
                        Logger.success(f"Loaded configuration for source: {source_config.source_id}")
                except Exception as e:
                    Logger.error(f"Failed to load configuration for prefix {prefix}", exc=e)

            self._last_load_time = time.time()
            Logger.info(f"Successfully loaded {len(self._sources)} source configurations")

            return self._sources.copy()

    def validate_connectivity(self) -> ValidationResult:
        """
        Validate database connectivity for all configured sources.

        Returns:
            ValidationResult: Validation results including per-source status
        """
        Logger.info("Validating database connectivity for all sources...")

        source_results = {}
        errors = {}

        for source_id, config in self._sources.items():
            try:
                Logger.info(f"Testing connection to {source_id} ({config.host}:{config.port}/{config.database})")

                src_conn = None
                try:
                    src_conn = connect_db(config.prefix, target=False)
                    cursor = src_conn.cursor()
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                    cursor.close()

                    Logger.success(f"Source database connection validated for {source_id}")
                    source_results[source_id] = True

                except Exception as src_err:
                    error_msg = f"Source database connection failed: {str(src_err)}"
                    Logger.error(f"Source validation failed for {source_id}: {error_msg}")
                    source_results[source_id] = False
                    errors[source_id] = error_msg
                finally:
                    if src_conn:
                        try:
                            src_conn.close()
                        except:
                            pass

                if source_results.get(source_id, False):
                    dst_conn = None
                    try:
                        dst_conn = connect_db(config.prefix, target=True)
                        cursor = dst_conn.cursor()
                        cursor.execute("SELECT 1")
                        cursor.fetchone()
                        cursor.close()

                        Logger.success(f"Target database connection validated for {source_id}")

                    except Exception as dst_err:
                        error_msg = f"Target database connection failed: {str(dst_err)}"
                        Logger.error(f"Target validation failed for {source_id}: {error_msg}")
                        source_results[source_id] = False
                        errors[source_id] = error_msg
                    finally:
                        if dst_conn:
                            try:
                                dst_conn.close()
                            except:
                                pass

            except Exception as e:
                error_msg = f"Configuration validation error: {str(e)}"
                Logger.error(f"Validation failed for {source_id}: {error_msg}")
                source_results[source_id] = False
                errors[source_id] = error_msg

        result = ValidationResult(
            is_valid=False,  # Will be calculated in __post_init__
            source_results=source_results,
            errors=errors
        )

        if result.is_valid:
            Logger.success(f"All {len(source_results)} sources validated successfully")
        else:
            failed_sources = [sid for sid, valid in source_results.items() if not valid]
            Logger.error(f"Validation failed for sources: {', '.join(failed_sources)}")

        return result

    def get_insert_only_sources(self) -> List[str]:
        """
        Get list of source IDs that are configured for insert-only mode.

        Returns:
            List[str]: List of source IDs with insert_only=True
        """
        insert_only_sources = [
            source_id for source_id, config in self._sources.items()
            if config.insert_only
        ]

        if insert_only_sources:
            Logger.info(f"Insert-only sources: {', '.join(insert_only_sources)}")
        else:
            Logger.info("No sources configured for insert-only mode")

        return insert_only_sources

    def reload_config(self) -> None:
        """
        Reload configuration from environment variables if changes are detected.

        This method checks for changes in the .env file modification time and
        reloads configuration if needed.
        """
        # Check if .env file has been modified
        env_file_path = ".env"
        current_mtime = 0

        if os.path.exists(env_file_path):
            current_mtime = os.path.getmtime(env_file_path)

        if current_mtime > self._env_file_mtime:
            Logger.info("Configuration file changes detected, reloading...")
            self._env_file_mtime = current_mtime

            # Reload environment variables
            load_dotenv(override=True)

            # Reload source configurations
            old_count = len(self._sources)
            self.load_sources()
            new_count = len(self._sources)

            Logger.success(f"Configuration reloaded: {old_count} -> {new_count} sources")

    def get_source_config(self, source_id: str) -> Optional[SourceConfig]:
        """
        Get configuration for a specific source.

        Args:
            source_id: The source identifier

        Returns:
            Optional[SourceConfig]: The source configuration or None if not found
        """
        return self._sources.get(source_id)

    def get_all_sources(self) -> Dict[str, SourceConfig]:
        """
        Get all loaded source configurations.

        Returns:
            Dict[str, SourceConfig]: Copy of all source configurations
        """
        with self._config_lock:
            return self._sources.copy()

    def _has_legacy_config(self) -> bool:
        """Check if legacy KINGDOM_ configuration exists."""
        return bool(
            os.getenv("KINGDOM_SQLSERVER_HOST") and
            os.getenv("KINGDOM_SQLSERVER_DB") and
            os.getenv("KINGDOM_SQLSERVER_USER")
        )

    def _load_legacy_config(self) -> Optional[SourceConfig]:
        """Load legacy KINGDOM_ configuration for backward compatibility."""
        try:
            host = os.getenv("KINGDOM_SQLSERVER_HOST")
            database = os.getenv("KINGDOM_SQLSERVER_DB")
            username = os.getenv("KINGDOM_SQLSERVER_USER")
            password = os.getenv("KINGDOM_SQLSERVER_PASS", "")
            port = int(os.getenv("KINGDOM_SQLSERVER_PORT", "1433"))
            batch_size = int(os.getenv("KINGDOM_BATCH_SIZE", "500"))
            poll_interval = float(os.getenv("KINGDOM_POLL_INTERVAL", "1.0"))

            # Check for insert-only mode (not in legacy but we include for future compatibility)
            insert_only = os.getenv("KINGDOM_INSERT_ONLY", "false").lower() in ("true", "1", "yes")

            return SourceConfig(
                prefix="KINGDOM",
                host=host,
                port=port,
                database=database,
                username=username,
                password=password,
                source_id="KINGDOM",
                insert_only=insert_only,
                batch_size=batch_size,
                poll_interval=poll_interval
            )

        except (ValueError, TypeError) as e:
            Logger.error(f"Failed to parse legacy KINGDOM configuration", exc=e)
            return None

    def _load_source_config(self, prefix: str) -> Optional[SourceConfig]:
        """
        Load configuration for a single source prefix.

        Args:
            prefix: The environment variable prefix (e.g., 'SOURCEA')

        Returns:
            Optional[SourceConfig]: The loaded configuration or None if invalid
        """
        prefix = prefix.upper()

        # Required parameters
        host = os.getenv(f"{prefix}_SQLSERVER_HOST")
        database = os.getenv(f"{prefix}_SQLSERVER_DB")
        username = os.getenv(f"{prefix}_SQLSERVER_USER")
        password = os.getenv(f"{prefix}_SQLSERVER_PASS", "")

        # Optional parameters with defaults
        port_str = os.getenv(f"{prefix}_SQLSERVER_PORT", "1433")
        try:
            from db_utils import get_source_id
            source_id = get_source_id()
        except ImportError:
            source_id = os.getenv("SOURCE_ID", prefix)
        batch_size_str = os.getenv(f"{prefix}_BATCH_SIZE", "500")
        poll_interval_str = os.getenv(f"{prefix}_POLL_INTERVAL", "1.0")
        insert_only_str = os.getenv(f"{prefix}_INSERT_ONLY", "false")

        # Validate required parameters
        if not host:
            Logger.error(f"Missing required parameter: {prefix}_SQLSERVER_HOST")
            return None

        if not database:
            Logger.error(f"Missing required parameter: {prefix}_SQLSERVER_DB")
            return None

        if not username:
            Logger.error(f"Missing required parameter: {prefix}_SQLSERVER_USER")
            return None

        # Parse and validate optional parameters
        try:
            port = int(port_str)
            if port <= 0:
                Logger.error(f"Invalid port for {prefix}: {port_str}")
                return None
        except ValueError:
            Logger.error(f"Invalid port format for {prefix}: {port_str}")
            return None

        try:
            batch_size = int(batch_size_str)
            if batch_size <= 0:
                Logger.error(f"Invalid batch_size for {prefix}: {batch_size_str}")
                return None
        except ValueError:
            Logger.error(f"Invalid batch_size format for {prefix}: {batch_size_str}")
            return None

        try:
            poll_interval = float(poll_interval_str)
            if poll_interval <= 0:
                Logger.error(f"Invalid poll_interval for {prefix}: {poll_interval_str}")
                return None
        except ValueError:
            Logger.error(f"Invalid poll_interval format for {prefix}: {poll_interval_str}")
            return None

        # Parse insert_only flag
        insert_only = insert_only_str.lower() in ("true", "1", "yes", "on")

        return SourceConfig(
            prefix=prefix,
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            source_id=source_id,
            insert_only=insert_only,
            batch_size=batch_size,
            poll_interval=poll_interval
        )