# Changelog

## [0.3.4] - Unreleased

### Added

- `upstream_base_url` / `upstream_api_key` settings: route this provider through an LLM gateway or
  proxy instead of `api.anthropic.com`. While a gateway URL is set, an inherited
  `ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY` counts as intentional rather than as a conflicting
  override, and the native CLI authenticates to the gateway with the configured placeholder — so a
  gateway holding the real credential (a local aiproxy with a subscription token, say) needs no
  Claude login where Hermes runs. Cloud-backend flags are still refused.

### Fixed

- Accept Hermes Relay's host-local `traceparent` request metadata without forwarding it to the native CLI or upstream, preventing full agent and fallback requests from failing on `extra_headers`.
- Continue rejecting arbitrary headers, credential overrides, and malformed header containers at the transport boundary.
