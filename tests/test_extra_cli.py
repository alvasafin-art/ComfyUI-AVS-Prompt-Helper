import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from backend.extra_cli import prepare, parse_output, generate
from backend.request import build, DEFAULTS
from backend.images import ImageItem


def request(provider):
    r = build({'document':['literal $(do-not-run)'], 'system_prompt':'System rules', 'settings':{**DEFAULTS,'adapter':provider,'model':'model'}})
    r.images = [ImageItem('a','image_1',b'png',2,2),ImageItem('b','image_2',b'png2',3,3)]
    return r


def test_claude_input_and_isolation(tmp_path):
    args, stdin = prepare(request('claude'),tmp_path,['claude.exe'])
    assert args[args.index('--tools')+1] == '' and '--bare' in args and '--strict-mcp-config' in args
    assert '--dangerously-skip-permissions' not in args
    assert 'literal $(do-not-run)' not in args
    message=json.loads(stdin)['message']
    assert len([p for p in message['content'] if p['type']=='image'])==2
    assert (tmp_path/'system.txt').read_text()=='System rules'


def test_kimi_input_and_isolation(tmp_path,monkeypatch):
    source=tmp_path/'source.json'
    source.write_text(json.dumps({'models':{'model':{}},'providers':{'provider':{'api_key':'secret'}},'hooks':{'bad':'command'},'plugins':['bad']}))
    monkeypatch.setenv('AVS_KIMI_CONFIG',str(source))
    args, stdin = prepare(request('kimi'),tmp_path,['kimi.exe'])
    config=json.loads((tmp_path/'config.json').read_text())
    agent=json.loads((tmp_path/'agent.yaml').read_text())
    assert 'hooks' not in config and 'plugins' not in config
    assert agent['agent']['tools']==[] and agent['agent']['subagents']=={}
    assert '--mcp-config-file' in args and '--skills-dir' in args
    assert 'secret' not in args and b'secret' not in stdin
    assert len([p for p in json.loads(stdin)['content'] if p['type']=='image_url'])==2


@pytest.mark.parametrize('provider,data,expected',[
    ('claude',{'type':'result','subtype':'success','result':'final','usage':{'input_tokens':7}},'final'),
    ('kimi',{'role':'assistant','content':[{'type':'think','think':'private'},{'type':'text','text':'final'}]},'final')])
def test_parse_final_only(provider,data,expected):
    assert parse_output(provider,json.dumps(data).encode())['text']==expected


@pytest.mark.parametrize('provider,data',[
    ('claude',{'type':'result','subtype':'error_max_turns','result':'partial'}),
    ('kimi',{'role':'assistant','content':'','tool_calls':[{}]})])
def test_failed_results(provider,data):
    with pytest.raises(ValueError):parse_output(provider,json.dumps(data).encode())


@pytest.mark.asyncio
@pytest.mark.parametrize('provider',['claude','kimi'])
async def test_process_roundtrip(provider, tmp_path, monkeypatch):
    from backend import extra_cli
    monkeypatch.setattr(extra_cli,'capabilities',lambda p:[p+'.exe'])
    source=tmp_path/'config-source.json';source.write_text('{"models":{},"providers":{}}')
    monkeypatch.setenv('AVS_KIMI_CONFIG',str(source))
    observed={}
    class Process:
        returncode=0
        def __init__(self,args,**kwargs):observed.update(args=args,**kwargs)
        def communicate(self,stdin):
            observed['input']=json.loads(stdin)
            response={'type':'result','subtype':'success','result':'final'} if provider=='claude' else {'role':'assistant','content':'final'}
            return json.dumps(response).encode(),b''
    monkeypatch.setattr(extra_cli.subprocess,'Popen',Process)
    result=await generate(request(provider))
    assert result['text']=='final' and observed['shell'] is False
    assert not Path(observed['cwd']).exists()
