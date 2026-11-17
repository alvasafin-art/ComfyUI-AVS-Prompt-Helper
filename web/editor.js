export function color(id) {
    let hash = 0;
    for (const c of id) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
    return `hsl(${hash % 360} 74% 72%)`;
}

// Text nodes and atomic image references are the entire serializable document.
export function makeEditor(host, items, changed) {
    const editor = document.createElement('div');
    editor.className = 'avs-editor'; editor.contentEditable = 'true';
    editor.role = 'textbox'; editor.ariaLabel = 'Your Prompt'; editor.ariaMultiLine = 'true';
    editor.dataset.placeholder = 'Describe the prompt you want. Type @ to reference an image…';
    const menu = document.createElement('div'); menu.className = 'avs-mentions'; menu.role = 'listbox'; menu.hidden = true;
    host.append(editor, menu);
    let history = [], cursor = -1, composing = false, choice = 0, mentionRange;
    function read() {
        const parts = [];
        function walk(node) {
            if (node.nodeType === Node.TEXT_NODE) { parts.push(node.textContent); return; }
            if (node.dataset?.imageId) { parts.push({ image_id: node.dataset.imageId }); return; }
            if (node.tagName === 'BR') { parts.push('\n'); return; }
            if (['DIV', 'P'].includes(node.tagName) && parts.length) parts.push('\n');
            node.childNodes.forEach(walk);
        }
        editor.childNodes.forEach(walk);
        const merged = parts.reduce((out, part) => {
            if (typeof part === 'string' && typeof out.at(-1) === 'string') out[out.length - 1] += part;
            else out.push(part);
            return out;
        }, []);
        return merged.flatMap(part => {
            if (typeof part !== 'string') return [part];
            return part.split(/(@image_\d+\b)/g).filter(Boolean).map(text => {
                if (!/^@image_\d+$/.test(text)) return text;
                const item = items().find(i => '@' + i.label === text);
                return {image_id: item?.id || 'missing:' + text};
            });
        });
    }
    function chip(id) {
        const el = document.createElement('span'); el.className = 'avs-chip';
        el.contentEditable = 'false'; el.dataset.imageId = id;
        return el;
    }
    function relabel() {
        const list = items();
        editor.querySelectorAll('[data-image-id]').forEach(el => {
            const item = list.find(i => i.id === el.dataset.imageId);
            el.textContent = item ? '@' + item.label : '@missing_image';
            el.classList.toggle('avs-missing', !item); el.style.color = color(el.dataset.imageId);
            el.title = item ? item.source : 'Original image is missing. Remove this mention or restore the image.';
        });
    }
    function render(parts) {
        editor.replaceChildren(...parts.map(p => typeof p === 'string' ? document.createTextNode(p) : chip(p.image_id)));
        relabel();
    }
    function save() {
        const doc = read();
        if (JSON.stringify(doc) !== JSON.stringify(history[cursor])) {
            history = history.slice(0, cursor + 1); history.push(doc);
            if (history.length > 150) history.shift(); cursor = history.length - 1;
        }
        changed(doc);
    }
    function close() { menu.hidden = true; mentionRange = null; editor.removeAttribute('aria-activedescendant'); }
    function insert(node, range) {
        range.deleteContents(); range.insertNode(node); range.setStartAfter(node); range.collapse(true);
        const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); save();
    }
    function choose(item) {
        if (!mentionRange) return;
        const range = mentionRange; close(); editor.focus(); insert(chip(item.id), range); relabel();
    }
    function suggest() {
        const selection = getSelection();
        if (!selection?.rangeCount || !selection.isCollapsed) return close();
        const range = selection.getRangeAt(0);
        if (range.startContainer.nodeType !== Node.TEXT_NODE || !editor.contains(range.startContainer)) return close();
        const prefix = range.startContainer.textContent.slice(0, range.startOffset);
        const match = prefix.match(/@([a-z_\d]*)$/i);
        if (!match) return close();
        const matches = items().filter(i => i.label.startsWith(match[1]));
        if (!matches.length) return close();
        mentionRange = range.cloneRange(); mentionRange.setStart(range.startContainer, range.startOffset - match[0].length);
        menu.replaceChildren(); choice = 0;
        matches.forEach((item, index) => {
            const option = document.createElement('button'); option.type = 'button'; option.role = 'option';
            option.textContent = `@${item.label} · ${item.source}`; option.style.color = color(item.id);
            option.onpointerdown = e => { e.preventDefault(); choose(item); };
            option.dataset.index = index; menu.append(option);
        });
        menu.hidden = false; highlight();
    }
    function highlight() { [...menu.children].forEach((el, i) => { el.ariaSelected = String(i === choice); }); menu.children[choice]?.scrollIntoView({block:'nearest'}); }
    editor.oncompositionstart = () => composing = true;
    editor.oncompositionend = () => { composing = false; save(); suggest(); };
    editor.oninput = () => { if (!composing) { save(); suggest(); } };
    editor.onpaste = e => {
        e.preventDefault(); const text = e.clipboardData.getData('text/plain'); const range = getSelection()?.getRangeAt(0);
        if (range && editor.contains(range.startContainer)) insert(document.createTextNode(text), range);
    };
    editor.onkeydown = e => {
        e.stopPropagation();
        if ((e.ctrlKey || e.metaKey) && ['z', 'y'].includes(e.key.toLowerCase())) {
            e.preventDefault(); const delta = e.key.toLowerCase() === 'y' || e.shiftKey ? 1 : -1;
            cursor = Math.max(0, Math.min(history.length - 1, cursor + delta));
            render(history[cursor] || []); changed(read()); close(); return;
        }
        if (!menu.hidden && ['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape'].includes(e.key)) {
            e.preventDefault();
            if (e.key === 'Escape') return close();
            if (e.key === 'Enter' || e.key === 'Tab') { menu.children[choice]?.onpointerdown({preventDefault(){}}); return; }
            choice = (choice + (e.key === 'ArrowDown' ? 1 : -1) + menu.children.length) % menu.children.length; highlight();
        } else if (e.key === 'Enter') {
            e.preventDefault(); insert(document.createTextNode('\n'), getSelection().getRangeAt(0));
        }
    };
    editor.onblur = () => setTimeout(() => { close(); if (document.activeElement !== editor) render(read()); }, 100);
    return { read, relabel, set(parts) { render(parts); history = [read()]; cursor = 0; }, element: editor };
}
