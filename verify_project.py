from pathlib import Path
import py_compile

root = Path(__file__).resolve().parent

targets = [
    root / 'app' / 'gui.py',
    root / 'app' / 'config.py',
    root / 'app' / 'scanner' / 'live_signal_scanner.py',
    root / 'app' / 'scanner' / 'test_live_signal_scanner.py',
    root / 'app' / 'market' / 'feature_engine.py',
    root / 'app' / 'market' / 'score_engine.py',
    root / 'app' / 'exchange' / 'websocket_manager.py',
]

for path in targets:
    py_compile.compile(str(path), doraise=True)
    print('OK', path.relative_to(root))

try:
    import google.protobuf
    from google.protobuf import __version__ as protobuf_version
    print('protobuf runtime:', protobuf_version)
except Exception as exc:
    print('WARNING: protobuf runtime could not be imported:', exc)

print('PROJECT FILE CHECK PASSED')
