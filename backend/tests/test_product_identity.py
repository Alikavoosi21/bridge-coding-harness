"""Separate application data and vault; never access the actual user vault."""
import json
from pathlib import Path

from server import keychain, settings


def test_default_home_does_not_open_legacy_settings(tmp_path, monkeypatch):
    monkeypatch.delenv('HARNESS_HOME', raising=False)
    monkeypatch.setenv('APPDATA', str(tmp_path))
    legacy = tmp_path / 'OnboardHarness'
    legacy.mkdir()
    content = '{"default_model":"legacy-private-model"}'
    (legacy / 'settings.json').write_text(content)
    assert settings.home() == tmp_path / 'BridgeCodingHarness'
    assert settings.load()['default_model'] == 'demo'
    settings.save(settings.load())
    assert (legacy / 'settings.json').read_text() == content


def test_credential_service_is_independent(monkeypatch):
    calls = []
    monkeypatch.setattr(keychain.keyring, 'get_password', lambda *args: calls.append(args))
    assert keychain.get_key('demo') == ''
    assert calls == [('bridge-coding-harness', 'demo')]


def test_windows_identity_matches_packager():
    root = Path(__file__).resolve().parents[2]
    package = json.loads((root / 'package.json').read_text())
    builder = json.loads((root / 'electron-builder.json').read_text())
    assert package['productName'] == builder['productName'] == 'Bridge Coding Harness'
    assert builder['appId'] == 'ir.bridge.codingharness'
    main = (root / 'electron/main.cjs').read_text(encoding='utf-8')
    assert builder['appId'] in main
    assert "'BridgeCodingHarness', 'desktop'" in main
