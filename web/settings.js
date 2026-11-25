export const defaults = { adapter: 'openai', model: '', base_url: '', api_mode: 'chat', reasoning: 'auto', merge_mode: 'append', image_mode: 'original', max_mp: 1, timeout: 120, max_images: 32, max_output_tokens: 2048, output_mode: 'text' };

import { showNodeDialog } from './dialog.js';
const catalogs = new Map();
const effortNames = { auto: 'Auto / Provider default', thinking: 'Thinking on', no_thinking: 'Thinking off' };
const manualEfforts = adapter => adapter === 'kimi' ? ['thinking','no_thinking'] : adapter === 'claude' ? ['low','medium','high','xhigh','max'] : ['none','minimal','low','medium','high','xhigh','max','ultra'];

export function settingsPanel(settings, request, onSave, anchor) {
    const dialog = document.createElement('dialog'); dialog.className = 'avs-settings';
    const form = document.createElement('form'); form.method = 'dialog';
    dialog.ariaLabel = 'Settings';
    const fields = {};
    function group(name, rows) {
        const section = document.createElement('fieldset'), legend = document.createElement('legend'); legend.textContent = name; section.append(legend);
        rows.forEach(([key, label, options, type]) => {
            const row = document.createElement('label'); row.textContent = label;
            const input = document.createElement(options ? 'select' : 'input');
            input.ariaLabel = label;
            if (options) options.forEach(([value, text]) => input.add(new Option(text, value)));
            else input.type = type || 'text';
            if (type === 'number') input.step = key === 'max_mp' ? '0.1' : '1';
            input.value = settings[key] ?? defaults[key]; fields[key] = input; row.append(input); section.append(row);
        }); form.append(section);
    }
    group('Connection', [
        ['adapter', 'Adapter', [['openai','Native OpenAI Responses'],['compatible','OpenAI-compatible API'],['codex','Codex CLI'],['claude','Claude Code CLI'],['kimi','Kimi CLI']]],
        ['base_url','Compatible API base URL (including /v1)'],
        ['api_mode','Compatible API mode', [['chat','Chat Completions'],['responses','Responses'],['auto','Auto: Responses → Chat on 404/405']]]
    ]);
    group('Model', [['model','Model ID'], ['reasoning','Reasoning effort', ['auto',...manualEfforts(settings.adapter || defaults.adapter)].map(x => [x, effortNames[x] || x])]]);
    group('Generation', [['output_mode','Output', [['text','Text only'],['text_and_image','Text and image']]],
        ['merge_mode','External text', [['append','Append'],['replace','Replace internal'],['prepend','Prepend']]], ['max_output_tokens','Maximum output tokens',null,'number']]);
    group('Images', [['image_mode','Image size mode',[['original','Original resolution'],['max_mp','Maximum megapixels (MP)']]], ['max_mp','Maximum megapixels',null,'number'], ['max_images','Provider image limit (set from provider documentation)',null,'number']]);
    group('Advanced', [['timeout','Request timeout (seconds)',null,'number']]);
    fields.model.placeholder='e.g. gpt-6-luna';
    fields.model.title='Exact provider model ID, not its display name';
    const status = document.createElement('p'); status.role = 'status';
    const modelRow = document.createElement('label'); modelRow.textContent = 'Model';
    const modelSelect = document.createElement('select'); modelSelect.ariaLabel = 'Model'; modelRow.append(modelSelect);
    fields.model.parentElement.before(modelRow);
    const capabilityNote = document.createElement('small'); capabilityNote.className = 'avs-capability-note';
    fields.reasoning.parentElement.append(capabilityNote);
    let models = [];
    const connectionKey = () => JSON.stringify([fields.adapter.value, fields.base_url.value.trim(), fields.api_mode.value]);
    function refreshEfforts() {
        const previous = fields.reasoning.value || 'auto';
        const model = models.find(m => m.id === fields.model.value);
        const known = Array.isArray(model?.reasoning);
        const available = ['auto',...(known ? model.reasoning : manualEfforts(fields.adapter.value))];
        fields.reasoning.replaceChildren(...available.map(value => new Option(effortNames[value] || value, value)));
        fields.reasoning.value = available.includes(previous) ? previous : 'auto';
        capabilityNote.textContent = known ? (model.default_reasoning ? `Provider default: ${model.default_reasoning}` : '') : 'Capabilities not reported; explicit levels require model support.';
        capabilityNote.hidden = !capabilityNote.textContent;
        if (!available.includes(previous)) status.textContent += ` ${previous} is unavailable for this model; selected Auto.`;
    }
    function loadCatalog(result) {
        models = (result?.models || []).filter(m => typeof m.id === 'string' && m.id);
        modelSelect.replaceChildren(new Option('Enter model ID manually', ''));
        models.forEach(m => modelSelect.add(new Option(`${m.name || m.id}${m.name !== m.id ? ` · ${m.id}` : ''}`, m.id)));
        let selected = models.find(m => m.id === fields.model.value);
        // Resolve a typed display name only if the catalogue provides one unique match.
        if (!selected && fields.model.value.trim()) {
            const normalize = text => text.toLowerCase().replace(/[\s_-]+/g, '');
            const matches = models.filter(m => normalize(m.name || m.id) === normalize(fields.model.value));
            if (matches.length === 1) selected = matches[0];
        }
        if (!fields.model.value.trim()) selected = models.find(m => m.is_default);
        if (selected) fields.model.value = selected.id;
        modelSelect.value = selected?.id || '';
        modelRow.hidden = !models.length;
        fields.model.parentElement.hidden = Boolean(selected);
        refreshEfforts();
    }
    modelSelect.onchange = () => {
        if (modelSelect.value) fields.model.value = modelSelect.value;
        fields.model.parentElement.hidden = Boolean(modelSelect.value);
        if (!modelSelect.value) fields.model.focus();
        status.textContent = ''; refreshEfforts();
    };
    fields.model.oninput = refreshEfforts;
    const refresh = () => {
        const compatible=fields.adapter.value==='compatible';
        const codex=fields.adapter.value==='codex';
        if (!codex) fields.output_mode.value='text';
        fields.output_mode.parentElement.hidden=!codex;
        fields.base_url.parentElement.hidden=!compatible;fields.api_mode.parentElement.hidden=!compatible;
        fields.max_mp.parentElement.hidden=fields.image_mode.value!=='max_mp';
        fields.max_output_tokens.parentElement.hidden=['codex','claude','kimi'].includes(fields.adapter.value);
    };
    const connectionChanged = () => { status.textContent=''; refresh(); loadCatalog(catalogs.get(connectionKey())); };
    fields.adapter.onchange=connectionChanged; fields.base_url.oninput=connectionChanged; fields.api_mode.onchange=connectionChanged;
    fields.image_mode.onchange=refresh;refresh();loadCatalog(catalogs.get(connectionKey()));
    const values = () => Object.fromEntries(Object.entries(fields).map(([k, el]) => [k, el.type === 'number' ? Number(el.value) : el.value]));
    const test = document.createElement('button'); test.type = 'button'; test.textContent = 'Test connection';
    test.onclick = async () => {
        const key = connectionKey(); test.disabled = true; status.textContent = 'Loading models…';
        try {
            const result = await request('/test', values());
            catalogs.set(key, result);
            if (dialog.isConnected && key === connectionKey()) { status.textContent = result.message; loadCatalog(result); }
        } catch(e) { if (key === connectionKey()) status.textContent = e.message; }
        finally { test.disabled = false; }
    };
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel'; cancel.onclick = () => dialog.close();
    const save = document.createElement('button'); save.textContent = 'Save settings'; save.className = 'avs-primary avs-save-settings';
    form.onsubmit = e => { e.preventDefault(); onSave(values()); dialog.close(); };
    const actions=document.createElement('div');actions.className='avs-dialog-actions';actions.append(test,cancel,save);form.append(status,actions); dialog.append(form);
    return showNodeDialog(dialog,anchor);
}
