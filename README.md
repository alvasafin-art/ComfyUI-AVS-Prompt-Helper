# AVS Prompt Helper

A ComfyUI custom node that turns instructions and optional images into one `STRING` prompt using external models. Designed for the classic Nodes 1.0 canvas, using ComfyUI's `addDOMWidget` lifecycle. It loads no inference model into VRAM.

## Install

Copy this repository to `ComfyUI/custom_nodes/ComfyUI-AVS-Prompt-Helper` (the folder name is flexible). Install requirements with **ComfyUI's Python**, then restart ComfyUI and refresh the browser:

```powershell
& 'C:\path\to\ComfyUI\.venv\Scripts\python.exe' -m pip install -r 'PATH\ComfyUI-AVS-Prompt-Helper\requirements.txt'
```

For portable Windows use `python_embeded\python.exe -m pip install -r ...`. On Linux use the ComfyUI venv's `python -m pip install -r requirements.txt`. Add **AVS / Prompt → AVS Prompt Helper**. Connect its `prompt` output to a downstream STRING consumer. A node without a path to an output node is not executed by ComfyUI.

## Connections

Open the gear button, choose the adapter and click **Test connection**. Choose a model from the returned list; its exact CLI/API ID is saved. Reasoning choices follow that model's reported capabilities. Manual model ID entry remains available. No generation is requested during discovery.

* **Native OpenAI Responses:** set `OPENAI_API_KEY` in the environment that starts ComfyUI. Uses `https://api.openai.com/v1/responses`, independent instructions and interleaved image labels/attachments.
* **OpenAI-compatible:** specify the complete base URL, for example `http://127.0.0.1:1234/v1`, and the server's model ID. Select Chat Completions or Responses. Auto attempts Responses and falls back only on HTTP 404/405. Set `AVS_COMPATIBLE_API_KEY` on the server if required. LM Studio, Ollama and vLLM must expose their compatible HTTP API; model vision/reasoning support remains provider-specific.
* **Codex CLI:** install and authenticate Codex on the **ComfyUI server**, using `codex login` outside this node. Set `AVS_CODEX_EXECUTABLE` to the native executable if it is not on PATH. Windows npm `.cmd`/`.ps1` shims are resolved to their packaged `codex.exe`; shell interpolation is never used. Paths containing spaces are supported.

Environment variables can be set before launching ComfyUI:

```powershell
$env:OPENAI_API_KEY = 'your-key'
$env:AVS_CODEX_EXECUTABLE = 'C:\path with spaces\codex.exe'
# Start ComfyUI from this environment afterwards.
```

Keys and executable paths are server-local; they are never written to workflows/presets or returned by connection tests. API keys must not be placed in a base URL. Discovery does not prove that a subsequent inference or image request will succeed.

### Model and reasoning discovery

* **Codex:** app-server `initialize` → `account/read` → paginated `model/list`. The account must be authenticated for the ComfyUI server user and `CODEX_HOME`. Model IDs, names, supported reasoning efforts and provider defaults come from the CLI. Includes `ultra` when reported. An empty selection uses the CLI-reported default model. A typed display name is resolved only when it uniquely matches the catalogue.
* **Claude Code:** stream-json SDK `initialize` control request, without a user message. Reads `models[].value`, `displayName`, `supportedEffortLevels` and `supportsEffort`. This is the initialization catalogue used by the Agent SDK; it is not proof of account entitlement or successful inference. Older CLIs without capability metadata retain manual effort selection with a note.
* **Kimi:** checks CLI compatibility, then reads the configured model aliases and capabilities from the same server configuration used for generation. Supports Auto, Thinking on and Thinking off, depending on model capabilities; always-thinking models cannot be switched off. The reviewed Kimi Wire protocol has no equivalent `model/list` request. This is a configured catalogue, not a live remote account check; refresh managed models in Kimi with `/model` before testing again. This adapter targets the documented Python Kimi CLI flags/config format; a different successor executable must support those flags.
* **Native/compatible API:** reads `/models`; the standard response does not describe reasoning capabilities, so manual efforts remain available with a note.

Selecting a model with incompatible saved effort resets effort to Auto and reports the change. Catalogues are kept in browser memory per connection, not saved into workflows. Stale results from a different adapter are ignored. Codex generation failures now show the specific CLI error with credential/prompt redaction instead of the former generic login warning.

