// Companion permission bridge — an opencode plugin.
//
// Gates mutating tool calls (edits + shell, including the hashline MCP tools)
// by asking the desktop companion before they run. The companion shows an
// Allow/Deny bubble; this hook blocks until the answer, so the agent's flow
// pauses and then continues (or the tool is denied) — never silently bypassed.
//
// Inert unless COMPANION_PERMS_URL is set, so normal opencode usage (TUI / plain
// CLI, not launched by the companion) is completely unaffected.

const GATED = new Set([
  "bash", "edit", "write", "patch",
  "hashline_edit", "hashline_write",
]);

function isGated(tool) {
  if (!tool) return false;
  if (GATED.has(tool)) return true;
  // any MCP tool that edits/writes (e.g. <server>_edit, <server>_write)
  return tool.endsWith("_edit") || tool.endsWith("_write");
}

export const PermissionBridge = async (_ctx) => {
  return {
    "tool.execute.before": async (input, output) => {
      const url = process.env.COMPANION_PERMS_URL;
      if (!url) return;                       // not driven by the companion → allow
      if (!isGated(input.tool)) return;       // reads / search / web → allow

      // ask the companion; block until it answers. Fail closed on any error.
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 180000); // 3 min
      let decision = "deny";
      try {
        const res = await fetch(url + "/ask", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            tool: input.tool,
            args: output && output.args,
            sessionID: input.sessionID,
            callID: input.callID,
          }),
          signal: ctrl.signal,
        });
        if (res.ok) {
          const data = await res.json();
          decision = data && data.decision;
        }
      } catch (_e) {
        decision = "deny";
      } finally {
        clearTimeout(timer);
      }

      if (decision !== "allow") {
        throw new Error("Permission denied by the companion.");
      }
    },
  };
};
