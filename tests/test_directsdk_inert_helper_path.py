"""The Claude helper the spawned CLI is pointed at: the active profile's copy, not ``__file__``.

A host that serves several profiles in one process (a gateway or the Desktop app switching
``HERMES_HOME`` between turns) imports whichever plugin copy came first, so ``Path(__file__)`` can
name a foreign profile's ``inert_mcp.py``. The resolver must prefer the install under the active
``HERMES_HOME`` and keep the module's own directory as the fallback.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import directsdk  # noqa: E402
import directsdk_setup  # noqa: E402

PLUGIN_ID = 'claude-subscription-directsdk-experimental'

# Minimal native CLI: reports its own argv, answers the query frame against ANTHROPIC_BASE_URL
# (the relay's loopback), then emits the terminal stream-json sequence the transport requires.
ARGV_NATIVE = r'''
import json, os, sys, urllib.request, urllib.error
open(os.environ['DIRECTSDK_ARGV_DUMP'], 'w').write(json.dumps(sys.argv))
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
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            calls.append(self.path)
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


def test_inert_helper_comes_from_the_active_profile(tmp_path, monkeypatch):
    """The spawned CLI is handed the helper installed under the active HERMES_HOME."""
    calls = []
    peer, thread = _gateway(calls)
    gateway = f'http://127.0.0.1:{peer.server_port}'
    home = tmp_path / 'hermes-home'
    _write_config(home, {'upstream_base_url': gateway, 'upstream_api_key': 'placeholder'})
    installed = home / 'plugins' / PLUGIN_ID
    installed.mkdir(parents=True)
    (installed / 'inert_mcp.py').write_text('# profile copy\n', encoding='utf-8')
    dump = tmp_path / 'argv.json'
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('ANTHROPIC_BASE_URL', gateway)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'placeholder')
    monkeypatch.setenv('DIRECTSDK_ARGV_DUMP', str(dump))

    native = tmp_path / 'native.py'
    native.write_text(ARGV_NATIVE)
    client = directsdk.Client(command=[sys.executable, str(native)])  # env=None: os.environ is read
    try:
        client.create(model='sonnet', messages=[{'role': 'user', 'content': 'fixture'}])
    finally:
        client.close()
        peer.shutdown()
        thread.join()
        peer.server_close()

    argv = json.loads(Path(dump).read_text())
    config = json.loads(argv[argv.index('--mcp-config') + 1])
    helper = config['mcpServers']['hermes']['args'][0]
    assert helper == str(installed / 'inert_mcp.py'), helper
    # Sanity: the profile copy is not where this module lives, so the assertion proves a real choice.
    assert helper != str(Path(directsdk.__file__).with_name('inert_mcp.py'))


def test_inert_helper_falls_back_to_the_module_directory(tmp_path, monkeypatch):
    """A profile without its own install falls back to this module's sibling, never an error."""
    home = tmp_path / 'hermes-home'
    _write_config(home, {})
    monkeypatch.setenv('HERMES_HOME', str(home))

    assert directsdk_setup.inert_mcp_path() == Path(directsdk_setup.__file__).with_name('inert_mcp.py')


def test_inert_helper_survives_an_unresolvable_home(monkeypatch):
    """No usable Hermes home at all still yields this module's sibling rather than raising."""
    import hermes_constants

    def _boom():
        raise RuntimeError('no home')

    monkeypatch.setattr(hermes_constants, 'get_hermes_home', _boom)

    assert directsdk_setup.inert_mcp_path() == Path(directsdk_setup.__file__).with_name('inert_mcp.py')
    assert os.path.isfile(directsdk_setup.inert_mcp_path())
