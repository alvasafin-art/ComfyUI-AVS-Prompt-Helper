const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function main() {
    const browser = await chromium.launch({ headless: true, channel: 'msedge' });
    try {
        const page = await browser.newPage({ viewport: { width: 1400, height: 950 } });
        await page.goto('http://127.0.0.1:8199');
        await page.waitForFunction(() => window.app?.graph && window.LiteGraph, { timeout: 60000 });
        await page.keyboard.press('Escape');
        const result = await page.evaluate(async () => {
            const { app } = await import('/scripts/app.js');
            await app.extensionManager.setting.set('Comfy.VueNodes.Enabled', false);
            app.graph.clear();
            const helper = LiteGraph.createNode('AVSPromptHelper');
            const text = LiteGraph.createNode('PreviewAny');
            const image = LiteGraph.createNode('PreviewImage');
            helper.pos = [200, 100];
            text.pos = [700, 100];
            image.pos = [700, 400];
            for (const node of [helper, text, image]) app.graph.add(node);
            helper.connect(0, text, 0);
            const slots = node => node.outputs.map(({ name, type }) => [name, type]);
            const fresh = slots(helper);
            const oldWorkflow = app.graph.serialize();
            const oldHelper = oldWorkflow.nodes.find(node => node.type === 'AVSPromptHelper');
            oldHelper.outputs = oldHelper.outputs.slice(0, 1);
            app.graph.configure(oldWorkflow);
            const find = type => app.graph._nodes.find(node => node.type === type);
            const savedHelper = find('AVSPromptHelper');
            const restored = slots(savedHelper);
            const textConnected = find('PreviewAny').inputs[0].link != null;
            const state = JSON.parse(savedHelper.widgets.find(widget => widget.name === 'state').value);
            savedHelper.connect(1, find('PreviewImage'), 0);
            return { fresh, restored, textConnected, outputMode: state.settings?.output_mode ?? 'text',
                imageConnected: find('PreviewImage').inputs[0].link != null };
        });
        const expected = [['prompt', 'STRING'], ['image', 'IMAGE']];
        assert.deepEqual(result.fresh, expected);
        assert.deepEqual(result.restored, expected);
        assert.equal(result.textConnected, true);
        assert.equal(result.outputMode, 'text');
        assert.equal(result.imageConnected, true);

        await page.getByRole('button', { name: 'Settings', exact: true }).click();
        await page.getByLabel('Adapter', { exact: true }).selectOption('codex');
        await page.getByLabel('Output', { exact: true }).selectOption('text_and_image');
        const discovery = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/avs-prompt/image-cli'));
        await page.getByRole('button', { name: 'Test connection', exact: true }).click();
        assert.equal((await discovery).ok(), true);
        await page.getByRole('option', { name: /Server fixture/ }).waitFor({ state: 'attached' });
        console.log('Fresh and migrated ports, preserved text link, new image link and server discovery passed.');
    } finally {
        await browser.close();
    }
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
