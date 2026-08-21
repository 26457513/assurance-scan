// One shape for every copy-paste agent prompt in the UI: a concrete MCP
// get_workflow call with the parameters the page already knows, plus an
// optional one-line follow-up. Keep prompts to this form — no essays.

export function workflowCallPrompt(
  name: string,
  params: Record<string, string>,
  followup = ''
): string {
  const json = JSON.stringify(params);
  return [
    `Call the assurance-scan MCP tool \`get_workflow\` with name="${name}" and parameters=${json}, then follow the returned workflow prompt.`,
    followup
  ]
    .filter(Boolean)
    .join(' ');
}
