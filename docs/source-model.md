# Source model

## Contract

Each workspace owns one or more `Source` objects:

- `id`: unique within the workspace
- `type`: document type (`source_code`, `architecture_docs`, ...)
- `root`: absolute/normalized root path
- `include` / `exclude`: glob patterns
- `adapter`: extractor name (`filesystem` by default)
- `status`: `not_indexed|indexing|ready|partial|error`
- `bucket`: optional derived classification (`knowledge|code|lis`)

## Legacy mapping

When no manifests are configured, enabled `index.knowledge` / `index.code` /
`index.lis` globs become sources named `knowledge`, `code` and `lis`.

## Safety note

Manifest roots are registered, but indexing still uses the legacy glob walker
for the synthetic default workspace until path security is in place. Newly
declared roots must not be activated for ingestion before that gate.
