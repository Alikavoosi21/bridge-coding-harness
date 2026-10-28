import json
import httpx
import pytest
from server import settings
from server.app import create_app
from server.errors import ApiError
from server.model_catalog import discover_models


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr('server.model_catalog.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


async def test_catalog_uses_header_sorts_deduplicates_and_never_persists_key(tmp_path, monkeypatch):
    monkeypatch.setenv('HARNESS_HOME', str(tmp_path))
    def reply(request):
        assert str(request.url) == 'https://provider.example/v1/models'
        assert request.headers['authorization'] == 'Bearer secret-value'
        return httpx.Response(200, json={'data':[{'id':'z'},{'id':'a'},{'id':'a'},{'id':'secret-value'}]})
    transport(monkeypatch, reply)
    result = await discover_models('https://provider.example/v1', 'secret-value')
    assert [item['id'] for item in result['models']] == ['a','z']
    assert not list(tmp_path.iterdir())


async def test_anthropic_models_protocol(monkeypatch):
    def reply(request):
        assert str(request.url) == 'https://api.anthropic.com/v1/models'
        assert request.headers['x-api-key'] == 'key'
        assert 'authorization' not in request.headers
        return httpx.Response(200,json={'data':[{'id':'claude-test','display_name':'Claude Test'}],'has_more':True})
    transport(monkeypatch, reply)
    result=await discover_models('https://api.anthropic.com','key')
    assert result['partial'] and result['models'][0]['name']=='Claude Test'


@pytest.mark.parametrize('status,code',[(401,'provider_auth'),(403,'provider_auth'),(404,'model_catalog_unsupported'),(302,'provider_redirect'),(500,'provider_error')])
async def test_provider_errors_never_echo_body_or_key(monkeypatch,status,code):
    transport(monkeypatch,lambda request:httpx.Response(status,text='secret-value private response',headers={'Location':'https://other.example'}))
    with pytest.raises(ApiError) as caught:
        await discover_models('https://provider.example/v1','secret-value')
    assert caught.value.code==code
    assert 'secret-value' not in str(caught.value)


async def test_defer_survives_restart_without_marking_setup_complete(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path));monkeypatch.delenv('HARNESS_TOKEN',raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://localhost') as client:
        response=await client.post('/setup/defer')
        assert response.status_code==200
        assert response.json()['setup']['deferred']
        assert response.json()['setup']['completed'] is False
        assert response.json()['workspace']['open']
        assert (await client.get('/readiness')).json()['task']['can_write'] is True
        assert (await client.put('/settings',json={'setup':{'completed':True}})).status_code==200
    assert settings.load()['setup']['completed']
    assert settings.load()['setup']['acknowledgements']=={key:False for key in ('model_api','sandbox_network','demo_state','read_only')}


async def test_saved_key_cannot_be_discovered_on_different_endpoint(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path));monkeypatch.delenv('HARNESS_TOKEN',raising=False)
    settings.save({'models':[{'id':'saved','name':'test','base_url':'https://original.example/v1','model':'test'}],'default_model':'saved'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://localhost') as client:
        response=await client.post('/models/discover',json={'id':'saved','base_url':'https://different.example/v1'})
        assert response.status_code==422


def test_discovered_and_probed_default_is_callable_by_harness(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path))
    monkeypatch.setattr('server.settings.keychain.get_key',lambda _: 'fixture-key')
    settings.save({'models':[{'id':'chosen','name':'Chosen model','model':'coding-model-two','base_url':'https://provider.example/v1','capabilities':{'tools':True,'checked_at':123}}],'default_model':'chosen'})
    spec=settings.model_spec(None)
    assert spec.model=='coding-model-two' and spec.api_key=='fixture-key'
    assert spec.base_url=='https://provider.example/v1'
