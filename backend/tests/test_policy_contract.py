"""First T009 slice: policy boundaries and exact approval fingerprints."""
from dataclasses import replace

import pytest

from harness.permissions import FileRule, Policy
from harness.policy import ActionContext, action_access


def context(tool='execute', **changes):
    return replace(ActionContext(tool, {'command': 'python -m pytest'}, '/workspace', '/bin/sh', 'image:sha256:one', 'offline-v1', 3), **changes)


def decide(action=None, **changes):
    values = dict(mode='ask', read_only=False, plan_approved=True, runtime_available=True)
    values.update(changes)
    return action_access(Policy(mode='auto'), action or context(), **values)


@pytest.mark.parametrize('mode,grant,expected', [('ask',False,'ask'),('ask',True,'ask'),('grant',False,'ask'),('grant',True,'allow'),('auto',False,'allow')])
def test_permission_modes(mode, grant, expected):
    assert decide(mode=mode, grant_matches=grant) == expected


@pytest.mark.parametrize('boundary', ['read_only','plan_approved','runtime_available'])
def test_grant_or_auto_cannot_bypass_hard_boundary(boundary):
    for mode in ('ask','grant','auto'):
        assert decide(mode=mode, grant_matches=True, **{boundary: boundary == 'read_only'}) == 'deny'


@pytest.mark.parametrize('exception', ['network','installation','first_verifier','human_apply'])
def test_sensitive_consent_is_explicit_even_with_auto_or_grant(exception):
    assert decide(mode='auto', grant_matches=True, **{exception:True}) == 'ask'


def test_workspace_deny_survives_all_modes_and_grants():
    rules = Policy(mode='auto', tool_rules={'execute':'deny'})
    for mode in ('ask','grant','auto'):
        assert action_access(rules, context(), mode=mode, read_only=False, plan_approved=True, runtime_available=True, grant_matches=True) == 'deny'


def test_reads_unknown_tools_and_rules_file():
    assert decide(context('read_file'), read_only=True, runtime_available=False) == 'allow'
    assert decide(context('external_connector'), mode='auto') == 'ask'
    assert decide(context('write_file', args={'file_path':'/.harness/rules.yaml'}),mode='auto') == 'ask'


def test_fingerprint_binds_every_material_input_without_becoming_identity():
    original=context(script=b'print(1)\n')
    assert original.fingerprint() == replace(original, args=dict(reversed(list(original.args.items())))).fingerprint()
    for changes in ({'tool':'edit_file'},{'args':{'command':'python -m pytest -x'}},{'cwd':'/other'}, {'shell':'bash'}, {'runtime':'image:two'}, {'environment_profile':'network-v1'}, {'plan_revision':4}, {'script':b'print(1)\r\n'}):
        assert replace(original, **changes).fingerprint() != original.fingerprint()
    with pytest.raises(ValueError):
        context(args={'timeout':float('nan')}).fingerprint()
