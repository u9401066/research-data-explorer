import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { getPythonArgs, loadSkillContent, BUNDLED_SKILLS, BUNDLED_PROMPTS, BUNDLED_AGENTS, BUNDLED_CLINE_RULES } from './utils';
import { findUvPath, installUvHeadless, buildMcpCommand, buildMcpEnv, ensureInstalledTool, checkDockerServiceHealth } from './uvManager';
import {
    shouldSkipMcpRegistration,
    isDevWorkspace as checkIsDevWorkspace,
    determinePythonPath,
    countMissingBundledItems,
    buildDevPythonPath,
    isBundledToolProject,
    codexConfigPath,
    configureCodexRdeMcpConfigFile,
} from './extensionHelpers';
import { TOOL_GROUPS, FULL_REPORT_CHAT_QUERY, MISSING_BOOTSTRAP_RDE_TOOLS_MESSAGE, buildPipelineExecutionPrompt, buildToolRetryInstruction, filterRdeTools, findMissingRequiredRdeTools, getToolCallPolicyAction, NO_AVAILABLE_RDE_TOOLS_MESSAGE, NO_RDE_TOOL_CALL_MESSAGE, toolGroupIncludes } from './toolPolicy';
import { readUxHarnessArtifacts, renderUxHarnessDashboardHtml, summarizeUxHarnessArtifacts } from './uxHarnessView';

let outputChannel: vscode.OutputChannel;
let resolvedUvPath: string | null = null;
let automlServiceAvailable = false;

export async function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('Research Data Explorer');
    outputChannel.appendLine('Research Data Explorer is activating...');

    // Step 1: Ensure uv is installed
    await ensureUvReady(context);

    // Step 1.5: Marketplace mode auto-installs required persistent tool binaries
    await ensureMarketplaceToolsReady(context);

    // Step 1.6: Check optional automl-stat-mcp availability (non-blocking)
    if (vscode.workspace.getConfiguration('rde').get<boolean>('automlAutoCheck', true)) {
        await checkAutomlAvailability(context);
    }

    // Step 2: Register MCP Server Definition Provider
    const mcpProvider = registerMcpServerProvider(context);
    context.subscriptions.push(mcpProvider);

    // Register Chat Participant Handler
    const chatHandler = registerChatParticipant(context);
    if (chatHandler) {
        context.subscriptions.push(chatHandler);
    }

    // Register Commands
    context.subscriptions.push(
        vscode.commands.registerCommand('rde.startServer', () => {
            vscode.window.showInformationMessage('RDE MCP Server is managed automatically by VS Code.');
        }),
        vscode.commands.registerCommand('rde.stopServer', () => {
            vscode.window.showInformationMessage('RDE MCP Server will stop when VS Code closes.');
        }),
        vscode.commands.registerCommand('rde.showStatus', () => {
            outputChannel.show();
            outputChannel.appendLine(`[${new Date().toISOString()}] Research Data Explorer Status: Active`);
        }),
        vscode.commands.registerCommand('rde.openHarnessDashboard', () => {
            openUxHarnessDashboard(context);
        }),
        vscode.commands.registerCommand('rde.runPipeline', () => {
            vscode.commands.executeCommand('workbench.action.chat.open', {
                query: FULL_REPORT_CHAT_QUERY
            });
        }),
        vscode.commands.registerCommand('rde.setupWorkspace', () => {
            setupWorkspace(context);
        }),
        vscode.commands.registerCommand('rde.configureCodex', async () => {
            await configureCodexMcp(context, false);
        }),
        vscode.commands.registerCommand('rde.checkAutoml', async () => {
            outputChannel.show();
            await checkAutomlAvailability(context);
            if (automlServiceAvailable) {
                vscode.window.showInformationMessage('✅ automl-stat-mcp 服務正常運行中；重型進階分析會自動委派。');
            } else {
                const choice = await vscode.window.showInformationMessage(
                    'automl-stat-mcp 未偵測到；RDE 仍會使用 local-lite 完成核心報告流程。Docker 只在重型 vendor workflow 需要。',
                    '查看可選啟動說明',
                    '關閉'
                );
                if (choice === '查看可選啟動說明') {
                    outputChannel.appendLine('\n=== automl-stat-mcp 可選啟動方式 ===');
                    outputChannel.appendLine('cd vendor/automl-stat-mcp && docker compose up -d');
                    outputChannel.appendLine('服務端口: stats-service=8003, automl-service=8001');
                    outputChannel.appendLine('================================\n');
                }
            }
        })
    );

    // Auto-scaffold: check if workspace is missing skills/agents/prompts
    autoScaffoldIfNeeded(context);
    configureCodexMcp(context, true);

    outputChannel.appendLine('Research Data Explorer activated successfully!');
}

