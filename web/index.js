import { app } from '../../scripts/app.js';
import { api } from '../../scripts/api.js';
import { makeEditor, color } from './editor.js';
import { defaults, settingsPanel } from './settings.js';
import { showNodeDialog } from './dialog.js';

const style = document.createElement('link'); style.rel = 'stylesheet'; style.href = new URL('./styles.css', import.meta.url).href; document.head.append(style);
const TYPE = 'AVSPromptHelper';
async function request(path, body) {
    const response = await api.fetchApi('/avs-prompt' + path, body === undefined ? {} : body instanceof FormData ? {method:'POST',body} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if (!response.ok) { let error; try { error = (await response.json()).error; } catch {} throw new Error(error || `AVS request failed (${response.status})`); }
    return response.json();
}
function element(tag, cls, text) { const el = document.createElement(tag); el.className = cls || ''; if (text) el.textContent = text; return el; }
function button(text, action, title) { const el = element('button','',text); el.type='button'; el.title=title || text; el.ariaLabel=title || text; el.onclick=action; return el; }

function connectionIcon() {
    const ns='http://www.w3.org/2000/svg';
    const svg=document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 40 16');svg.setAttribute('aria-hidden','true');
    const line=document.createElementNS(ns,'path');
    line.setAttribute('d','M8 8H32');line.setAttribute('stroke','currentColor');line.setAttribute('stroke-width','3');
    svg.append(line);
    for(const x of [7,33]){
        const circle=document.createElementNS(ns,'circle');
        circle.setAttribute('cx',x);circle.setAttribute('cy','8');circle.setAttribute('r','5.5');circle.setAttribute('fill','currentColor');svg.append(circle);
    }
    return svg;
}

export function syncSockets(node) {
    const sockets = node.inputs?.filter(i => /^image_\d+$/.test(i.name)) || [];
    let last = -1; sockets.forEach((i, index) => { if (i.link != null) last = index; });
    const count = Math.min(20, Math.max(1, last + 2));
    for (let i = sockets.length - 1; i >= count; i--) node.removeInput(node.inputs.indexOf(sockets[i]));
    for (let i = sockets.length; i < count; i++) node.addInput(`image_${i+1}`, 'IMAGE');
}

function install(node) {
    node.color='#181818'; node.bgcolor='#181818';
    const original = node.widgets?.find(w => w.name === 'state');
    let state = {version:1,document:[],system_prompt:'',uploads:[],settings:{...defaults},regeneration:''};
    let library = [], removed = false, busy = false, popup, syncing = false;
    const root = element('div','avs-root');
    root.addEventListener('keydown', e => e.stopPropagation());
    root.addEventListener('pointerdown', e => e.stopPropagation());
    root.addEventListener('wheel', e => {
        const scroller=e.target.closest('.avs-editor,.avs-images,.avs-mentions');
        const editing=scroller && (scroller.contains(document.activeElement) || scroller.classList.contains('avs-mentions'));
        const canScroll=scroller && (e.deltaY<0 ? scroller.scrollTop>0 : scroller.scrollTop+scroller.clientHeight<scroller.scrollHeight-1);
        e.stopPropagation();
        if(editing && canScroll && !e.ctrlKey && !e.metaKey)return;
        e.preventDefault();
        app.canvas.canvas.dispatchEvent(new WheelEvent('wheel',{
            bubbles:true,cancelable:true,clientX:e.clientX,clientY:e.clientY,
            deltaX:e.deltaX,deltaY:e.deltaY,deltaZ:e.deltaZ,deltaMode:e.deltaMode,
            ctrlKey:e.ctrlKey,metaKey:e.metaKey,shiftKey:e.shiftKey,altKey:e.altKey
        }));
    }, {passive:false});
    const header = element('div','avs-top');
    header.append(button('⚙', () => { popup?.close(); popup = settingsPanel(state.settings, request, settings => { state.settings=settings; persist(); },root); }, 'Settings'));
    const prompt = element('section','avs-prompt');
    const editorHost = element('div','avs-editor-host'); prompt.append(editorHost);
    const system = element('section','avs-system');
    const select = element('select'); select.ariaLabel='System prompt preset';
    const actions = element('div','avs-preset-actions');
    const imageSection = element('section','avs-images'); imageSection.ariaLabel='Images';
    const grid = element('div','avs-image-grid'); imageSection.append(grid);
    const footer = element('footer','avs-footer'), status = element('span','avs-status','Idle · Usage N/A'); status.role='status'; status.ariaLive='polite';
    const regen = button('Regenerate', async () => {
        if (busy) return;
        const previous = state.regeneration;
        state.regeneration = crypto.randomUUID(); persist(); setBusy(true); status.textContent='Queued…';
        try { const queued = await app.queuePrompt(0,1); if (queued === false) throw new Error('Graph could not be queued; check connected output nodes'); }
        catch (e) { state.regeneration=previous; persist(); fail(e); }
    }); regen.className='avs-primary';
    footer.append(status,regen); root.append(header,prompt,system,imageSection,footer);
    const items = () => [...(node.inputs || []).filter(i => /^image_\d+$/.test(i.name) && i.link != null).map(i => ({id:'socket:'+i.name,source:`Graph · ${i.name}`})),
        ...(state.uploads || []).map(id => ({id:'upload:'+id,handle:id,source:'Upload'}))].map((i,index) => ({...i,label:`image_${index+1}`}));
    const editor = makeEditor(editorHost,items,document => { state.document=document; persist(); });
    function persist() { if (original) original.value=JSON.stringify(state); node.setDirtyCanvas(true,true); updateDirty(); }
    function updateDirty() { const preset=library.find(p=>p.id===state.preset_id); select.title=preset && preset.system_prompt!==state.system_prompt ? 'Workflow snapshot differs from saved preset' : 'System prompt preset'; }
    function setBusy(value) { busy=value; regen.disabled=value; }
    function fail(error) { status.textContent=error.message; status.classList.add('avs-error'); setBusy(false); }
    async function guarded(action) { try { await action(); } catch (e) { fail(e); } }
    function drawPresets() {
        select.replaceChildren(new Option(state.system_prompt ? 'Custom prompt' : 'Select a system prompt',''));
        library.forEach(p=>select.add(new Option(p.name,p.id)));
        if (state.preset_id && !library.some(p=>p.id===state.preset_id)) select.add(new Option('Unavailable preset · snapshot retained',state.preset_id));
        select.value=state.preset_id || ''; updateDirty();
    }
    async function mutate(operation, data) { library=(await request('/presets',{operation,...data})).presets; drawPresets(); }
    select.onchange=()=>{ state.preset_id=select.value; const p=library.find(p=>p.id===select.value); if(p) state.system_prompt=p.system_prompt; persist(); };
    function editPreset(create) {
        popup?.close();
        const dialog=element('dialog','avs-settings avs-preset-dialog');dialog.ariaLabel=create?'New system prompt':'Edit system prompt';
        const form=element('form');
        const nameLabel=element('label','','Name'), name=element('input');name.ariaLabel='Preset name';name.required=true;name.maxLength=120;
        const promptLabel=element('label','','Prompt'), text=element('textarea','avs-preset-text');text.ariaLabel='System instruction';
        const existing=library.find(p=>p.id===state.preset_id);
        name.value=create?'':existing?.name||'Custom prompt';text.value=create?'':state.system_prompt;
        nameLabel.append(name);promptLabel.append(text);
        const error=element('p','avs-error');error.role='alert';
        const controls=element('div','avs-dialog-actions');
        const save=button('Save',null);save.type='submit';save.className='avs-primary';
        controls.append(button('Cancel',()=>dialog.close()),save);
        form.append(nameLabel,promptLabel,error,controls);
        form.onsubmit=async e=>{
            e.preventDefault();save.disabled=true;
            try{
                const id=create?crypto.randomUUID():(state.preset_id||crypto.randomUUID());
                await mutate('save',{id,name:name.value,system_prompt:text.value});
                if(!removed){state.preset_id=id;state.system_prompt=text.value;drawPresets();persist();}
                dialog.close();
            }catch(e){error.textContent=e.message;save.disabled=false;}
        };
        dialog.append(form);popup=showNodeDialog(dialog,root);name.focus();
    }
    actions.append(select,
        button('+',()=>editPreset(true),'New system prompt'),
        button('⋯',()=>{
            popup?.close(); popup=document.createElement('dialog');popup.className='avs-settings avs-library';popup.ariaLabel='System prompt library';
            const operation=(label,fn)=>button(label,()=>guarded(fn));
            popup.append(element('h2','','System prompt library'),
                operation('Edit prompt',async()=>editPreset(false)),
                operation('Duplicate',async()=>{const p=library.find(p=>p.id===state.preset_id);const id=crypto.randomUUID();await mutate('save',{id,name:(p?.name||'Custom')+' copy',system_prompt:state.system_prompt});state.preset_id=id;drawPresets();persist();}),
                operation('Export JSON',async()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({version:1,presets:library},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='avs-system-presets.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}),
                operation('Import JSON',async()=>{const input=document.createElement('input');input.type='file';input.accept='.json';input.onchange=()=>guarded(async()=>{const file=input.files[0];if(file.size>1e6)throw new Error('Preset file exceeds 1 MB');const data=JSON.parse(await file.text());if(data.version!==1||!Array.isArray(data.presets))throw new Error('Invalid preset library');for(const p of data.presets)await mutate('save',{id:crypto.randomUUID(),name:p.name,system_prompt:p.system_prompt});});input.click();}),
                );
            const editGroup=element('div','avs-library-group');
            const transferGroup=element('div','avs-library-group');
            const buttons=[...popup.querySelectorAll('button')];
            editGroup.append(...buttons.slice(0,2));transferGroup.append(...buttons.slice(2));
            const deletion=element('div','avs-library-delete');
            const remove=operation('Delete preset',async()=>{if(!state.preset_id || !window.confirm('Delete this shared preset? Workflow text will be retained.'))return;await mutate('delete',{id:state.preset_id});state.preset_id='';drawPresets();persist();popup.close();});
            remove.disabled=!state.preset_id;deletion.append(remove);
            popup.append(editGroup,transferGroup,deletion);
            showNodeDialog(popup,root);
        },'Rename, duplicate, delete, import or export presets'));
    system.append(actions);
    const picker=element('input');picker.type='file';picker.accept='image/png,image/jpeg,image/webp';picker.multiple=true;picker.hidden=true;root.append(picker);
    async function upload(files) {
        for(const file of files){const data=new FormData();data.append('image',file);const result=await request('/upload',data);if(removed)return;state.uploads.push(result.id);persist();drawImages();}
    }
    picker.onchange=()=>guarded(async()=>{await upload(picker.files);picker.value='';});
    imageSection.ondragover=e=>{e.preventDefault();e.stopPropagation();};
    imageSection.ondrop=e=>{e.preventDefault();e.stopPropagation();guarded(()=>upload(e.dataTransfer.files));};
    function drawImages(){
        grid.replaceChildren();
        items().forEach(item=>{
            const card=element('div','avs-image-card');card.style.setProperty('--image-color',color(item.id));
            if(item.handle){
                const img=element('img');img.src=api.apiURL('/avs-prompt/assets/'+item.handle);img.alt=item.label;img.onerror=()=>{img.replaceWith(element('span','avs-missing','Missing asset'));};
                card.append(img);const controls=element('div','avs-image-controls');
                controls.append(button('×',()=>{state.uploads=state.uploads.filter(id=>id!==item.handle);persist();drawImages();},'Remove image'),
                    button('←',()=>{const i=state.uploads.indexOf(item.handle);if(i>0){[state.uploads[i-1],state.uploads[i]]=[state.uploads[i],state.uploads[i-1]];persist();drawImages();}},'Move upload earlier'));
                card.append(controls);
            }else { const link=element('span','avs-graph-image');link.title='Connected graph image';link.ariaLabel='Connected graph image';link.append(connectionIcon());card.append(link); }
            card.append(element('b','',item.label.replace('image_','Image_')));grid.append(card);
        });
        const add=button('+',()=>picker.click(),'Add image');add.className='avs-add-image';grid.append(add);editor.relabel();
    }
    if(original){original.type='hidden';original.computeSize=()=>[0,-4];original.computeLayoutSize=()=>({minHeight:0,maxHeight:0,minWidth:0});}
    const widget=node.addDOMWidget('avs_ui','avs-ui',root,{serialize:false,hideOnZoom:false,getMinHeight:()=>420,getHeight:()=>Math.max(420,node.size[1]-(node.inputs?.length||0)*20-56)});
    widget.serialize=false;
    function restore(){
        node.color='#181818'; node.bgcolor='#181818';
        try{const saved=JSON.parse(original?.value||'{}');state={...state,...saved,settings:{...defaults,...saved.settings}};if(state.version!==1)throw new Error('Unsupported workflow version');editor.set(state.document||[state.prompt||'']);drawPresets();drawImages();}catch(e){fail(e);}
    }
    const configure=node.onConfigure;
    node.onConfigure=function(...args){const result=configure?.apply(this,args);restore();queueMicrotask(()=>{if(!removed)syncSockets(node);});return result;};
    const connections=node.onConnectionsChange;
    node.onConnectionsChange=function(...args){const result=connections?.apply(this,args);if(!syncing){syncing=true;queueMicrotask(()=>{if(!removed){syncSockets(node);drawImages();}syncing=false;});}return result;};
    const resize=node.onResize;
    node.onResize=function(size){size[0]=Math.max(350,size[0]);size[1]=Math.max(500+(node.inputs?.length||0)*20,size[1]);return resize?.call(this,size);};
    const executed=node.onExecuted;
    node.onExecuted=function(message){executed?.call(this,message);const s=message.avs_status?.[0];if(s){const u=s.usage||{};status.classList.remove('avs-error');status.textContent=`${s.cached?'Cached':'Generated'} · ${s.duration??'—'}s · In ${u.input_tokens??'N/A'} / Out ${u.output_tokens??'N/A'} / Total ${u.total_tokens??'N/A'}`;}setBusy(false);};
    const abort=new AbortController();
    api.addEventListener('executing',e=>{if(String(e.detail)===String(node.id)){setBusy(true);status.textContent='Processing…';}else if(e.detail==null)setBusy(false);},{signal:abort.signal});
    api.addEventListener('execution_error',e=>{if(String(e.detail.node_id)===String(node.id)||busy)fail(new Error(e.detail.exception_message||'Graph execution failed'));},{signal:abort.signal});
    api.addEventListener('execution_cached',e=>{if(e.detail.nodes?.map(String).includes(String(node.id))){status.textContent='Cached · '+status.textContent.replace(/^(Cached|Generated) · /,'');setBusy(false);}},{signal:abort.signal});
    api.addEventListener('execution_interrupted',()=>{if(busy)fail(new Error('Cancel requested / execution interrupted'));},{signal:abort.signal});
    const remove=node.onRemoved;
    node.onRemoved=function(...args){removed=true;abort.abort();popup?.close();root.remove();return remove?.apply(this,args);};
    syncSockets(node);restore();node.setSize([440,680]);
    request('/presets').then(data=>{if(!removed){library=data.presets;drawPresets();}}).catch(fail);
}
app.registerExtension({name:'AVS.PromptHelper',nodeCreated(node){if(node.comfyClass===TYPE)install(node);}});
