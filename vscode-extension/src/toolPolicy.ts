export const RDE_MCP_TOOL_NAMES = [
    'init_project',
    'get_pipeline_status',
    'get_decision_log',
    'get_deviation_log',
    'log_deviation',
    'scan_data_folder',
    'load_dataset',
    'run_intake',
    'build_schema',
    'profile_dataset',
    'assess_quality',
    'align_concept',
    'propose_analysis_plan',
    'register_analysis_plan',
    'check_readiness',
    'suggest_cleaning',
    'apply_cleaning',
    'analyze_variable',
    'compare_groups',
    'correlation_matrix',
    'generate_table_one',
    'run_advanced_analysis',
    'run_repeated_measures',
    'collect_results',
    'assemble_report',
    'create_visualization',
    'export_report',
    'run_audit',
    'auto_improve',
    'export_final_report',
    'export_handoff',
    'verify_audit_trail',
] as const;

export const TOOL_GROUPS = {
    explore: [
        'init_project',
        'get_pipeline_status',
        'scan_data_folder',
        'run_intake',
        'load_dataset',
        'build_schema',
        'profile_dataset',
        'assess_quality',
    ],
    pipeline: [
        'init_project',
        'get_pipeline_status',
        'align_concept',
        'propose_analysis_plan',
        'register_analysis_plan',
        'check_readiness',
        'get_decision_log',
        'get_deviation_log',
    ],
    compare: [
        'get_pipeline_status',
        'check_readiness',
        'compare_groups',
        'analyze_variable',
        'log_deviation',
    ],
    table1: [
        'get_pipeline_status',
        'check_readiness',
        'generate_table_one',
    ],
    advanced: [
        'get_pipeline_status',
        'check_readiness',
        'run_advanced_analysis',
        'run_repeated_measures',
        'log_deviation',
    ],
    report: [
        'collect_results',
        'assemble_report',
        'create_visualization',
        'export_report',
        'export_final_report',
        'export_handoff',
    ],
    audit: [
        'get_pipeline_status',
        'get_decision_log',
        'get_deviation_log',
        'run_audit',
        'auto_improve',
        'export_final_report',
        'verify_audit_trail',
        'log_deviation',
    ],
} as const;

const RDE_MCP_TOOL_NAME_SET = new Set<string>(RDE_MCP_TOOL_NAMES);

export const NO_AVAILABLE_RDE_TOOLS_MESSAGE =
    '⚠️ 目前沒有可用的 RDE MCP 工具。請先確認 MCP server 已註冊並可被 Copilot 看到。';

export const NO_RDE_TOOL_CALL_MESSAGE =
    '⚠️ 本次回應沒有呼叫任何 RDE MCP 工具，因此未執行受治理的 EDA 流程。請確認 MCP server 可用後再試。';

export const FULL_REPORT_CHAT_QUERY =
    '@rde /fullreport 請使用完整 13-Phase auditable workflow，從專案建立、資料收件、raw structure gate、schema、concept alignment、greedy plan proposal、plan completeness review、plan lock、readiness、分析、collect_results、assemble_report、run_audit 到 auto_improve/export_final_report，產出完整分析報告。';

export interface ToolInfoLike {
    name: string;
}

export function isRdeToolName(name: string): boolean {
    return RDE_MCP_TOOL_NAME_SET.has(name);
}

export function isRdeMcpTool(tool: ToolInfoLike): boolean {
    return isRdeToolName(tool.name);
}

export function filterRdeTools<T extends ToolInfoLike>(
    tools: readonly T[],
    toolFilter?: (tool: T) => boolean,
): T[] {
    return tools.filter(tool => isRdeMcpTool(tool) && (!toolFilter || toolFilter(tool)));
}

export function toolGroupIncludes(group: readonly string[], toolName: string): boolean {
    return group.includes(toolName);
}

export function getToolCallPolicyAction(options: {
    toolCallCount: number;
    requireToolCall: boolean;
    round: number;
    maxRounds: number;
}): 'accept' | 'retry' | 'reject' {
    if (!options.requireToolCall || options.toolCallCount > 0) {
        return 'accept';
    }
    return options.round < options.maxRounds - 1 ? 'retry' : 'reject';
}

export function buildToolRetryInstruction(
    allowedTools: readonly string[] = RDE_MCP_TOOL_NAMES,
): string {
    return [
        'You must invoke at least one RDE MCP tool from this allowlist before answering.',
        `Allowed tools: ${allowedTools.join(', ')}`,
        'Do not use non-RDE tools, do not write code, and do not answer from prior knowledge alone.',
        'If execution is blocked, explain the blocker only after attempting tool use.',
    ].join('\n');
}

export function buildPipelineExecutionPrompt(userPrompt: string, edaSkill: string | null): string {
    const preamble = [
        'You are executing the RDE 13-Phase Auditable EDA Pipeline through MCP tools.',
        'This is an execution request, not a documentation request.',
        'You may only use RDE MCP tools. Do not use generic workspace, code, file, terminal, or search tools to perform the analysis.',
        '',
        'Mandatory execution rules:',
        '1. Start by understanding current project state and pipeline status using get_pipeline_status() or init_project() when no project exists.',
        '2. Follow the 13-Phase Pipeline: Setup → Intake → Schema → Concept → Creative Ideation → Plan Completeness Review → Plan Registration → Pre-check → Execute → Collect → Report → Audit → Improve.',
        '3. Respect Hard Constraints (H-001 to H-010): file size, format, sample size, PII, artifact gate, plan lock, etc.',
        '4. Note Soft Constraints (S-001 to S-012): normality, multiple comparisons, sensitivity analysis, etc.',
        '5. All Phase 8 analysis decisions are automatically logged (H-009).',
        '6. If the user wants autonomous EDA or did not specify a precise Phase 4 analysis list, call propose_analysis_plan() after Phase 3 to generate a greedy blueprint before plan lock.',
        '7. If Phase 3 or Phase 4 needs confirmation, stop and ask through the tool result rather than guessing.',
        '8. If the request cannot be completed with an RDE MCP tool, report the blocker instead of answering from general knowledge.',
        '9. Never write code, edit files, or inspect the workspace as a substitute for using the RDE MCP workflow.',
        '',
        `Allowed RDE MCP tools: ${Array.from(RDE_MCP_TOOL_NAMES).join(', ')}`,
        '',
        'User request:',
        userPrompt,
    ].join('\n');

    if (!edaSkill) {
        return preamble;
    }

    return [preamble, '', 'Reference workflow instructions:', edaSkill].join('\n');
}
