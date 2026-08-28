// Every copy-paste agent prompt in the UI is the same machine-readable
// shape: one lead line plus a JSON call plan against the MCP server.

export interface McpCall {
  tool: string;
  args: Record<string, unknown>;
  note?: string;
}

export function mcpPrompt(calls: McpCall[]): string {
  const plan = JSON.stringify({ mcp: 'assurance-scan', calls }, null, 2);
  return `Run these calls against the assurance-scan MCP server, following each tool's returned guidance:\n${plan}`;
}
