# Changelog

## [0.3.5] - Unreleased

### Fixed

- Point the spawned CLI at the active profile's `inert_mcp.py` instead of `Path(__file__)`'s
  sibling. A host that serves several profiles in one process (a gateway, or the Desktop app
  switching `HERMES_HOME` between turns) imports whichever plugin copy came first, so the child
  was handed a foreign profile's helper; the resolver now follows `get_hermes_home()` and falls
  back to this module's directory only when the profile has no install of its own.

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