function openUxHarnessDashboard(context: vscode.ExtensionContext): void {
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workspaceRoot) {
        vscode.window.showWarningMessage('Open a workspace before viewing the RDE UX harness dashboard.');
        return;
    }

    const artifacts = readUxHarnessArtifacts(workspaceRoot);
    const summary = summarizeUxHarnessArtifacts(artifacts);
    const panel = vscode.window.createWebviewPanel(
        'rdeUxHarnessDashboard',
        'RDE UX Harness',
        vscode.ViewColumn.One,
        {
            enableScripts: false,
            retainContextWhenHidden: true,
        },
    );
    panel.iconPath = vscode.Uri.joinPath(context.extensionUri, 'media', 'icon.png');
    panel.webview.html = renderUxHarnessDashboardHtml(artifacts);

    outputChannel.appendLine(
        `[UX] Dashboard opened: ${summary.present}/${summary.total} artifacts present; ` +
        `missing tools=${summary.missingTools.join(', ') || 'none'}`,
    );

    if (summary.missing > 0) {
        vscode.window.showInformationMessage(
            `RDE UX harness is missing ${summary.missing} artifact(s).`,
            'Generate via @rde',
        ).then(choice => {
            if (choice === 'Generate via @rde') {
                vscode.commands.executeCommand('workbench.action.chat.open', {
                    query: '@rde /pipeline Generate the RDE UX harness artifacts for the current project using get_approval_card, get_harness_dashboard, build_artifact_index, and get_blocker_playbook.',
                });
            }
        });
    }
}

// ─── automl-stat-mcp Health Check ──────────────────────────────────────────────

async function checkAutomlAvailability(context: vscode.ExtensionContext): Promise<void> {
    const config = vscode.workspace.getConfiguration('rde');
    const automlEndpoint = config.get<string>('automlEndpoint') || 'http://localhost:8002';
    const statsEndpoint = automlEndpoint.replace(':8002', ':8003');

    const log = (msg: string) => outputChannel.appendLine(`[automl] ${msg}`);

    log(`Checking automl-stat-mcp availability...`);

    // Check stats-service (port 8003) — the primary analysis engine
    const statsHealthUrl = `${statsEndpoint}/health`;
    const statsAvailable = await checkDockerServiceHealth(statsHealthUrl, 3000, log);

    if (statsAvailable) {
        automlServiceAvailable = true;
        log('automl-stat-mcp is available — heavy advanced analyses will be delegated');
    } else {
        automlServiceAvailable = false;
        log('automl-stat-mcp not detected — core report flow will use local-lite analysis');
        log('Optional heavy engine: cd vendor/automl-stat-mcp && docker compose up -d');
    }

    context.globalState.update('automlAvailable', automlServiceAvailable);
}

// ─── uv Setup ──────────────────────────────────────────────────────────────────

async function ensureUvReady(context: vscode.ExtensionContext): Promise<void> {
    const log = (msg: string) => outputChannel.appendLine(`[uv] ${msg}`);

    log('Checking uv installation...');
    resolvedUvPath = await findUvPath(log);

    if (resolvedUvPath) {
        log(`uv is ready: ${resolvedUvPath}`);
        context.globalState.update('uvPath', resolvedUvPath);
        return;
    }

    log('uv not found, prompting user...');
    const choice = await vscode.window.showInformationMessage(
        'Research Data Explorer 需要 "uv" (Python 套件管理器) 才能運行。要自動安裝嗎？',
        '自動安裝 uv',
        '手動安裝',
        '取消'
    );

    if (choice === '自動安裝 uv') {
        resolvedUvPath = await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'RDE: 正在安裝 uv...',
                cancellable: false
            },
            async (progress) => {
                progress.report({ message: '下載並安裝 uv (Python 套件管理器)...' });
                const installed = await installUvHeadless(log);

                if (installed) {
                    progress.report({ message: '安裝完成！' });
                    context.globalState.update('uvPath', installed);

                    const reload = await vscode.window.showInformationMessage(
                        '✅ uv 安裝成功！請重新載入 VS Code 以完成設定。',
                        '重新載入'
                    );
                    if (reload === '重新載入') {
                        vscode.commands.executeCommand('workbench.action.reloadWindow');
                    }
                } else {
                    vscode.window.showErrorMessage(
                        'uv 安裝失敗。請手動安裝: https://docs.astral.sh/uv/',
                        '開啟安裝頁面'
                    ).then(c => {
                        if (c === '開啟安裝頁面') {
                            vscode.env.openExternal(vscode.Uri.parse('https://docs.astral.sh/uv/getting-started/installation/'));
                        }
                    });
                }
                return installed;
            }
        );
    } else if (choice === '手動安裝') {
        vscode.env.openExternal(vscode.Uri.parse('https://docs.astral.sh/uv/getting-started/installation/'));
    }
}

