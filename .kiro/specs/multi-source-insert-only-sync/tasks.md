# Implementation Plan: Multi-Source Insert-Only Sync

## Overview

This implementation plan transforms the existing single-source CDC replicator into a multi-source system with insert-only operations and intelligent deduplication. The approach maintains backward compatibility while adding new capabilities incrementally.

## Tasks

- [x] 1. Enhance database schema for multi-source support
  - [x] 1.1 Add status column to audit log table
    - Modify setup_triggers.py to add status column with default 'pending'
    - Add indexes for efficient status-based queries
    - Ensure backward compatibility with existing audit log data
    - _Requirements: 2.3, 6.1_

  - [ ]* 1.2 Create deduplication tracker table
    - Create dedup_tracker table with hash, source_id, and timestamps
    - Add appropriate indexes for hash lookups and cleanup operations
    - _Requirements: 3.1, 6.2_

  - [ ]* 1.3 Write property test for schema modifications
    - **Property 9: Schema Enhancement Compatibility**
    - **Validates: Requirements 6.5**

- [x] 2. Implement multi-source configuration system
  - [x] 2.1 Create MultiSourceConfig class
    - Parse multiple source prefixes from environment variables
    - Validate database connectivity for all sources
    - Support configuration hot-reloading mechanism
    - _Requirements: 1.1, 1.2, 1.5, 9.1, 9.2_

  - [ ]* 2.2 Write property test for multi-source connection isolation
    - **Property 1: Multi-Source Connection Isolation**
    - **Validates: Requirements 1.3**

  - [ ]* 2.3 Write unit tests for configuration validation
    - Test invalid configuration detection and error messages
    - Test connectivity failure scenarios and network vs config issues
    - _Requirements: 9.3, 9.4_

- [ ] 3. Develop deduplication engine
  - [x] 3.1 Implement content hashing algorithm
    - Create deterministic hash computation excluding metadata columns
    - Use SHA-256 for cryptographic strength and collision resistance
    - Normalize record content for consistent hashing
    - _Requirements: 3.4, 3.5_

  - [ ]* 3.2 Write property test for content hash determinism
    - **Property 4: Content Hash Determinism**
    - **Validates: Requirements 3.5**

  - [-] 3.3 Implement DeduplicationEngine class
    - Create hash-based duplicate detection logic
    - Integrate with memory cache and persistent storage
    - Log duplicate events with detailed information
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 3.4 Write property test for deduplication effectiveness
    - **Property 5: Deduplication Effectiveness**
    - **Validates: Requirements 3.2, 3.3**

- [ ] 4. Build memory cache management system
  - [~] 4.1 Create MemoryCache class with LRU eviction
    - Implement LRU cache with configurable TTL and capacity limits
    - Support up to 1 million entries within 512MB memory constraint
    - Provide cache statistics and monitoring capabilities
    - _Requirements: 5.1, 5.2, 5.5_

  - [ ]* 4.2 Write property test for LRU cache eviction correctness
    - **Property 7: LRU Cache Eviction Correctness**
    - **Validates: Requirements 5.2**

  - [~] 4.3 Implement cache-database fallback mechanism
    - Create seamless fallback from memory cache to persistent storage
    - Ensure consistency between cache and database results
    - _Requirements: 5.3, 5.4_

  - [ ]* 4.4 Write property test for cache-database fallback consistency
    - **Property 8: Cache-Database Fallback Consistency**
    - **Validates: Requirements 5.4**

- [~] 5. Checkpoint - Core components validation
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Implement insert-only synchronization mode
  - [~] 6.1 Modify audit log processing for insert-only operations
    - Convert UPDATE operations to INSERT operations in replicator.py
    - Ignore DELETE operations when insert-only mode is enabled
    - Preserve original timestamp and add source metadata
    - _Requirements: 2.1, 2.2, 2.5_

  - [ ]* 6.2 Write property test for insert-only operation conversion
    - **Property 2: Insert-Only Operation Conversion**
    - **Validates: Requirements 2.1**

  - [~] 6.3 Implement status tracking for processed records
    - Update audit log status atomically with processing actions
    - Mark records as 'processed', 'duplicate', or 'error' appropriately
    - _Requirements: 2.4_

  - [ ]* 6.4 Write property test for status tracking consistency
    - **Property 3: Status Tracking Consistency**
    - **Validates: Requirements 2.4**

