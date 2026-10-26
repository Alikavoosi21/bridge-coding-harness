"""Acceptance must never turn a demo run into claimed real-provider proof."""
import json

from harness import ModelSpec
import real_provider_acceptance as acceptance


async def test_demo_stops_before_creating_a_fixture_or_calling_provider(tmp_path, monkeypatch):
    report = tmp_path / 'evidence' / 'real-provider.json'
    monkeypatch.setattr(acceptance, 'OUTPUT', report)
    monkeypatch.setattr(acceptance.settings, 'model_spec', lambda _: ModelSpec('demo', 'demo', 'demo://', 'demo'))

    async def forbidden_probe(*args, **kwargs):
        raise AssertionError('A demo must not reach the provider test.')

    monkeypatch.setattr(acceptance, 'probe_model', forbidden_probe)
    assert await acceptance.main() == 3
    result = json.loads(report.read_text(encoding='utf-8'))
    assert result['passed'] is False
    assert result['checks'] == []
    assert result['blocked']