// ─── Marketplace Tool Install ──────────────────────────────────────────────────

async function ensureMarketplaceToolsReady(context: vscode.ExtensionContext): Promise<void> {
    if (!resolvedUvPath) {
        outputChannel.appendLine('[Install] Skipping tool auto-install because uv is not ready.');
        return;
    }

    const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const isDevWs = wsRoot ? checkIsDevWorkspace(wsRoot) : false;
    if (isDevWs) {
        outputChannel.appendLine('[Install] Development workspace detected - skipping marketplace tool auto-install.');
        return;
    }

    if (wsRoot) {
        const mcpJsonPath = path.join(wsRoot, '.vscode', 'mcp.json');
        if (fs.existsSync(mcpJsonPath)) {
            try {
                const content = fs.readFileSync(mcpJsonPath, 'utf-8');
                if (shouldSkipMcpRegistration(content)) {
                    outputChannel.appendLine('[Install] User-managed mcp.json detected - skipping marketplace tool auto-install.');
                    return;
                }
            } catch {
                outputChannel.appendLine('[Install] Could not inspect .vscode/mcp.json - continuing with checks.');
            }
        }
    }

    const bundledToolPath = path.join(context.extensionPath, 'bundled', 'tool');
    if (isBundledToolProject(bundledToolPath)) {
        outputChannel.appendLine('[Install] Bundled RDE project detected - skipping registry install.');
        return;
    }

    const toolSpecs: Array<{ packageName: string; binaryName?: string }> = [
        { packageName: 'research-data-explorer' },
    ];

    const log = (msg: string) => outputChannel.appendLine(`[Install] ${msg}`);

    await vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title: 'RDE: 正在檢查並安裝 MCP 相依套件...',
            cancellable: false,
        },
        async (progress) => {
            const total = toolSpecs.length;
            for (let i = 0; i < total; i++) {
                const spec = toolSpecs[i];
                progress.report({
                    message: `檢查 ${spec.binaryName || spec.packageName} (${i + 1}/${total})`,
                    increment: 100 / total,
                });
                await ensureInstalledTool(spec.packageName, spec.binaryName, undefined, log);
            }
        }
    );
}

// ─── MCP Server Provider ───────────────────────────────────────────────────────

