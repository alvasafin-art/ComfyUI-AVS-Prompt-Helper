import json
from pathlib import Path
import subprocess
import pytest
from backend import adapters
from backend.request import build, DEFAULTS


@pytest.mark.asyncio
async def test_cli_argument_safety_final_output_and_usage(monkeypatch):
    monkeypatch.setattr(adapters, 'cli_capabilities', lambda: 'C:/Program Files/Codex/codex.exe')
    captured = {}
    class Process:
        returncode = 0
        def __init__(self, args, **kwargs):
            captured.update(args=args, kwargs=kwargs)
            Path(args[args.index('--output-last-message') + 1]).write_text('final prompt', encoding='utf-8')
        def communicate(self, data):
            captured['stdin'] = data.decode()
            return json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':4}}).encode(), b''
        def kill(self):
            captured['killed'] = True
    monkeypatch.setattr(subprocess, 'Popen', Process)
    r = build({'document':['user $(unsafe)'], 'system_prompt':'separate system', 'settings':{**DEFAULTS,'adapter':'codex','model':'test','reasoning':'high'}})
    result = await adapters.cli_generate(r)
    assert result['text'] == 'final prompt' and result['usage']['input_tokens'] == 10
    assert captured['kwargs']['shell'] is False
    assert 'user $(unsafe)' not in captured['args']
    assert 'user $(unsafe)' in captured['stdin'] and 'SYSTEM INSTRUCTIONS:' in captured['stdin']
    assert captured['args'][captured['args'].index('--sandbox')+1] == 'read-only'
    assert '--ignore-user-config' in captured['args']
    assert not Path(captured['kwargs']['cwd']).exists()


def test_cli_missing_protective_flags_rejected(monkeypatch):
    monkeypatch.setattr(adapters, 'cli_executable', lambda: 'codex')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 0, '--sandbox --image', ''))
    with pytest.raises(ValueError, match='isolation flags'):
        adapters.cli_capabilities()
