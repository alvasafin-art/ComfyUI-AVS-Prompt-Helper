import io
import json
from pathlib import Path
import pytest
from backend import codex_catalog, cli_catalog
from backend.extra_cli import prepare
from backend.request import build


def test_catalogs_keep_provider_ids_and_distinguish_unknown_efforts():
    assert codex_catalog.normalize_models([{'id':'display-id','model':'real-id','displayName':'Visible',
        'supportedReasoningEfforts':[{'reasoningEffort':'ultra'}],'defaultReasoningEffort':'ultra'}])[0] == {
        'id':'real-id','name':'Visible','reasoning':['ultra'],'default_reasoning':'ultra','is_default':False}
    rows = cli_catalog.claude_models([
        {'value':'opus','displayName':'Claude Opus','supportedEffortLevels':['low','max']},
        {'value':'old'}, {'value':'haiku','supportsEffort':False}])
    assert rows[0]['id']=='opus' and rows[0]['reasoning']==['low','max']
    assert rows[1]['reasoning'] is None and rows[2]['reasoning']==[]


def test_kimi_aliases_thinking_and_secrets():
    config={'default_model':'toggle','providers':{'p':{'api_key':'secret'}},'models':{
        'toggle':{'provider':'p','model':'kimi-code','display_name':'Kimi'},
        'always':{'provider':'p','model':'example-reasoner'},
        'plain':{'provider':'p','model':'plain'},
        'invalid':{'provider':'missing','model':'plain'}}}
    rows=cli_catalog.kimi_models(config)
    assert [r['id'] for r in rows]==['toggle','always','plain']
    assert [r['reasoning'] for r in rows]==[['thinking','no_thinking'],['thinking'],[]]
    assert rows[0]['is_default'] and 'secret' not in json.dumps(rows)


@pytest.mark.parametrize('mode,flag',[('thinking','--thinking'),('no_thinking','--no-thinking')])
def test_kimi_thinking_flags(tmp_path, monkeypatch, mode, flag):
    source=tmp_path/'source.json'
    source.write_text(json.dumps({'providers':{'p':{}},'models':{'alias':{'provider':'p','model':'kimi-code'}}}))
    monkeypatch.setenv('AVS_KIMI_CONFIG',str(source))
    r=build({'document':['text'],'settings':{'adapter':'kimi','model':'alias','reasoning':mode}})
    args,_=prepare(r,tmp_path,['kimi'])
    assert flag in args


def test_kimi_cannot_disable_always_thinking(tmp_path, monkeypatch):
    source=tmp_path/'source.json'
    source.write_text(json.dumps({'providers':{'p':{}},'models':{'alias':{'provider':'p','model':'reasoner'}}}))
    monkeypatch.setenv('AVS_KIMI_CONFIG',str(source))
    r=build({'document':['text'],'settings':{'adapter':'kimi','model':'alias','reasoning':'no_thinking'}})
    with pytest.raises(ValueError,match='does not support'):
        prepare(r,tmp_path,['kimi'])


def test_cli_error_redaction(monkeypatch):
    monkeypatch.setenv('EXAMPLE_API_KEY','plain-secret-123')
    result=codex_catalog.failure_detail(json.dumps({'type':'turn.failed','error':{'message':
        'Unsupported model; prompt contents; Bearer abc123; sk-secret111 plain-secret-123'}}).encode(),b'',('prompt contents',))
    assert 'Unsupported model' in result
    assert all(s not in result for s in ('prompt contents','abc123','sk-secret111','plain-secret-123'))


def fake_process(monkeypatch, module, events):
    observed={}
    class Input(io.BytesIO):
        def close(self):
            observed['sent']=[json.loads(line) for line in self.getvalue().splitlines()]
            super().close()
    class Process:
        returncode=None
        def __init__(self,args,**kwargs):
            observed.update(args=args,**kwargs)
            self.stdin=Input();self.stdout=io.BytesIO(b'\n'.join(json.dumps(e).encode() for e in events))
        def poll(self): return self.returncode
        def kill(self): self.returncode=-1;observed['killed']=True
        def wait(self,timeout): return self.returncode
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    return observed


def test_codex_handshake_account_pagination_cleanup(monkeypatch):
    observed=fake_process(monkeypatch,codex_catalog,[
        {'id':1,'result':{}}, {'id':2,'result':{'account':{'type':'chatgpt'}}},
        {'id':3,'result':{'data':[{'model':'one'}],'nextCursor':'next'}},
        {'id':4,'result':{'data':[{'model':'two'}],'nextCursor':None}}])
    result=codex_catalog.discover('codex')
    assert [m['id'] for m in result['models']]==['one','two']
    assert [m['method'] for m in observed['sent']]==['initialize','initialized','account/read','model/list','model/list']
    assert observed['sent'][-1]['params']['cursor']=='next'
    assert observed['shell'] is False and observed['killed'] and not Path(observed['cwd']).exists()


def test_codex_not_logged_in(monkeypatch):
    observed=fake_process(monkeypatch,codex_catalog,[{'id':1,'result':{}},{'id':2,'result':{'account':None}}])
    with pytest.raises(ValueError,match='not logged in'):
        codex_catalog.discover('codex')
    assert observed['killed'] and all(m['method']!='model/list' for m in observed['sent'])


def test_claude_handshake_without_user_turn(monkeypatch):
    observed=fake_process(monkeypatch,cli_catalog,[{'type':'control_response','response':{
        'request_id':'avs-models','subtype':'success','response':{'models':[{
            'value':'opus','displayName':'Opus','supportedEffortLevels':['high','max']}],'account':{'apiKey':'secret'}}}}])
    result=cli_catalog.discover_claude(['claude'])
    assert result['models'][0]['reasoning']==['high','max'] and 'secret' not in json.dumps(result)
    assert len(observed['sent'])==1 and observed['sent'][0]['request']['subtype']=='initialize'
    assert '--strict-mcp-config' in observed['args'] and observed['killed']
    assert not Path(observed['cwd']).exists()


def test_claude_discovery_failure_cleanup(monkeypatch):
    observed=fake_process(monkeypatch,cli_catalog,[{'type':'control_response','response':{
        'request_id':'avs-models','subtype':'error','error':'unsupported initialization'}}])
    with pytest.raises(ValueError,match='unsupported initialization'):
        cli_catalog.discover_claude(['claude'])
    assert observed['killed'] and not Path(observed['cwd']).exists()