function registerMcpServerProvider(context: vscode.ExtensionContext): vscode.Disposable {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (workspaceFolders) {
        const mcpJsonPath = path.join(workspaceFolders[0].uri.fsPath, '.vscode', 'mcp.json');
        if (fs.existsSync(mcpJsonPath)) {
            try {
                const content = fs.readFileSync(mcpJsonPath, 'utf-8');
                if (shouldSkipMcpRegistration(content)) {
                    outputChannel.appendLine('[MCP] Found rde in .vscode/mcp.json - skipping auto-registration');
                    return { dispose: () => { /* noop */ } };
                }
            } catch {
                outputChannel.appendLine('[MCP] Could not read .vscode/mcp.json - proceeding with auto-registration');
            }
        }
    }

    const provider: vscode.McpServerDefinitionProvider = {
        onDidChangeMcpServerDefinitions: new vscode.EventEmitter<void>().event,

        provideMcpServerDefinitions(_token: vscode.CancellationToken): vscode.ProviderResult<vscode.McpServerDefinition[]> {
            const wsFolders = vscode.workspace.workspaceFolders;
            const wsRoot = wsFolders?.[0]?.uri.fsPath;

            const isDevWs = wsRoot ? checkIsDevWorkspace(wsRoot) : false;
            const uvPath = resolvedUvPath || (context.globalState.get<string>('uvPath')) || 'uv';

            outputChannel.appendLine(`[MCP] Mode: ${isDevWs ? 'development' : 'marketplace'}, uv: ${uvPath}`);

            const definitions: vscode.McpServerDefinition[] = [];
            const bundledToolPath = path.join(context.extensionPath, 'bundled', 'tool');
            const hasBundledTool = isBundledToolProject(bundledToolPath);

            let rdeCommand: string;
            let rdeArgs: string[];
            let mcpEnv: Record<string, string>;

            if (isDevWs && wsRoot) {
                // Development: use workspace source via uv run
                const pythonPath = getPythonPath(context);
                rdeCommand = pythonPath;
                rdeArgs = getPythonArgs(pythonPath, 'rde', pythonPath === 'uv' ? { projectPath: wsRoot } : undefined);

                const pythonPathEnv = buildDevPythonPath(wsRoot, bundledToolPath);
                mcpEnv = buildMcpEnv({ workspaceDir: wsRoot, pythonPath: pythonPathEnv });
            } else if (hasBundledTool) {
                // Packaged extension: run the bundled local Python project via uv.
                rdeCommand = uvPath;
                rdeArgs = getPythonArgs(uvPath, 'rde', { projectPath: bundledToolPath });
                mcpEnv = buildMcpEnv({ workspaceDir: wsRoot });
                outputChannel.appendLine(`[MCP] RDE: using bundled project at ${bundledToolPath}`);
            } else {
                // Marketplace: prefer pre-installed tool, fallback to uvx
                const [cmd, args, preInstalled] = buildMcpCommand(uvPath, 'research-data-explorer');
                rdeCommand = cmd;
                rdeArgs = args;
                mcpEnv = buildMcpEnv({ workspaceDir: wsRoot });
                if (preInstalled) {
                    outputChannel.appendLine('[MCP] RDE: using pre-installed binary (skipping uvx)');
                }
            }

            // Add automl endpoint and availability from configuration
            const automlEndpoint = vscode.workspace.getConfiguration('rde').get<string>('automlEndpoint');
            if (automlEndpoint) {
                mcpEnv['AUTOML_STAT_MCP_URL'] = automlEndpoint;
            }
            if (automlServiceAvailable) {
                mcpEnv['AUTOML_AVAILABLE'] = '1';
                // Derive stats-service and automl-service URLs
                const baseUrl = automlEndpoint || 'http://localhost:8002';
                mcpEnv['STATS_SERVICE_URL'] = baseUrl.replace(':8002', ':8003');
                mcpEnv['AUTOML_SERVICE_URL'] = baseUrl.replace(':8003', ':8001').replace(':8002', ':8001');
            }

            outputChannel.appendLine(`[MCP] RDE: ${rdeCommand} ${rdeArgs.join(' ')}`);
            definitions.push(new vscode.McpStdioServerDefinition(
                'Research Data Explorer',
                rdeCommand,
                rdeArgs,
                mcpEnv
            ));

            return definitions;
        },

        resolveMcpServerDefinition(
            definition: vscode.McpServerDefinition,
            _token: vscode.CancellationToken
        ): vscode.ProviderResult<vscode.McpServerDefinition> {
            outputChannel.appendLine(`Resolving MCP server: ${definition.label}`);
            return definition;
        }
    };

    return vscode.lm.registerMcpServerDefinitionProvider('rde', provider);
}

// ─── Tool-calling Loop ─────────────────────────────────────────────────────────