Protocol references: [Codex app-server](https://learn.chatgpt.com/docs/app-server), [Claude ModelInfo](https://code.claude.com/docs/en/agent-sdk/typescript#modelinfo), [Kimi model configuration](https://github.com/MoonshotAI/kimi-cli/blob/main/src/kimi_cli/config.py), [Kimi thinking capabilities](https://github.com/MoonshotAI/kimi-cli/blob/main/src/kimi_cli/llm.py).

Codex requires `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, `--sandbox`, `--image`, and `--output-last-message`. The installed CLI was inspected and supports these. Older CLI versions fail with an upgrade message. Runs use a temporary directory, read-only sandbox, approval policy `never`, disabled shell/unified-exec features and disabled web search. User MCP and hook configuration is excluded. System/user instructions are clearly separated in stdin because `codex exec` has no separate system-message argument. Codex remains an agent CLI, not a strict text-only inference API: OS sandbox behavior is version/platform-dependent and read-only does not guarantee all outside files are unreadable. Native API is the most predictable transport. No dangerous auto-approval flags are used.

## Using the node

1. **Your Prompt:** write your request. `@` opens an image menu; use arrows and Enter/Tab, Escape to dismiss. References are stored as stable image IDs and shown as colored labels. Pasted plain text stays plain except recognized image aliases, which bind to the current image. Missing references fail before contacting a provider. Undo/redo has a per-editor history.
2. **Preset selector:** choose a system prompt. `+` opens a separate dialog with Name, Prompt and Save. `⋯ → Edit prompt` opens the selected preset for editing/renaming; duplicate, delete and JSON import/export are also available. Presets contain only ID, name and system text. Cancelling the dialog does not change the workflow. Existing custom workflow instructions remain available through Edit prompt.
3. **Images:** connect graph IMAGE sockets or add files from the browser's file picker/drop area. Graph images come first in socket order, uploads afterwards. Move an upload left with its arrow; remove it with ×. Stable references preserve their targets when numbering changes.

There is one spare IMAGE socket, expanding to 20 connected sockets. The external STRING input coexists with the editor: Append (default) puts internal text first, blank line, external text; Prepend reverses order; Replace internal uses nonempty external text. Graph image cards explicitly indicate that no preview is available before execution.

Examples: for text-only, enter an instruction and connect to a text encoder; for multi-image, attach references and use `@image_1`/`@image_2`; for reusable rules, save a system preset and connect a variable upstream STRING as the subject. Prompt rules for FLUX/Qwen or other image models are entirely user supplied.

The workflow saves a **snapshot** of system text and the selected preset ID. Library updates apply only when you explicitly select a preset again; loading a workflow never silently adopts new preset text. A differing snapshot is identified in the selector tooltip. Upload IDs are also stored in the workflow. On another machine migrate the upload directory or re-upload missing assets.

## Claude Code and Kimi CLI

Select **Claude Code CLI** or **Kimi CLI** in Settings. Install/authenticate the respective program on the ComfyUI server first. Set `AVS_CLAUDE_EXECUTABLE` or `AVS_KIMI_EXECUTABLE` if the native executable is not on PATH. Claude npm shims are resolved to `node` plus the installed `cli.js`, without a shell. Kimi uses a native executable, including the Windows Python entry-point `.exe`.

Claude uses noninteractive structured input/output, a separate system-prompt file, inline base64 image content, no tools, bare mode, no discovered settings/MCP servers/hooks, and no session persistence. Explicit effort supports low/medium/high/xhigh/max subject to model support. Required CLI flags are checked before generation.

Kimi uses a custom agent with **no tools or subagents**, an explicit empty MCP file and empty skills directory. Its print mode auto-approves tools internally, so the tool-free agent is essential. Provider/model/auth definitions are read from `~/.kimi/config.toml` or `AVS_KIMI_CONFIG` (JSON/TOML); only these definitions and thinking defaults are copied into a temporary restricted config. Hooks/plugins/services are excluded. Images use the documented Kosong image URL content schema. Auto retains the configured thinking mode; explicit supported modes use `--thinking` / `--no-thinking`. Kimi may retain CLI session/log data in its own user directory. No inferred usage is shown.

For all CLI adapters, output-token limits belong to the CLI/model configuration; the API output-limit control is hidden. CLI flags/schemas were checked against official documentation and tested with mocked subprocesses; **live Claude/Kimi generation has not been tested**, and neither executable was installed in the development environment. Unsupported installed versions fail rather than dropping isolation flags. DeepSeek Harness is intentionally excluded.

References: [Claude CLI](https://code.claude.com/docs/en/cli-reference), [Kimi print mode](https://github.com/MoonshotAI/kimi-cli/blob/main/docs/en/customization/print-mode.md), [Kimi agent files](https://github.com/MoonshotAI/kimi-cli/blob/main/docs/en/customization/agents.md), [Kimi message schemas](https://github.com/MoonshotAI/kimi-cli/blob/main/packages/kosong/src/kosong/message.py).

## Images and reasoning

PNG/JPEG/WebP still images, up to 25 MiB per upload and 80 MP decoded. EXIF orientation is applied and alpha is preserved in PNG requests. Original resolution keeps oriented pixel dimensions. Maximum megapixels only downsamples: `sqrt(max_mp * 1e6 / area)`, integer dimensions below the ceiling, Lanczos filtering. The same pipeline handles tensors and uploads, never overwriting originals.

Each IMAGE socket accepts exactly one `[1,H,W,C]` tensor, C=1/3/4. Split batches upstream: a multi-frame batch is rejected rather than silently truncating it. Float values are clamped to [0,1], transferred to CPU and encoded; NaN/Inf are rejected. Combined PNG payload is limited to 40 MiB. Upload count is independent of the 20 graph sockets; total image limit defaults to 32 and is configurable. Set the limit from your provider's documentation. Providers may impose stricter limits or internally resize images. MP does not guarantee a particular token saving.

Auto reasoning omits the parameter. Explicit levels are passed without translation; incompatible models/endpoints produce a visible error rather than silently discarding the setting. Chat Completions compatibility uses `max_tokens`; endpoints requiring different fields should use Responses if available. There is no universal model capability discovery protocol.

## Cache, execution and cancellation

Queue calls a provider only if the effective request changed and no plugin cache entry exists. SHA-256 covers prompt, system text, ordered processed image contents, settings and schema version. The cache holds successful final text and actual usage; it never stores image payloads or keys. It is atomic and bounded to 512 entries / 64 MiB, survives restarts, and coalesces simultaneous identical requests in one server process. Use one ComfyUI process per data directory; cross-process single flight is not implemented.

Regenerate creates a unique serialized request token and queues the graph. Its durable receipt permits exactly one new generation for the same request/token, then normal queue executions reuse the replacement. Different node instances/workflows share semantic cache entries. ComfyUI's own cache can skip execution entirely; its cached event updates the footer. Eviction or manual cache deletion intentionally removes reuse guarantees. Regeneration receipts retain the latest 256 tokens per entry.

No automatic retries for timeouts, rate limits or 5xx: the provider might already have accepted a billable request. Correct the issue and queue again explicitly. ComfyUI interruption is polled while waiting; the HTTP task or CLI process is cancelled. An external provider may still finish/bill work already received. Failed, cancelled, incomplete and empty responses are not cached. No costs/token values are invented; unavailable usage is N/A.

## Storage and routes

Default: `ComfyUI/user/avs_prompt_helper`; override with `AVS_PROMPT_HELPER_DATA`. Subdirectories: `presets`, `uploads`, `cache`. Presets are isolated using ComfyUI's validated user identity. Cache and unguessable 256-bit upload handles are shared across this installation so workflow duplication/sharing works. Handles act as bearer capabilities: anyone possessing a workflow handle and server access can fetch that attachment. Protect remotely exposed ComfyUI with its authentication/reverse proxy. ComfyUI user IDs alone are not strong authentication.

Routes use ComfyUI session infrastructure and reject mismatched Origin headers:

| Route | Behavior |
|---|---|
| GET `/avs-prompt/presets` | Current user's library |
| POST `/avs-prompt/presets` | `operation: save/delete`; only name/system text/ID persisted |
| POST `/avs-prompt/upload` | Multipart `image`, decoded/validated and stored under random ID |
| GET `/avs-prompt/assets/{id}` | Attachment preview; no user-supplied filesystem paths |
| POST `/avs-prompt/test` | Non-generating discovery; message, models with IDs/names/efforts, source for CLI |

Uploads are retained so older workflows keep working. Delete unused uploads manually only after checking saved workflows. Malformed cache/preset JSON falls back safely; the next successful write replaces it. The disk cache contains generated text, so treat the data directory as private.

## Development and verification

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest pytest-asyncio
.\.venv\Scripts\python.exe -m pytest -q
node --check web/index.js
```

Tests cover resizing/EXIF/alpha, tensor validation, image ordering, stable mentions, merge modes, preset isolation/snapshots, path validation, fingerprints, single flight and regeneration, real local HTTP Responses/Chat transport and no unsafe retry. Start an isolated CPU ComfyUI server for the browser checks with `tests/start_smoke.ps1 -Python <python.exe> -ComfyRoot <folder containing main.py>`. With Playwright and Microsoft Edge installed, run `node tests/browser_smoke.cjs` from the repository root. `tests/browser_catalog.cjs` also checks discovery and requires an authenticated Codex CLI. These browser checks do not request model generation from a remote provider.

Manual Nodes 1.0 checklist: resize width/height; canvas pan/zoom and browser zoom; collapse/expand; duplicate; save/reopen; connect all 20 sockets, disconnect/undo; upload/drop multiple files; autocomplete/undo/paste/dangling mention; preset CRUD/restart; connect an output consumer and Queue twice, Regenerate once, Queue again; check actual provider invocation count and downstream text; interrupt a running request; reopen after migrating/missing uploads; check two browser tabs/users. See `TEST_REPORT.md` for checks actually executed and remaining limitations.

Official implementation references: [ComfyUI hooks](https://github.com/Comfy-Org/docs/blob/main/custom-nodes/js/javascript_hooks.mdx), [DOM widget implementation](https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/src/scripts/domWidget.ts), [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create).
