# Atomic full indexing (Phase 6)

Full rebuilds write to a staging collection first:

1. Create staging collection
2. Embed and upsert into staging
3. Verify non-empty result
4. Activate staging via `CollectionRouter`
5. Keep the previous generation for rollback

If embedding or upsert fails before activation, the previously active
collection remains unchanged.