async function runWithTools(
    request: vscode.ChatRequest,
    stream: vscode.ChatResponseStream,
    token: vscode.CancellationToken,
    toolFilter?: (tool: vscode.LanguageModelToolInformation) => boolean,
    options?: {
        maxRounds?: number;
        promptOverride?: string;
        requireToolCall?: boolean;
    },
): Promise<void> {
    const maxRounds = options?.maxRounds ?? 5;
    const requireToolCall = options?.requireToolCall ?? true;

    const allTools = vscode.lm.tools;
    const allRdeTools = filterRdeTools(allTools);
    const filtered = filterRdeTools(allTools, toolFilter);

    if (filtered.length === 0) {
        stream.markdown(NO_AVAILABLE_RDE_TOOLS_MESSAGE);
        outputChannel.appendLine('[Tools] No RDE MCP tools available to chat participant.');
        return;
    }
    const missingRequiredTools = findMissingRequiredRdeTools(allRdeTools);
    if (missingRequiredTools.length > 0) {
        stream.markdown(
            `${MISSING_BOOTSTRAP_RDE_TOOLS_MESSAGE}\n\nMissing required tool(s): ${missingRequiredTools.join(', ')}`,
        );
        outputChannel.appendLine(
            `[Tools] RDE MCP tool list missing required bootstrap tools: ${missingRequiredTools.join(', ')}`,
        );
        return;
    }

    const chatTools: vscode.LanguageModelChatTool[] = filtered.map(t => ({
        name: t.name,
        description: t.description,
        inputSchema: t.inputSchema,
    }));

    const messages: vscode.LanguageModelChatMessage[] = [
        vscode.LanguageModelChatMessage.User(options?.promptOverride ?? request.prompt),
    ];

    for (let round = 0; round < maxRounds; round++) {
        const response = await request.model.sendRequest(
            messages,
            { tools: chatTools },
            token,
        );

        const toolCalls: vscode.LanguageModelToolCallPart[] = [];
        const assistantParts: (vscode.LanguageModelTextPart | vscode.LanguageModelToolCallPart)[] = [];
        const bufferedText: string[] = [];

        for await (const chunk of response.stream) {
            if (chunk instanceof vscode.LanguageModelTextPart) {
                bufferedText.push(chunk.value);
                assistantParts.push(chunk);
            } else if (chunk instanceof vscode.LanguageModelToolCallPart) {
                toolCalls.push(chunk);
                assistantParts.push(chunk);
            }
        }

        if (toolCalls.length === 0) {
            const action = getToolCallPolicyAction({
                toolCallCount: toolCalls.length,
                requireToolCall,
                round,
                maxRounds,
            });

            if (action === 'retry') {
                messages.push(vscode.LanguageModelChatMessage.Assistant(assistantParts));
                messages.push(vscode.LanguageModelChatMessage.User(
                    [new vscode.LanguageModelTextPart(buildToolRetryInstruction(filtered.map(tool => tool.name)))],
                ));
                continue;
            }

            if (action === 'reject') {
                stream.markdown(NO_RDE_TOOL_CALL_MESSAGE);
                outputChannel.appendLine('[Tools] Model response did not invoke any RDE MCP tool.');
                return;
            }

            const finalText = bufferedText.join('');
            if (finalText.trim()) {
                stream.markdown(finalText);
            }
            return;
        }

        const interimText = bufferedText.join('');
        if (interimText.trim()) {
            stream.markdown(interimText);
        }

        messages.push(vscode.LanguageModelChatMessage.Assistant(assistantParts));

        const toolResults: (vscode.LanguageModelToolResultPart | vscode.LanguageModelTextPart)[] = [];
        for (const call of toolCalls) {
            try {
                const result = await vscode.lm.invokeTool(call.name, {
                    input: call.input,
                    toolInvocationToken: request.toolInvocationToken,
                }, token);

                const texts = result.content
                    .filter((p): p is vscode.LanguageModelTextPart => p instanceof vscode.LanguageModelTextPart)
                    .map(p => p.value);
                toolResults.push(new vscode.LanguageModelToolResultPart(call.callId, [new vscode.LanguageModelTextPart(texts.join('\n'))]));
            } catch (err) {
                toolResults.push(new vscode.LanguageModelToolResultPart(
                    call.callId,
                    [new vscode.LanguageModelTextPart(`Tool error: ${err instanceof Error ? err.message : String(err)}`)],
                ));
            }
        }

        messages.push(vscode.LanguageModelChatMessage.User(toolResults));
    }
}

// ─── Chat Participant ──────────────────────────────────────────────────────────

/** Tool allowlist helpers — maps chat commands to exact RDE MCP tools only */
const TOOL_FILTERS: Record<string, (t: vscode.LanguageModelToolInformation) => boolean> = {
    explore: t => toolGroupIncludes(TOOL_GROUPS.explore, t.name),
    pipeline: t => toolGroupIncludes(TOOL_GROUPS.pipeline, t.name),
    compare: t => toolGroupIncludes(TOOL_GROUPS.compare, t.name),
    table1: t => toolGroupIncludes(TOOL_GROUPS.table1, t.name),
    advanced: t => toolGroupIncludes(TOOL_GROUPS.advanced, t.name),
    report: t => toolGroupIncludes(TOOL_GROUPS.report, t.name),
    audit: t => toolGroupIncludes(TOOL_GROUPS.audit, t.name),
};

