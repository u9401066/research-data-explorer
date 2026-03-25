import { describe, expect, it } from 'vitest';

import {
    FULL_REPORT_CHAT_QUERY,
    NO_RDE_TOOL_CALL_MESSAGE,
    RDE_MCP_TOOL_NAMES,
    TOOL_GROUPS,
    buildPipelineExecutionPrompt,
    buildToolRetryInstruction,
    filterRdeTools,
    getToolCallPolicyAction,
} from '../src/toolPolicy';

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
        expect(prompt).toContain('compare_groups');
        expect(prompt).toContain('verify_audit_trail');
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
