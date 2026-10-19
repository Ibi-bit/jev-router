import { Plugin } from "@opencode/plugin"
import { execFile } from "node:child_process"
import os from "node:os"
import path from "node:path"
import { promisify } from "node:util"

const run = promisify(execFile)
const router = process.env.JEV_ROUTER ?? path.join(os.homedir(), "jev-router", "router.py")

interface Usage {
  model?: string
  tokens?: {
    input?: number
    output?: number
    reasoning?: number
    cache?: { read?: number; write?: number }
  }
  cost?: number
}

/** Fetch the most recent assistant message's usage for a session. */
async function lastUsage(sessionID: string): Promise<Usage | null> {
  try {
    const { stdout } = await run("opencode", [
      "api", "get",
      `/api/session/${sessionID}/message?limit=6&order=desc`,
    ], { timeout: 15_000 })
    const messages = JSON.parse(stdout).data ?? []
    for (const message of messages) {
      if (message.type === "assistant" && message.tokens) return message as Usage
    }
  } catch {
    // usage logging is best-effort; never block the prompt
  }
  return null
}

/** True while a subagent prompt is being submitted, so its own hook skips routing. */
let subagentPending = false

/** Best-effort: append the previous call's usage to routing-log.jsonl. */
async function logUsage(sessionID: string) {
  const usage = await lastUsage(sessionID)
  if (!usage?.tokens) return
  try {
    await run("python3", [router, "--log-usage", JSON.stringify({
      sessionID,
      model: usage.model,
      tokens: usage.tokens,
      cost: usage.cost,
    })], { timeout: 10_000 })
  } catch {
    // ignore
  }
}

export default Plugin.define({
  id: "wriggle.jev-router",
  async setup(ctx) {
    const skillsDir = path.join(ctx.location.directory, ".opencode", "skills")
    await ctx.session.hook("prompt", async (event) => {
      if (subagentPending) return // a subagent session's prompt must not route again
      try {
        await logUsage(event.sessionID)
        const usage = await lastUsage(event.sessionID)
        const tokens = usage?.tokens
        const sessionTokens = tokens
          ? (tokens.input ?? 0) + (tokens.cache?.read ?? 0) + (tokens.cache?.write ?? 0)
          : 0
        const args = ["python3", router, "--json", "--skills-dir", skillsDir,
          "--session-tokens", String(sessionTokens)]
        if (usage?.model) args.push("--session-model", usage.model)
        args.push(event.prompt.text)
        const { stdout } = await run(args[0], args.slice(1), { timeout: 60_000 })
        const decision = JSON.parse(stdout)
        const [providerID, ...id] = decision.model.split("/")

        if (decision.mode === "subagent" && decision.subagent_prompt) {
          // Fresh context: the subagent sees only the question, its answer joins the session.
          const [subProviderID, ...subID] = decision.model.split("/")
          const created = await ctx.session.create({ title: "jev-router subagent" })
          await ctx.session.switchModel({
            sessionID: created.id,
            model: { providerID: subProviderID, id: subID.join("/") },
          })
          const answered = async () => {
            subagentPending = true
            try {
              await ctx.session.prompt({ sessionID: created.id, text: decision.subagent_prompt })
              await ctx.session.wait({ sessionID: created.id })
            } finally {
              subagentPending = false
            }
            const messages = await ctx.session.context({ sessionID: created.id })
            for (let i = messages.length - 1; i >= 0; i--) {
              const m = messages[i] as { type?: string; tokens?: Usage["tokens"]; cost?: number; content?: unknown }
              if (m.type !== "assistant") continue
              if (m.tokens) {
                await run("python3", [router, "--log-usage", JSON.stringify({
                  sessionID: created.id,
                  model: { id: decision.model.replace(/^openrouter\//, ""), providerID: "openrouter" },
                  tokens: m.tokens,
                  cost: m.cost,
                })], { timeout: 10_000 }).catch(() => {})
              }
              const text = typeof m.content === "string"
                ? m.content
                : Array.isArray(m.content)
                  ? (m.content as { type: string; text?: string }[])
                      .filter((p) => p.type === "text" && p.text)
                      .map((p) => p.text)
                      .join("\n")
                  : ""
              if (text.trim()) return text.trim()
            }
            return ""
          }
          let answer = ""
          try {
            answer = await Promise.race([
              answered(),
              new Promise<never>((_, rej) => setTimeout(() => rej(new Error("subagent timed out")), 300_000)),
            ])
          } catch (subError) {
            console.error("jev router subagent failed, sending prompt unchanged", subError)
          }
          event.prompt.text = answer
            ? `${event.prompt.text}\n\n` +
              `[A subagent running on ${decision.model} was asked the same self-contained question. ` +
              `Its answer follows; use it if it correctly addresses the task.]\n${answer}`
            : event.prompt.text
          return
        }

        event.prompt.text = decision.prompt
        await ctx.session.switchModel({
          sessionID: event.sessionID,
          model: { providerID, id: id.join("/"), variant: decision.thinking ?? undefined },
        })
      } catch (error) {
        console.error("jev router failed, sending prompt unchanged", error)
      }
    })
  },
})
