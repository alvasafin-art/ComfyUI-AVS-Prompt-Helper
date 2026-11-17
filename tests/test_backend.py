import asyncio
import copy
import io
import json
import numpy as np
import pytest
from PIL import Image
from backend.images import encode, decode, tensor_image, collect
from backend.request import build, parse_state, DEFAULTS
from backend.storage import asset_path, presets, atomic_json
from backend.cache import execute
from backend.adapters import payload, api_generate, cli_generate, cli_capabilities


def state(**extra):
    return {"version": 1, "document": ["Describe"], "system_prompt": "Only the prompt", "settings": {**DEFAULTS, "model": "test-model"}, **extra}


@pytest.mark.parametrize('size', [(4000, 2000), (2000, 4000), (2000, 2000), (1, 3000), (300, 400)])
def test_resize(size):
    im = Image.new('RGBA', size, (30, 40, 50, 80))
    data, w, h = encode(im, 'max_mp', 1)
    assert w * h <= 1_000_000 and w <= size[0] and h <= size[1]
    assert abs(w / h - size[0] / size[1]) < .01
    assert Image.open(io.BytesIO(data)).mode == 'RGBA'
    assert encode(im)[1:] == size


def test_orientation_and_decode_limits():
    im = Image.new('RGB', (80, 40)); exif = im.getexif(); exif[274] = 6
    out = io.BytesIO(); im.save(out, format='JPEG', exif=exif)
    assert decode(out.getvalue()).size == (40, 80)
    with pytest.raises(ValueError): decode(b'x' * (25 * 1024 * 1024 + 1))
    with pytest.raises(ValueError): encode(im, 'max_mp', float('nan'))


def test_tensor_validation():
    assert tensor_image(np.zeros((1, 8, 10, 3))).size == (10, 8)
    with pytest.raises(ValueError, match='single image'): tensor_image(np.zeros((2, 8, 8, 3)))
    with pytest.raises(ValueError, match='NaN'): tensor_image(np.full((1, 8, 8, 3), np.nan))
    assert np.asarray(tensor_image(np.full((1, 8, 8, 3), 2))).max() == 255


def test_order_and_mentions():
    handle = 'a' * 64; path = asset_path(handle); path.parent.mkdir(); path.write_bytes(encode(Image.new('RGB', (10, 10)))[0])
    s = state(uploads=[handle], document=[{'image_id':'upload:'+handle}, ' then ', {'image_id':'socket:image_3'}])
    r = build(s, image_3=np.zeros((1, 8, 8, 3)), image_1=np.ones((1, 8, 8, 3)))
    assert [i.stable_id for i in r.images] == ['socket:image_1','socket:image_3','upload:'+handle]
    assert r.user == '@image_3 then @image_2'
    assert build(s, image_3=np.zeros((1, 8, 8, 3))).user == '@image_2 then @image_1'
    with pytest.raises(ValueError, match='Dangling'): build(s)
    path.unlink()
    with pytest.raises(ValueError, match='Missing attachment'): build(s)


@pytest.mark.parametrize('mode,expected',[('append','Describe\n\nexternal'),('prepend','external\n\nDescribe'),('replace','external')])
def test_merge(mode,expected):
    s=state();s['settings']['merge_mode']=mode
    assert build(s,'external').user==expected


def test_presets_snapshot_isolation_and_corruption():
    p=presets('one','save',{'name':'A','system_prompt':'old','model':'secret','api_key':'secret'})['presets'][0]
    assert set(p)=={'id','name','system_prompt'}
    s=state(system_prompt=p['system_prompt'],preset_id=p['id'])
    presets('one','save',{**p,'system_prompt':'new'})
    assert build(s).system=='old' and presets('two')['presets']==[]
    assert parse_state(json.dumps(s))==s
    presets('one','delete',p)
    assert presets('one')['presets']==[]


