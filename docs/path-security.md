# Path security

## Defaults

- Symlinks are denied unless `allow_symlinks=True`.
- Files must resolve inside a registered root.
- Absolute LIS mirrors are allowed only when their root is registered as an
  extra root / source root.
- Secret-like names are refused, including `.env*`, `.npmrc`, `credentials.json`,
  `service-account.json`, `secrets.yaml` / `secrets.yml`, `local.settings.json`,
  `kubeconfig`, and common private key basenames (`id_rsa`, `id_ed25519`, …).
- Secret-like suffixes: `.pem`, `.key`, `.p12`, `.pfx`, `.jks`, `.keystore`,
  `.ovpn`, `.p8`.
- Operators may extend the denylist via `index.extra_secret_names` and
  `index.extra_secret_suffixes` in `config.yaml` (unioned with the defaults).
- Default max file size is 2 MiB.
- Allowed suffixes cover common text/code/doc extensions, including
  `.rs`, `.swift`, `.metal`, `.c`/`.h`/`.m`, `.cs`, `.vue`, `.html`, `.sql`,
  `.sh`, `.bicep`/`.bicepparam`, `.pdf`, `.docx`, and `.sru` (plus the original
  markdown/JS/TS/Python/YAML/TOML set). Binaries (e.g. `.pt`, `.png`, `.mp4`)
  remain blocked.

## Logging

Denied paths are logged with the reason and file name only. File contents are
never written to logs.

## Integration

`walk_files` and partial `--files` indexing both call `assert_within_roots`
before reading content.
