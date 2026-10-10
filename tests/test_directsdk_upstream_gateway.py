"""The `upstream_base_url` gateway setting: deliberate Anthropic endpoint/credential overrides.

By default an inherited ``ANTHROPIC_BASE_URL``/``ANTHROPIC_API_KEY`` is a hard error — it would
silently bypass the subscription login. Configuring a gateway flips exactly those two into
intentional, so a local proxy (aiproxy) can hold the real credential while the CLI presents a
placeholder, and the relay talks to the gateway instead of api.anthropic.com.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import directsdk  # noqa: E402

PLUGIN_ID = 'claude-subscription-directsdk-experimental'

# Minimal native CLI: answers the query frame against ANTHROPIC_BASE_URL (the relay's loopback),
# then emits the terminal stream-json sequence the transport requires.
NATIVE = r'''
import json, os, sys, urllib.request, urllib.error
for line in sys.stdin:
    frame = json.loads(line)
    if frame.get('shouldQuery') is False:
        print(json.dumps({'type': 'result', 'num_turns': 0}), flush=True)
        continue
    break
url = os.environ['ANTHROPIC_BASE_URL'] + '/v1/messages'
try:
    urllib.request.urlopen(urllib.request.Request(url, data=b'{}', headers={'Content-Type': 'application/json'}), timeout=5).read()
except urllib.error.HTTPError:
    pass
print(json.dumps({'type': 'assistant', 'message': {'id': 'first', 'role': 'assistant', 'content': [{'type': 'text', 'text': 'FIRST'}]}}))
print(json.dumps({'type': 'stream_event', 'event': {'type': 'message_stop'}}))
print(json.dumps({'type': 'result', 'subtype': 'success', 'usage': {'input_tokens': 0, 'output_tokens': 0}}))
'''

SSE = [
    {'type': 'message_start', 'message': {'id': 'first', 'role': 'assistant', 'model': 'sonnet', 'content': [],
                                          'usage': {'input_tokens': 0, 'output_tokens': 0}}},
    {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
    {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'FIRST'}},
    {'type': 'content_block_stop', 'index': 0},
    {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'},
     'usage': {'input_tokens': 0, 'output_tokens': 0}},
    {'type': 'message_stop'},
]


def _gateway(calls):
    class Peer(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append((self.path, self.headers.get('x-api-key'), self.headers.get('Authorization')))
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(''.join('data: ' + json.dumps(e) + '\n\n' for e in SSE).encode())

    peer = ThreadingHTTPServer(('127.0.0.1', 0), Peer)
    thread = threading.Thread(target=peer.serve_forever, daemon=True)
    thread.start()
    return peer, thread


def _write_config(home: Path, settings: dict) -> None:
    home.mkdir(parents=True, exist_ok=True)
    lines = ['plugins:', '  enabled:', '    - ' + PLUGIN_ID, '  entries:', '    ' + PLUGIN_ID + ':',
             '      settings:']
    for key, value in settings.items():
        lines.append(f'        {key}: "{value}"')
    (home / 'config.yaml').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def test_gateway_setting_waives_endpoint_and_key_conflicts(tmp_path, monkeypatch):
    """With a gateway configured, the relay forwards to it and the request succeeds."""
    calls = []
    peer, thread = _gateway(calls)
    gateway = f'http://127.0.0.1:{peer.server_port}'
    home = tmp_path / 'hermes-home'
    _write_config(home, {'upstream_base_url': gateway, 'upstream_api_key': 'placeholder'})
    monkeypatch.setenv('HERMES_HOME', str(home))
    # The overrides that are a hard error without a gateway.
    monkeypatch.setenv('ANTHROPIC_BASE_URL', gateway)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'placeholder')

    native = tmp_path / 'native.py'
    native.write_text(NATIVE)
    client = directsdk.Client(command=[sys.executable, str(native)])  # env=None: os.environ is read
    try:
        result = client.create(model='sonnet', messages=[{'role': 'user', 'content': 'fixture'}])
        assert len(calls) == 1, calls
        assert calls[0][0].startswith('/v1/messages')
        assert result.choices[0].message.content == 'FIRST'
    finally:
        client.close()
        peer.shutdown()
        thread.join()
        peer.server_close()


def test_no_gateway_still_refuses_inherited_overrides(tmp_path, monkeypatch):
    """Regression guard: without the setting the conflict stays a hard error."""
    home = tmp_path / 'hermes-home'
    _write_config(home, {})
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('ANTHROPIC_BASE_URL', 'http://127.0.0.1:9')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'placeholder')

    native = tmp_path / 'native.py'
    native.write_text(NATIVE)
    client = directsdk.Client(command=[sys.executable, str(native)])
    try:
        with pytest.raises(ValueError, match='conflicting native auth/backend overrides'):
            client.create(model='sonnet', messages=[{'role': 'user', 'content': 'fixture'}])
    finally:
        client.close()
