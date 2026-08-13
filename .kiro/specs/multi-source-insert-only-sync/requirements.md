# Requirements Document

## Introduction

The multi-source insert-only sync feature extends the existing CDC replicator to support data synchronization from multiple source databases with insert-only deduplication capabilities. This feature enables horizontal scaling of data ingestion while maintaining data consistency and recovery capabilities after system crashes.

## Glossary

- **Replicator**: The CDC (Change Data Capture) system that synchronizes data between databases
- **Source_Database**: A database being monitored for changes and synchronized from
- **Target_Database**: The destination database where all changes are replicated to
- **Insert_Only_Mode**: A synchronization mode that only performs INSERT operations, never UPDATE or DELETE
- **Deduplication_Tracker**: A system component that prevents duplicate data insertion across multiple sources
- **Recovery_Processor**: A component that handles startup recovery after system crashes
- **Memory_Cache**: An in-memory storage for tracking recently processed records
- **Audit_Log**: The sync_audit_log table that captures all database changes
- **Source_Config**: Configuration defining multiple database sources with their connection parameters
- **Cleanup_Scheduler**: A background process that maintains deduplication tracking tables

## Requirements

### Requirement 1: Multi-Source Configuration Support

**User Story:** As a system administrator, I want to configure multiple source databases for synchronization, so that I can consolidate data from different systems into a single target database.

#### Acceptance Criteria

1. WHEN the system starts, THE Replicator SHALL load source database configurations from environment variables
2. WHEN multiple source prefixes are defined, THE Replicator SHALL establish separate connections to each source database
3. WHEN a source database connection fails, THE Replicator SHALL continue processing other sources and retry the failed connection
4. THE Source_Config SHALL support at least 10 concurrent source database connections
5. WHEN configuration changes are detected, THE Replicator SHALL reload the configuration without requiring a restart

### Requirement 2: Insert-Only Synchronization Mode

**User Story:** As a data engineer, I want insert-only synchronization mode, so that I can merge data from multiple sources without conflicts from updates and deletes.

#### Acceptance Criteria

1. WHEN insert-only mode is enabled, THE Replicator SHALL convert all UPDATE operations to INSERT operations
2. WHEN insert-only mode is enabled, THE Replicator SHALL ignore DELETE operations from the audit log
3. THE Audit_Log SHALL include a new status column to track processing state of each record
4. WHEN a record is processed, THE Replicator SHALL mark it as 'processed' in the audit log status column
5. WHEN insert-only mode processes an UPDATE, THE Replicator SHALL preserve the original timestamp and add source metadata

### Requirement 3: Deduplication System

**User Story:** As a data engineer, I want automatic deduplication across multiple sources, so that identical records from different databases are not inserted multiple times.

#### Acceptance Criteria

1. THE Deduplication_Tracker SHALL maintain a hash-based index of processed records for each table
2. WHEN a record is about to be inserted, THE Deduplication_Tracker SHALL check if an equivalent record already exists
3. WHEN duplicate records are detected, THE Replicator SHALL skip the insertion and log the duplicate event
4. THE Deduplication_Tracker SHALL use a combination of table name, primary key, and content hash for uniqueness detection
5. WHEN content hashing is performed, THE Replicator SHALL exclude timestamp and metadata columns from the hash calculation

### Requirement 4: Recovery and Startup Processing

**User Story:** As a system administrator, I want automatic recovery after system crashes, so that no data synchronization is lost and the system can resume operation safely.

#### Acceptance Criteria

1. WHEN the system starts up, THE Recovery_Processor SHALL identify all unprocessed records in audit logs across all sources
2. WHEN unprocessed records are found, THE Recovery_Processor SHALL process them in chronological order before starting live synchronization
3. WHEN processing recovered records, THE Deduplication_Tracker SHALL prevent duplicate insertions that may have occurred during the crash
4. THE Recovery_Processor SHALL complete startup recovery within 30 seconds for databases with up to 100,000 pending records
5. WHEN recovery processing fails for a specific source, THE Replicator SHALL continue with other sources and retry the failed source

### Requirement 5: Memory Cache Management

