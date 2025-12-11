## 2024-05-23 - [N+1 Query in Batch Sync]
**Learning:** Even with local SQLite databases, N+1 query patterns (looping over inputs and running SELECT+UPDATE for each) introduce significant overhead.
**Action:** Always prefer `WHERE id IN (...)` for bulk fetching and `executemany` for bulk updates.
**Details:** Found `api_sync_batch` running 2 queries per card. Optimized to 2 queries total per batch (1 select + 1 bulk update). Benchmarks showed 1.33x speedup on local DB with 5000 items, and it significantly reduces transaction overhead.
