# Verification — 2026-11-16

## Model catalogue revision

* **40 Python tests passed**, including Codex handshake/account check/pagination/cleanup, Claude initialization without user turns, per-model effort metadata, Kimi aliases and thinking flags, always-thinking rejection and error redaction.
* Live installed **Codex 0.166.0**: authenticated app-server discovery returned **8 models**. One recorded text probe through the node's actual transport, `gpt-6-luna` with `low`, returned **OK**. This confirms that combination works on this host; it does not identify the precise cause of the user's earlier generic failure. Image inference remains untested.
* `tests/browser_catalog.cjs` passed against actual ComfyUI: real Codex discovery, typed display-name resolution, unsupported effort reset, persistence of canonical ID/low after reopening, manual entry, and ignoring late responses after adapter switching. Claude and Kimi browser responses were fixtures because those CLIs are not installed. No JavaScript errors.
* Existing full browser smoke passed again: dialog centering/grouping/dismissal, real wheel zoom, sockets/uploads/workflow lifecycle, and four graph executions with exactly two local HTTP provider calls. Catalogue settings screenshot visually inspected.
* Claude and Kimi **live discovery/inference remain unverified**. Kimi discovery reads configured models/capabilities, not remote account availability. Tests never present this as a verified remote login.

## UI revision and added CLI adapters

The node now uses one continuous #181818 header/body with #080808 fields/cards and #F25623 actions. Removed body/subtitle labels, the inline system editor and its Save button. Preset creation/editing uses a separate dialog; the main body keeps the selector and compact actions. Cards are larger, graph cards show only a connection glyph plus Image_N, and the upload tile is an icon. Status precedes the bottom-right Regenerate button. Settings use unboxed sections, grey labels and orange section names, with no title or technical boilerplate.

**30 Python tests passed** after adding Claude and Kimi structured-input/output, image, tool-isolation, error and subprocess-cleanup tests. Repeated real Nodes 1.0 browser checks passed: creating/saving a preset in the new dialog, no inline textarea, no horizontal overflow at narrow width, save/load, sockets, upload, mentions, duplicate/collapse/zoom, and four queue executions yielding exactly two mock-provider calls. No JavaScript page errors. Current main/settings/preset screenshots were visually inspected, including the final darker unified body.

Claude/Kimi programs were not found locally. Their implementations are tested against documented protocols with mocked subprocesses; real login/model/image inference remains unverified. DeepSeek was excluded at the user's request.

## Implemented

Installable Python custom node, one STRING output; native JavaScript/CSS classic-canvas interface; structured image references; optional external STRING; up to 20 dynamic IMAGE sockets; browser uploads; per-user persistent presets; workflow snapshots; common image preprocessing; native Responses, compatible Responses/Chat and Codex CLI transports; atomic bounded persistent cache; regeneration receipts and real graph queue integration.

## Executed

* Python 3.12.11: **22 tests passed**, including an actual local aiohttp endpoint for Chat/Responses, fallback only on unsupported endpoints, cache/single-flight/regeneration, fingerprints, image validation/resize/EXIF/alpha, ordered references, merge modes, preset isolation, CLI argument/output mock tests and protective-flag rejection.
* Installed Codex CLI `exec --help` inspected; native executable resolved; required protective flags confirmed. Initial tests did not request CLI inference; the later catalogue revision includes a live text probe described above.
* Real isolated ComfyUI **v0.45.4**, frontend **1.58.5**, CPU mode, Edge headless, **Nodes 1.0** selected. Plugin loaded successfully without changing core files.
* Browser tests: editor inputs, settings dialog, narrow width without horizontal overflow, workflow serialize/reload, collapse/expand, canvas zoom/pan, duplication with retained prompt, no leaked DOM after reload/removal, all 20 IMAGE sockets connect and trailing spares prune back to one, browser file upload, colored structured reference, real graph execution into built-in PreviewAny.
* Actual Queue → Queue → button Regenerate → Queue: **four graph executions, exactly two HTTP provider calls**, updated downstream `prompt-result-2`, uploaded image present in multimodal payload. This provider was a local deterministic HTTP fixture, not a paid model.
* JavaScript syntax checks passed; browser reported no page errors. Screenshots of the actual UI were rendered and visually inspected in `test-results/`. A narrow-layout footer shrink issue and accessible field labels were corrected.

## Not verified / constraints

* Live OpenAI API inference and Codex image inference remain untested. Responses protocol assembly uses local fixtures; Codex text/authentication was verified for the specific combination above. Other provider/model acceptance requires the user's configured account and model.
* No live LM Studio/Ollama/vLLM server, Linux execution, Nodes 2.0, cross-machine browser/upload deployment or reverse-proxy authentication test.
* Manual browser zoom, full undo/redo/caret matrix including IME, all drag/drop variants, concurrent browser tabs/users, OS-level CLI cancellation and provider-side cancellation/billing still require environment-specific testing.
* Codex read-only sandbox is an agent sandbox rather than proof of strict text-only inference; see README. Required isolation flags are capability-checked. Server config deliberately holds executable paths rather than accepting arbitrary executable paths from browser workflows.
* Graph tensors show honest placeholder cards, not tensor previews. Batches larger than one fail clearly. Provider limits/reasoning are explicitly configured and errors surfaced; no universal capability auto-detection is claimed.
* Single-flight is per server process. Disk cache and upload capability handles are installation-wide; presets are isolated by ComfyUI user ID. Upload retention is manual to preserve old workflows.

The implementation is usable and its classic UI has been visually checked; full provider/platform acceptance is pending the live checks above. Do not interpret mock-provider results as proof of a specific paid model's compatibility.

## Icon and alignment refinement

Preset text darkened; native select arrows replaced with a consistent 12 px right inset (including Settings). Graph connection icon is now a half-size SVG with filled circles, thicker centered stroke and full-card vertical centering. Add-image plus is light grey, Images caption removed, gear doubled. Regenerate has centered white text and no icon; Save settings text is also white. Real browser smoke passed, including four queues/two mock calls. Computed styles verified Save settings white, arrow inset and borderless settings sections; current screenshots visually reviewed.

## Library dialog and wheel interaction

Grouped Edit/Duplicate and Export/Import actions; isolated Delete preset at the bottom. Removed Close; all node dialogs dismiss on backdrop click and anchor to the node body center, clamped inside the viewport. Gear reduced from 34 to 22.67 px. Wheel events over the node now forward to the canvas; focused overflowing editors retain local scrolling. Browser test used real mouse wheel input in both directions, checked dialog center within 2 px, outside dismissal, graph serialization and regeneration. Passed without page errors; library screenshot visually reviewed. Model input now hints that an exact provider ID is required. Local Codex metadata lists gpt-6-luna and reasoning low/medium/high/xhigh/max; display names are not translated automatically.