**User Story:** As a system administrator, I want efficient memory usage for deduplication tracking, so that the system can handle high-volume data synchronization without excessive memory consumption.

#### Acceptance Criteria

1. THE Memory_Cache SHALL store recently processed record hashes with a configurable TTL (Time To Live)
2. WHEN memory cache reaches its size limit, THE Memory_Cache SHALL evict oldest entries using LRU (Least Recently Used) policy
3. THE Memory_Cache SHALL be backed by persistent deduplication tracking tables in the database
4. WHEN a record hash is not found in memory cache, THE Deduplication_Tracker SHALL check the persistent storage
5. THE Memory_Cache SHALL support up to 1 million cached record hashes while consuming less than 512MB of memory

### Requirement 6: Database Schema Enhancements

**User Story:** As a database administrator, I want schema enhancements to support multi-source synchronization, so that the system can track processing state and deduplication metadata.

#### Acceptance Criteria

1. THE Audit_Log SHALL include a new 'status' column with values: 'pending', 'processed', 'error', 'duplicate'
2. THE system SHALL create a 'dedup_tracker' table with columns: table_name, record_hash, source_id, created_at
3. WHEN audit log records are created, THE status column SHALL default to 'pending'
4. THE dedup_tracker table SHALL have appropriate indexes for efficient hash lookups and cleanup operations
5. WHEN schema modifications are applied, THE system SHALL maintain backward compatibility with existing audit log data

### Requirement 7: Cleanup and Maintenance

**User Story:** As a system administrator, I want automated cleanup of tracking data, so that the system maintains optimal performance over time without manual intervention.

#### Acceptance Criteria

1. THE Cleanup_Scheduler SHALL run automatically every 24 hours to remove old deduplication tracking records
2. WHEN cleanup runs, THE Cleanup_Scheduler SHALL remove dedup_tracker records older than the configured retention period
3. WHEN cleanup runs, THE Cleanup_Scheduler SHALL remove processed audit log records older than the configured retention period
4. THE Cleanup_Scheduler SHALL preserve at least 7 days of tracking data by default
5. WHEN cleanup operations fail, THE system SHALL log errors and continue normal operation

### Requirement 8: Enhanced Logging and Monitoring

**User Story:** As a system operator, I want comprehensive logging for multi-source operations, so that I can monitor system health and troubleshoot issues effectively.

#### Acceptance Criteria

1. WHEN processing records from multiple sources, THE Replicator SHALL log the source database identifier for each operation
2. WHEN duplicate records are detected, THE system SHALL log detailed information including source, table, and hash values
3. WHEN recovery processing occurs, THE system SHALL log progress and completion statistics for each source
4. THE system SHALL provide metrics on processing rate, duplicate detection rate, and error rates per source
5. WHEN errors occur during multi-source processing, THE system SHALL include source context in error messages

### Requirement 9: Configuration Validation

**User Story:** As a system administrator, I want configuration validation for multi-source setup, so that I can detect and fix configuration issues before they cause runtime failures.

#### Acceptance Criteria

1. WHEN the system starts, THE Replicator SHALL validate all source database connection parameters
2. WHEN invalid configuration is detected, THE system SHALL log specific error messages and refuse to start
3. WHEN source database connectivity fails during validation, THE system SHALL distinguish between network and configuration issues
4. THE system SHALL validate that insert-only mode configuration is consistent across all sources
5. WHEN configuration validation passes, THE system SHALL log successful validation for each configured source

### Requirement 10: Backward Compatibility

**User Story:** As a system administrator, I want the new multi-source feature to be backward compatible, so that existing single-source deployments continue to work without modification.

#### Acceptance Criteria

1. WHEN no multi-source configuration is provided, THE system SHALL operate in legacy single-source mode
2. WHEN legacy environment variables are used, THE system SHALL function exactly as before the multi-source enhancement
3. WHEN existing audit log tables are present, THE system SHALL gracefully add new columns without data loss
4. THE system SHALL maintain all existing command-line options and their behavior
5. WHEN upgrading from single-source to multi-source, THE system SHALL migrate existing audit log data to include status information