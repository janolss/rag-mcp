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
- Default max file size is 2 MiB.
- Allowed suffixes are limited to common text/code/doc extensions.

## Logging

Denied paths are logged with the reason and file name only. File contents are
never written to logs.

## Integration

`walk_files` and partial `--files` indexing both call `assert_within_roots`
before reading content.
