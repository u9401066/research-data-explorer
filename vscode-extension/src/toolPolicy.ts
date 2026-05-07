const PHASE_08_AUTONOMOUS_BRANCH_TOOL_NAMES = [
    'open_exploration_branch',
    'suggest_branch_experiments',
    'start_autoresearch_run',
    'get_autoresearch_status',
    'stop_autoresearch_run',
    'resume_autoresearch_run',
    'run_autoresearch_next_task',
    'run_autoresearch_queue',
    'run_branch_experiment',
    'evaluate_branch',
    'discard_branch',
    'get_exploration_board',
] as const;

const PHASE_08_BRANCH_PROMOTION_TOOL_NAMES = [
    'promote_branch_to_plan_amendment',
] as const;

export const RDE_MCP_TOOL_NAMES = [
    'init_project',
    'get_pipeline_status',
    'get_decision_log',
    'get_deviation_log',
    'log_deviation',
    'get_approval_card',
    'get_harness_dashboard',
    'build_artifact_index',
    'get_blocker_playbook',
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
    ...PHASE_08_AUTONOMOUS_BRANCH_TOOL_NAMES,
    ...PHASE_08_BRANCH_PROMOTION_TOOL_NAMES,
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

const WORKFLOW_PREREQUISITE_TOOLS = [
    'init_project',
    'get_pipeline_status',
    'scan_data_folder',
    'run_intake',
    'load_dataset',
    'build_schema',
    'align_concept',
    'propose_analysis_plan',
    'register_analysis_plan',
    'check_readiness',
] as const;

export const TOOL_GROUPS = {
    explore: [
        'init_project',
        'get_pipeline_status',
        'get_harness_dashboard',
        'build_artifact_index',
        'scan_data_folder',
        'run_intake',
        'load_dataset',
        'build_schema',
        'profile_dataset',
        'assess_quality',
        'assemble_report',
        'export_report',
    ],
    pipeline: [
        ...WORKFLOW_PREREQUISITE_TOOLS,
        'get_approval_card',
        'get_harness_dashboard',
        'build_artifact_index',
        'get_blocker_playbook',
        'get_decision_log',
        'get_deviation_log',
        ...PHASE_08_AUTONOMOUS_BRANCH_TOOL_NAMES,
        ...PHASE_08_BRANCH_PROMOTION_TOOL_NAMES,
    ],
    compare: [
        ...WORKFLOW_PREREQUISITE_TOOLS,
        'compare_groups',
        'analyze_variable',
        ...PHASE_08_AUTONOMOUS_BRANCH_TOOL_NAMES,
        'log_deviation',
    ],
    table1: [
        ...WORKFLOW_PREREQUISITE_TOOLS,
        'generate_table_one',
        ...PHASE_08_AUTONOMOUS_BRANCH_TOOL_NAMES,
    ],
    advanced: [
        ...WORKFLOW_PREREQUISITE_TOOLS,
        'run_advanced_analysis',
        'run_repeated_measures',
        ...PHASE_08_AUTONOMOUS_BRANCH_TOOL_NAMES,
        'log_deviation',
    ],
    report: [
        ...WORKFLOW_PREREQUISITE_TOOLS,
        'collect_results',
        'assemble_report',
        'get_approval_card',
        'get_harness_dashboard',
        'build_artifact_index',
        'get_blocker_playbook',
        'create_visualization',
        'export_report',
        'export_final_report',
        'export_handoff',
    ],
    audit: [
        ...WORKFLOW_PREREQUISITE_TOOLS,
        'get_approval_card',
        'get_harness_dashboard',
        'build_artifact_index',
        'get_blocker_playbook',
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

export const BOOTSTRAP_REQUIRED_RDE_TOOL_NAMES = [
    'init_project',
] as const;

export const MISSING_BOOTSTRAP_RDE_TOOLS_MESSAGE =
    'RDE MCP tool list is incomplete: init_project is missing. Restart the RDE MCP server or reload VS Code before running the pipeline.';

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

export function findMissingRequiredRdeTools(
    tools: readonly ToolInfoLike[],
    requiredTools: readonly string[] = BOOTSTRAP_REQUIRED_RDE_TOOL_NAMES,
): string[] {
    const available = new Set(tools.map(tool => tool.name));
    return requiredTools.filter(toolName => !available.has(toolName));
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
        '1. If no project_id or active project exists, call init_project() first. Use get_pipeline_status(project_id=...) only after a project exists or when checking a known project.',
        '2. Follow the 13-Phase Pipeline: Setup → Intake → Schema → Concept → Creative Ideation → Plan Completeness Review → Plan Registration → Pre-check → Execute → Collect → Report → Audit → Improve.',
        '3. Respect Hard Constraints (H-001 to H-010): file size, format, sample size, PII, artifact gate, plan lock, etc.',
        '4. Note Soft Constraints (S-001 to S-012): normality, multiple comparisons, sensitivity analysis, etc.',
        '5. All Phase 8 analysis decisions are automatically logged (H-009).',
        '6. If the user wants autonomous EDA or did not specify a precise Phase 4 analysis list, Phase 4 is a two-step confirmation gate: call propose_analysis_plan(confirm=false) after Phase 3 user confirmation to generate the greedy blueprint/review artifacts, show those artifacts to the user, then call propose_analysis_plan(confirm=true) only after the user confirms them.',
        '7. Confirmation gates are mandatory: Phase 3 concept alignment requires user confirmation; Phase 4 creative ideation requires user confirmation; the combined Phase 5+6 plan review and lock requires user confirmation.',
        '8. If Phase 3, Phase 4, or combined Phase 5+6 needs confirmation, stop and ask through the tool result rather than guessing.',
        '9. Phase 8 may run autonomous YOLO exploration branches with start_autoresearch_run(), get_autoresearch_status(), stop_autoresearch_run(), resume_autoresearch_run(), run_autoresearch_next_task(), run_autoresearch_queue(), open_exploration_branch(), suggest_branch_experiments(), run_branch_experiment(), evaluate_branch(), discard_branch(), and get_exploration_board(); branch outputs stay branch-scoped artifacts and do not change primary conclusions.',
        '10. Branch promotion is never automatic: promote_branch_to_plan_amendment(confirm=true) requires an evaluate_branch() audit gate and explicit user confirmation before any plan amendment or primary conclusion uses it.',
        '11. Use UX harness tools when the user needs no-code guidance: get_approval_card(), get_harness_dashboard(), build_artifact_index(), and get_blocker_playbook().',
        '12. If the request cannot be completed with an RDE MCP tool, report the blocker instead of answering from general knowledge.',
        '13. Never write code, edit files, or inspect the workspace as a substitute for using the RDE MCP workflow.',
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