function registerChatParticipant(context: vscode.ExtensionContext): vscode.Disposable | null {
    try {
        const skillsPath = path.join(context.extensionPath, 'skills');

        const handler: vscode.ChatRequestHandler = async (
            request: vscode.ChatRequest,
            _chatContext: vscode.ChatContext,
            stream: vscode.ChatResponseStream,
            token: vscode.CancellationToken
        ) => {
            if (request.command === 'fullreport') {
                const edaSkill = loadSkillContent(skillsPath, 'eda-workflow');
                stream.markdown('📄 **正在使用完整 13-Phase MCP workflow 組裝分析報告…**\n\n');
                await runWithTools(
                    request,
                    stream,
                    token,
                    undefined,
                    {
                        maxRounds: 10,
                        promptOverride: buildPipelineExecutionPrompt(
                            request.prompt || '請完成完整 13-Phase 分析並產出可審計報告。',
                            edaSkill,
                        ),
                    },
                );
                return { metadata: { command: request.command } };
            }

            // Commands that use the tool-calling loop
            const toolCommand = request.command;
            if (toolCommand && toolCommand in TOOL_FILTERS) {
                const icons: Record<string, string> = {
                    explore: '🔍', pipeline: '🔄', compare: '📊',
                    table1: '📋', advanced: '🧪', report: '📄',
                    audit: '🔒',
                };
                stream.markdown(`${icons[toolCommand] || '🔧'} **正在使用 MCP 工具處理您的請求…**\n\n`);
                await runWithTools(request, stream, token, TOOL_FILTERS[toolCommand]);
                return { metadata: { command: toolCommand } };
            }

            switch (request.command) {
                case 'help':
                    stream.markdown('## 📚 Research Data Explorer 完整指令列表\n\n');
                    stream.markdown('### 💬 Chat 指令 (@rde)\n\n');
                    stream.markdown('| 指令 | 說明 |\n');
                    stream.markdown('|------|------|\n');
                    stream.markdown('| `/explore` | 🔍 快速探索資料集概況 |\n');
                    stream.markdown('| `/fullreport` | 📄 從資料到完整分析報告的受治理流程 |\n');
                    stream.markdown('| `/pipeline` | 🔄 查看目前 Pipeline 進度 |\n');
                    stream.markdown('| `/compare` | 📊 比較兩組差異 |\n');
                    stream.markdown('| `/table1` | 📋 產生 Table 1 (基線特徵表) |\n');
                    stream.markdown('| `/advanced` | 🧪 進階統計分析 (PSM, Survival, ROC) |\n');
                    stream.markdown('| `/report` | 📄 組裝與匯出報告 |\n');
                    stream.markdown('| `/audit` | 🔒 審計紀錄與品質檢查 |\n');
                    stream.markdown('| `/help` | 顯示本說明 |\n\n');
                    stream.markdown('### 🔧 Agent Mode 自然語言\n\n');
                    stream.markdown('直接在 Agent Mode 輸入：\n');
                    stream.markdown('- 「我有資料想分析」→ 完整 13-Phase\n');
                    stream.markdown('- 「請幫我完成完整分析報告」→ fullreport\n');
                    stream.markdown('- 「只想看概況」→ Quick Explore\n');
                    stream.markdown('- 「比較兩組差異」→ compare_groups\n');
                    stream.markdown('- 「做 Table 1」→ generate_table_one\n');
                    stream.markdown('- 「跑進階分析」→ run_advanced_analysis\n');
                    stream.markdown('- 「產出報告」→ assemble_report\n');
                    stream.markdown('- 「匯出 Word/PDF」→ export_report\n');
                    break;

                default: {
                    // General query — full pipeline execution
                    const edaSkill = loadSkillContent(skillsPath, 'eda-workflow');
                    stream.markdown('🔧 **正在使用 MCP 工具處理您的請求…**\n\n');
                    await runWithTools(
                        request,
                        stream,
                        token,
                        undefined,
                        {
                            maxRounds: 10,
                            promptOverride: buildPipelineExecutionPrompt(request.prompt, edaSkill),
                        },
                    );
                }
            }

            return { metadata: { command: request.command } };
        };

        const participant = vscode.chat.createChatParticipant('rde.assistant', handler);
        participant.iconPath = vscode.Uri.joinPath(context.extensionUri, 'media', 'icon.png');

        participant.followupProvider = {
            provideFollowups(_result, _context, _token) {
                return [
                    { prompt: '完整分析到報告', label: '📄 Full Report', command: 'fullreport' },
                    { prompt: '快速探索資料', label: '🔍 Quick Explore', command: 'explore' },
                    { prompt: '比較兩組差異', label: '📊 Compare Groups', command: 'compare' },
                    { prompt: '產生 Table 1', label: '📋 Table 1', command: 'table1' },
                    { prompt: '匯出報告', label: '📄 Export Report', command: 'report' },
                ];
            }
        };

        return participant;
    } catch (error) {
        outputChannel.appendLine(`Chat participant registration skipped: ${error}`);
        return null;
    }
}