def test_fingerprints():
    original=state(); r=build(original); key=r.fingerprint()
    for field,value in [('model','other'),('reasoning','high'),('max_mp',2),('image_mode','max_mp'),('max_output_tokens',300)]:
        s=copy.deepcopy(original);s['settings'][field]=value
        assert build(s).fingerprint()!=key
    assert build(state(system_prompt='changed')).fingerprint()!=key
    assert build(state(document=['other'])).fingerprint()!=key
    assert build(state(),image_1=np.zeros((1,8,8,3))).fingerprint()!=build(state(),image_1=np.ones((1,8,8,3))).fingerprint()
    a=np.zeros((1,8,8,3));b=np.ones((1,8,8,3))
    assert build(state(),image_1=a,image_2=b).fingerprint()!=build(state(),image_1=b,image_2=a).fingerprint()


@pytest.mark.asyncio
async def test_cache_singleflight_regeneration_restart_and_failure():
    calls=[]
    async def producer(r):
        calls.append(1);await asyncio.sleep(.02);return {'text':str(len(calls)),'usage':{}}
    r=build(state())
    results=await asyncio.gather(*(execute(r,'',producer) for _ in range(5)))
    assert len(calls)==1 and all(x['text']=='1' for x in results)
    results=await asyncio.gather(*(execute(r,'nonce-1',producer) for _ in range(3)))
    assert len(calls)==2 and all(x['text']=='2' for x in results)
    assert (await execute(r,'',producer))['text']=='2'
    assert (await execute(r,'nonce-1',producer))['cached']
    async def fail(r):raise ValueError('failed')
    with pytest.raises(ValueError):await execute(r,'nonce-2',fail)
    assert (await execute(r,'',producer))['text']=='2'
    from backend.cache import LOCKS
    LOCKS.clear()
    assert (await execute(r,'nonce-1',producer))['text']=='2' and len(calls)==2


def test_payloads_and_limits():
    s=state();s['settings']['reasoning']='high'
    r=build(s,image_2=np.zeros((1,5,5,3)),image_4=np.ones((1,5,5,3)))
    p=payload(r,'responses');assert p['instructions']=='Only the prompt' and p['reasoning']=={'effort':'high'}
    assert [c['text'] for c in p['input'][0]['content'] if c['type']=='input_text']==['Describe','Image @image_1:','Image @image_2:']
    assert payload(r,'chat')['messages'][0]['role']=='system'
    s['settings']['max_images']=1
    with pytest.raises(ValueError,match='limit'):build(s,image_1=np.zeros((1,5,5,3)),image_2=np.zeros((1,5,5,3)))


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['chat','responses','auto'])
async def test_real_http_transport(mode):
    from aiohttp import web
    calls=[]
    async def respond(request):
        body=await request.json();calls.append((request.path,body))
        if request.path.endswith('/responses'):
            if mode=='auto':return web.Response(status=404)
            return web.json_response({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'final'}]}],'usage':{'input_tokens':12}})
        return web.json_response({'choices':[{'message':{'content':'final'},'finish_reason':'stop'}],'usage':{'prompt_tokens':12}})
    app=web.Application();app.router.add_post('/v1/{tail:.*}',respond)
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    port=site._server.sockets[0].getsockname()[1]
    s=state();s['settings'].update(adapter='compatible',api_mode=mode,base_url=f'http://127.0.0.1:{port}/v1')
    try:
        result=await api_generate(build(s,image_1=np.zeros((1,5,5,3))))
        assert result['text']=='final' and result['usage']['input_tokens']==12
        assert len(calls)==(2 if mode=='auto' else 1)
    finally:await runner.cleanup()


@pytest.mark.asyncio
async def test_no_retry_on_chargeable_error():
    from aiohttp import web
    calls=[]
    async def fail(request):calls.append(1);return web.Response(status=500)
    app=web.Application();app.router.add_post('/responses',fail)
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    s=state();s['settings'].update(adapter='compatible',api_mode='auto',base_url=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}')
    try:
        with pytest.raises(ValueError,match='HTTP 500'):await api_generate(build(s))
        assert len(calls)==1
    finally:await runner.cleanup()


def test_path_traversal():
    for path in ['../../secret','C:\\secret','a'*63,'z'*64]:
        with pytest.raises(ValueError):asset_path(path)