- [ ] 7. Build recovery and startup processing system
  - [~] 7.1 Create RecoveryController class
    - Identify unprocessed records across all sources at startup
    - Process recovered records in chronological order
    - Complete recovery within 30 seconds for up to 100,000 records
    - _Requirements: 4.1, 4.2, 4.4_

  - [ ]* 7.2 Write property test for recovery completeness
    - **Property 6: Recovery Completeness**
    - **Validates: Requirements 4.1, 4.2**

  - [~] 7.3 Implement crash-resistant recovery mechanism
    - Prevent duplicate insertions during recovery processing
    - Handle recovery failures per source independently
    - _Requirements: 4.3, 4.5_

  - [ ]* 7.4 Write integration tests for recovery scenarios
    - Test crash simulation and restart verification
    - Test partial recovery failure handling
    - _Requirements: 4.3, 4.5_

- [ ] 8. Integrate multi-source processing into main replicator
  - [~] 8.1 Create MultiSourceProcessor class
    - Orchestrate parallel processing of multiple audit logs
    - Maintain separate connection pools per source
    - Handle source-specific errors without affecting others
    - _Requirements: 1.2, 1.3, 1.4_

  - [~] 8.2 Modify main replicator loop in replicator.py
    - Integrate multi-source processor with existing single-source logic
    - Maintain backward compatibility for single-source deployments
    - Add enhanced logging with source identification
    - _Requirements: 8.1, 8.2, 10.1, 10.2_

  - [ ]* 8.3 Write integration tests for multi-source processing
    - Test parallel processing with multiple test databases
    - Validate source isolation and error handling
    - _Requirements: 1.3, 1.4_

- [ ] 9. Implement cleanup and maintenance scheduler
  - [~] 9.1 Create CleanupScheduler class
    - Implement 24-hour automated cleanup of old tracking records
    - Remove dedup_tracker records older than retention period
    - Remove processed audit log records based on configuration
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 9.2 Write unit tests for cleanup operations
    - Test retention period logic and data preservation
    - Test cleanup failure handling and error logging
    - _Requirements: 7.5_

- [ ] 10. Enhance logging and monitoring capabilities
  - [~] 10.1 Add source-aware logging throughout the system
    - Include source database identifier in all log messages
    - Log detailed duplicate detection information
    - Provide processing metrics per source (rate, errors, duplicates)
    - _Requirements: 8.1, 8.2, 8.4_

  - [~] 10.2 Implement enhanced error context logging
    - Include source context in all error messages
    - Log recovery progress and completion statistics
    - _Requirements: 8.3, 8.5_

- [ ] 11. Final integration and backward compatibility validation
  - [~] 11.1 Ensure backward compatibility for existing deployments
    - Test legacy single-source mode operation
    - Validate existing environment variables continue to work
    - Test migration from single-source to multi-source configuration
    - _Requirements: 10.1, 10.2, 10.4, 10.5_

  - [ ]* 11.2 Write comprehensive integration tests
    - Test full multi-source workflow end-to-end
    - Test configuration migration scenarios
    - Validate performance requirements under load
    - _Requirements: 10.3, 4.4_

- [~] 12. Final checkpoint - Complete system validation
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation and early problem detection
- Property tests validate universal correctness properties across all inputs
- Integration tests verify interaction between components and external systems
- The implementation maintains strict backward compatibility with existing deployments

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "3.1"] },
    { "id": 2, "tasks": ["1.3", "2.3", "3.2", "4.1"] },
    { "id": 3, "tasks": ["3.3", "4.2", "4.3"] },
    { "id": 4, "tasks": ["3.4", "4.4", "6.1"] },
    { "id": 5, "tasks": ["6.2", "6.3", "7.1"] },
    { "id": 6, "tasks": ["6.4", "7.2", "7.3"] },
    { "id": 7, "tasks": ["7.4", "8.1"] },
    { "id": 8, "tasks": ["8.2", "9.1"] },
    { "id": 9, "tasks": ["8.3", "9.2", "10.1"] },
    { "id": 10, "tasks": ["10.2", "11.1"] },
    { "id": 11, "tasks": ["11.2"] }
  ]
}
```