// ─── Helpers ───────────────────────────────────────────────────────────────────

function getPythonPath(context: vscode.ExtensionContext): string {
    const config = vscode.workspace.getConfiguration('rde');
    const configuredPath = config.get<string>('pythonPath');
    const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

    return determinePythonPath({
        configuredPath: configuredPath || undefined,
        wsRoot,
        extensionPath: context.extensionPath,
    });
}

async function configureCodexMcp(
    context: vscode.ExtensionContext,
    silent: boolean,
): Promise<void> {
    const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!wsRoot) {
        if (!silent) {
            vscode.window.showWarningMessage('Open a workspace before configuring Codex for RDE.');
        }
        return;
    }

    const bundledToolPath = path.join(context.extensionPath, 'bundled', 'tool');
    const projectPath = checkIsDevWorkspace(wsRoot)
        ? wsRoot
        : (isBundledToolProject(bundledToolPath) ? bundledToolPath : undefined);

    if (!projectPath) {
        const message = 'RDE bundled tool project was not found; Codex MCP config was not changed.';
        outputChannel.appendLine(`[Codex] ${message}`);
        if (!silent) {
            vscode.window.showWarningMessage(message);
        }
        return;
    }

    try {
        const uvPath = resolvedUvPath || context.globalState.get<string>('uvPath') || 'uv';
        const result = configureCodexRdeMcpConfigFile(
            codexConfigPath(),
            {
                command: uvPath,
                projectPath,
                workspacePath: wsRoot,
            },
        );
        outputChannel.appendLine(
            `[Codex] ${result.changed ? 'Updated' : 'Already configured'} ${result.configPath}`,
        );
        if (!silent) {
            vscode.window.showInformationMessage(
                result.changed
                    ? 'Codex MCP config updated for Research Data Explorer.'
                    : 'Codex MCP config already points to Research Data Explorer.',
            );
        }
    } catch (error) {
        const message = `Failed to configure Codex MCP: ${error instanceof Error ? error.message : String(error)}`;
        outputChannel.appendLine(`[Codex] ${message}`);
        if (!silent) {
            vscode.window.showErrorMessage(message);
        }
    }
}

// ─── Auto-scaffold ─────────────────────────────────────────────────────────────

async function autoScaffoldIfNeeded(context: vscode.ExtensionContext): Promise<void> {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
        return;
    }

    const wsRoot = workspaceFolders[0].uri.fsPath;
    const extPath = context.extensionPath;

    const {
        missingSkills,
        missingAgents,
        missingPrompts,
        missingCodexSkills,
        missingClineRules,
        missingCodexInstructions,
        total: totalMissing,
    } = countMissingBundledItems(
        wsRoot,
        extPath,
        BUNDLED_SKILLS,
        BUNDLED_AGENTS,
        BUNDLED_PROMPTS,
        BUNDLED_SKILLS,
        BUNDLED_CLINE_RULES,
        true,
    );

    if (totalMissing === 0) {
        outputChannel.appendLine('[AutoScaffold] Workspace already has all skills/agents/prompts.');
        return;
    }

    const stateKey = `rde.scaffolded.${wsRoot}`;
    const alreadyPrompted = context.globalState.get<boolean>(stateKey);

    if (alreadyPrompted) {
        outputChannel.appendLine(`[AutoScaffold] Already prompted for this workspace (${totalMissing} items missing).`);
        return;
    }

    const detail: string[] = [];
    if (missingSkills > 0) { detail.push(`${missingSkills} skills`); }
    if (missingAgents > 0) { detail.push(`${missingAgents} agents`); }
    if (missingPrompts > 0) { detail.push(`${missingPrompts} prompts`); }
    if (missingCodexSkills > 0) { detail.push(`${missingCodexSkills} Codex skills`); }
    if (missingClineRules > 0) { detail.push(`${missingClineRules} Cline rules`); }
    if (missingCodexInstructions > 0) { detail.push('Codex AGENTS.md'); }

    const selection = await vscode.window.showInformationMessage(
        `RDE: 偵測到 workspace 缺少 ${detail.join('、')}。要設定嗎？`,
        '設定 Workspace',
        '稍後再說',
        '不再提醒'
    );

    if (selection === '設定 Workspace') {
        await setupWorkspace(context);
    } else if (selection === '不再提醒') {
        await context.globalState.update(stateKey, true);
    }
}

