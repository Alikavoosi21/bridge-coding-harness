from pathlib import Path
import httpx
import pytest
from harness.skills_registry import scan_skill_sources,parse_skill_text
from server.app import create_app
from server.storage import Store


def make_skill(root,name='review-code'):
    root.mkdir(parents=True)
    text=f'---\nname: {name}\ndescription: Read only explicitly requested code.\n---\n\nIMPORTED_SKILL_BODY.\n'
    (root/'SKILL.md').write_text(text,encoding='utf8')
    (root/'helper.txt').write_text('Resource, not an instruction to execute.',encoding='utf8')
    return text


def test_nested_collection_detects_skills_not_parent_or_resources(tmp_path):
    make_skill(tmp_path/'skills'/'engineering'/'review')
    make_skill(tmp_path/'skills'/'productivity'/'questions','ask-questions')
    make_skill(tmp_path/'node_modules'/'hidden','not-a-user-skill')
    result=scan_skill_sources(tmp_path)
    assert {row['name'] for row in result['items']}=={'review-code','ask-questions'}
    assert all(row['valid'] for row in result['items'])
    assert not result['truncated']


def test_individual_skill_scan_and_file_parser_preserve_body(tmp_path):
    text=make_skill(tmp_path/'one')
    assert len(scan_skill_sources(tmp_path/'one')['items'])==1
    parsed=parse_skill_text('\ufeff'+text)
    assert parsed['name']=='review-code' and parsed['body']=='IMPORTED_SKILL_BODY.'
    with pytest.raises(ValueError):parse_skill_text('not a SKILL.md')


async def test_scan_and_parse_are_readonly_and_do_not_enable_anything(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'));monkeypatch.delenv('HARNESS_TOKEN',raising=False)
    text=make_skill(tmp_path/'collection'/'engineering'/'review')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://localhost') as api:
        result=await api.post('/skill-sources/scan',json={'source':str(tmp_path/'collection')})
        assert result.status_code==200 and result.json()['items'][0]['name']=='review-code'
        parsed=await api.post('/skills/parse',json={'content':text})
        assert parsed.status_code==200 and parsed.json()['body']=='IMPORTED_SKILL_BODY.'
        assert (await api.get('/skill-sources')).json()['items']==[]
        assert (await api.post('/skills/parse',json={'content':'broken file'})).status_code==422
        source=(await api.post('/skill-sources',json={'source':result.json()['items'][0]['source'],'scope':'personal'})).json()
        detail=(await api.get('/skill-sources/'+source['id'])).json()
        assert not detail['enabled'] and detail['body']=='IMPORTED_SKILL_BODY.'
        enabled=await api.post('/skill-sources/'+source['id']+'/enable',json={'expected_hash':detail['current_hash'],'confirm':True})
        assert enabled.status_code==200 and enabled.json()['enabled']
        assert 'helper.txt' in enabled.json()['files']
