import { describe, expect, it } from 'vitest';

import {
    FULL_REPORT_CHAT_QUERY,
    MISSING_BOOTSTRAP_RDE_TOOLS_MESSAGE,
    NO_RDE_TOOL_CALL_MESSAGE,
    RDE_MCP_TOOL_NAMES,
    TOOL_GROUPS,
    buildPipelineExecutionPrompt,
    buildToolRetryInstruction,
    filterRdeTools,
    findMissingRequiredRdeTools,
    getToolCallPolicyAction,
    toolGroupIncludes,
} from '../src/toolPolicy';

const BRANCH_TOOL_NAMES = [
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
    'promote_branch_to_plan_amendment',
    'discard_branch',
    'get_exploration_board',
] as const;

const AUTONOMOUS_BRANCH_TOOL_NAMES = [
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

const UX_HARNESS_TOOL_NAMES = [
    'get_approval_card',
    'get_harness_dashboard',
    'build_artifact_index',
    'get_blocker_playbook',
] as const;

describe('toolPolicy', () => {
    it('filters to exact RDE MCP tools only', () => {
        const filtered = filterRdeTools([
            { name: 'init_project' },
            { name: 'search' },
            { name: 'compare_groups' },
            { name: 'runCommands' },
        ]);

        expect(filtered.map(tool => tool.name)).toEqual(['init_project', 'compare_groups']);
    });

    it('ensures all grouped tools come from the RDE allowlist', () => {
        const allowed = new Set(RDE_MCP_TOOL_NAMES);

        for (const group of Object.values(TOOL_GROUPS)) {
            expect(group.every(toolName => allowed.has(toolName))).toBe(true);
        }
    });

    it('keeps governed workflow commands bootstrapped through readiness prerequisites', () => {
        const prerequisiteTools = [
            'init_project',
            'scan_data_folder',
            'run_intake',
            'load_dataset',
            'build_schema',
            'align_concept',
            'propose_analysis_plan',
            'register_analysis_plan',
            'check_readiness',
        ];

        for (const command of ['pipeline', 'compare', 'table1', 'advanced'] as const) {
            expect(TOOL_GROUPS[command]).toEqual(expect.arrayContaining(prerequisiteTools));
        }
    });

    it('keeps init_project visible after command-level tool filtering', () => {
        const allTools = RDE_MCP_TOOL_NAMES.map(name => ({ name }));

        for (const command of [
            'explore',
            'pipeline',
            'compare',
            'table1',
            'advanced',
            'report',
            'audit',
        ] as const) {
            const filtered = filterRdeTools(
                allTools,
                tool => toolGroupIncludes(TOOL_GROUPS[command], tool.name),
            ).map(tool => tool.name);

            expect(filtered).toContain('init_project');
            expect(filtered).toContain('build_schema');
        }
    });

    it('detects partial live RDE tool lists that are missing bootstrap tools', () => {
        const partialLiveTools = [
            { name: 'run_intake' },
            { name: 'build_schema' },
            { name: 'align_concept' },
        ];
        const filtered = filterRdeTools(
            partialLiveTools,
            tool => toolGroupIncludes(TOOL_GROUPS.pipeline, tool.name),
        );

        expect(filtered.map(tool => tool.name)).not.toContain('init_project');
        expect(findMissingRequiredRdeTools(filtered)).toEqual(['init_project']);
        expect(MISSING_BOOTSTRAP_RDE_TOOLS_MESSAGE).toContain('init_project');
        expect(MISSING_BOOTSTRAP_RDE_TOOLS_MESSAGE).toContain('reload VS Code');
    });

    it('includes Phase 8 exploration branch loop tools in the RDE allowlist', () => {
        expect(RDE_MCP_TOOL_NAMES).toEqual(expect.arrayContaining([...BRANCH_TOOL_NAMES]));
    });

    it('includes no-code UX harness tools in the RDE allowlist and governed workflows', () => {
        expect(RDE_MCP_TOOL_NAMES).toEqual(expect.arrayContaining([...UX_HARNESS_TOOL_NAMES]));
        for (const command of ['pipeline', 'report', 'audit'] as const) {
            expect(TOOL_GROUPS[command]).toEqual(expect.arrayContaining([...UX_HARNESS_TOOL_NAMES]));
        }
    });

    it('allows autonomous branch tools in analysis workflows and scopes promotion to governed flows', () => {
        for (const command of ['pipeline', 'compare', 'table1', 'advanced'] as const) {
            expect(TOOL_GROUPS[command]).toEqual(expect.arrayContaining([...AUTONOMOUS_BRANCH_TOOL_NAMES]));
        }

        expect(TOOL_GROUPS.pipeline).toContain('promote_branch_to_plan_amendment');
        expect(TOOL_GROUPS.advanced).not.toContain('promote_branch_to_plan_amendment');
        expect(TOOL_GROUPS.compare).not.toContain('promote_branch_to_plan_amendment');
        expect(TOOL_GROUPS.table1).not.toContain('promote_branch_to_plan_amendment');
    });

    it('allows quick explore to assemble and export a not-audited quick report', () => {
        expect(TOOL_GROUPS.explore).toEqual(expect.arrayContaining([
            'assemble_report',
            'export_report',
        ]));
    });

    it('retries before rejecting when no tool call occurs', () => {
        expect(getToolCallPolicyAction({
            toolCallCount: 0,
            requireToolCall: true,
            round: 0,
            maxRounds: 3,
        })).toBe('retry');

        expect(getToolCallPolicyAction({
            toolCallCount: 0,
            requireToolCall: true,
            round: 2,
            maxRounds: 3,
        })).toBe('reject');

        expect(getToolCallPolicyAction({
            toolCallCount: 1,
            requireToolCall: true,
            round: 0,
            maxRounds: 3,
        })).toBe('accept');
    });

    it('builds retry instructions and blocker text around the active allowlist', () => {
        const retryPrompt = buildToolRetryInstruction(['init_project', 'check_readiness']);

        expect(retryPrompt).toContain('Allowed tools: init_project, check_readiness');
        expect(NO_RDE_TOOL_CALL_MESSAGE).toContain('沒有呼叫任何 RDE MCP 工具');
    });

    it('builds a guarded execution prompt with current tool names', () => {
        const prompt = buildPipelineExecutionPrompt('比較兩組差異', 'SKILL-CONTENT');

        expect(prompt).toContain('You may only use RDE MCP tools.');
        expect(prompt).toContain('Allowed RDE MCP tools:');
        expect(prompt).toContain('call init_project() first');
        expect(prompt).toContain('compare_groups');
        expect(prompt).toContain('verify_audit_trail');
        expect(prompt).toContain('Phase 3 concept alignment requires user confirmation');
        expect(prompt).toContain('Phase 4 is a two-step confirmation gate');
        expect(prompt).toContain('propose_analysis_plan(confirm=false)');
        expect(prompt).toContain('propose_analysis_plan(confirm=true)');
        expect(prompt).toContain('combined Phase 5+6 plan review and lock requires user confirmation');
        expect(prompt).toContain('Phase 8 may run autonomous YOLO exploration branches');
        expect(prompt).toContain('start_autoresearch_run()');
        expect(prompt).toContain('get_autoresearch_status()');
        expect(prompt).toContain('stop_autoresearch_run()');
        expect(prompt).toContain('resume_autoresearch_run()');
        expect(prompt).toContain('run_autoresearch_next_task()');
        expect(prompt).toContain('run_autoresearch_queue()');
        expect(prompt).toContain('promote_branch_to_plan_amendment(confirm=true)');
        expect(prompt).toContain('get_approval_card()');
        expect(prompt).toContain('get_harness_dashboard()');
        expect(prompt).toContain('build_artifact_index()');
        expect(prompt).toContain('get_blocker_playbook()');
        expect(prompt).toContain('audit gate');
        expect(prompt).toContain('Reference workflow instructions:');
        expect(prompt).toContain('SKILL-CONTENT');
    });

    it('uses a dedicated full-report chat query instead of the status-only pipeline command', () => {
        expect(FULL_REPORT_CHAT_QUERY).toContain('@rde /fullreport');
        expect(FULL_REPORT_CHAT_QUERY).toContain('assemble_report');
        expect(FULL_REPORT_CHAT_QUERY).toContain('run_audit');
        expect(FULL_REPORT_CHAT_QUERY).not.toContain('/pipeline');
    });
});