async function setupWorkspace(context: vscode.ExtensionContext): Promise<void> {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
        vscode.window.showErrorMessage('請先開啟一個 workspace 資料夾。');
        return;
    }

    const wsRoot = workspaceFolders[0].uri.fsPath;
    const extPath = context.extensionPath;
    let copied = 0;

    // 1. Copy skills → .claude/skills/
    for (const skill of BUNDLED_SKILLS) {
        const src = path.join(extPath, 'skills', skill, 'SKILL.md');
        const dst = path.join(wsRoot, '.claude', 'skills', skill, 'SKILL.md');
        if (fs.existsSync(src) && !fs.existsSync(dst)) {
            fs.mkdirSync(path.dirname(dst), { recursive: true });
            fs.copyFileSync(src, dst);
            copied++;
        }
    }

    // 2. Copy Codex skills → .codex/skills/
    for (const skill of BUNDLED_SKILLS) {
        const src = path.join(extPath, 'skills', skill, 'SKILL.md');
        const dst = path.join(wsRoot, '.codex', 'skills', skill, 'SKILL.md');
        if (fs.existsSync(src) && !fs.existsSync(dst)) {
            fs.mkdirSync(path.dirname(dst), { recursive: true });
            fs.copyFileSync(src, dst);
            copied++;
        }
    }

    // 3. Copy prompts → .github/prompts/
    for (const prompt of BUNDLED_PROMPTS) {
        const src = path.join(extPath, 'prompts', `${prompt}.prompt.md`);
        const dst = path.join(wsRoot, '.github', 'prompts', `${prompt}.prompt.md`);
        if (fs.existsSync(src) && !fs.existsSync(dst)) {
            fs.mkdirSync(path.dirname(dst), { recursive: true });
            fs.copyFileSync(src, dst);
            copied++;
        }
    }

    // 4. Copy agents → .github/agents/
    for (const agent of BUNDLED_AGENTS) {
        const src = path.join(extPath, 'agents', `${agent}.agent.md`);
        const dst = path.join(wsRoot, '.github', 'agents', `${agent}.agent.md`);
        if (fs.existsSync(src) && !fs.existsSync(dst)) {
            fs.mkdirSync(path.dirname(dst), { recursive: true });
            fs.copyFileSync(src, dst);
            copied++;
        }
    }

    // 5. Copy Cline rules → .clinerules/
    for (const rule of BUNDLED_CLINE_RULES) {
        const src = path.join(extPath, 'clinerules', rule);
        const dst = path.join(wsRoot, '.clinerules', rule);
        if (fs.existsSync(src) && !fs.existsSync(dst)) {
            fs.mkdirSync(path.dirname(dst), { recursive: true });
            fs.copyFileSync(src, dst);
            copied++;
        }
    }

    // 6. Copy copilot-instructions.md (only if not exists)
    const instrSrc = path.join(extPath, 'copilot-instructions.md');
    const instrDst = path.join(wsRoot, '.github', 'copilot-instructions.md');
    if (fs.existsSync(instrSrc) && !fs.existsSync(instrDst)) {
        fs.mkdirSync(path.dirname(instrDst), { recursive: true });
        fs.copyFileSync(instrSrc, instrDst);
        copied++;
    }

    // 7. Copy Codex AGENTS.md (only if not exists)
    const codexInstrSrc = path.join(extPath, 'AGENTS.md');
    const codexInstrDst = path.join(wsRoot, 'AGENTS.md');
    if (fs.existsSync(codexInstrSrc) && !fs.existsSync(codexInstrDst)) {
        fs.copyFileSync(codexInstrSrc, codexInstrDst);
        copied++;
    }

    if (copied > 0) {
        vscode.window.showInformationMessage(
            `RDE: 已設定 ${copied} 個檔案（skills、prompts、agents、instructions）到 workspace。重新載入視窗以啟用全部功能。`,
            '重新載入'
        ).then(selection => {
            if (selection === '重新載入') {
                vscode.commands.executeCommand('workbench.action.reloadWindow');
            }
        });
    } else {
        vscode.window.showInformationMessage('RDE: Workspace 已是最新，無需更新。');
    }

    await configureCodexMcp(context, true);
    outputChannel.appendLine(`[Setup] Copied ${copied} files to workspace`);
}

export function deactivate() {
    outputChannel?.appendLine('Research Data Explorer deactivated.');
}
