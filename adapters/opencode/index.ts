import { Plugin } from "@opencode/plugin"
import { execFile } from "node:child_process"
import os from "node:os"
import path from "node:path"
import { promisify } from "node:util"

const run = promisify(execFile)
const router = process.env.JEV_ROUTER ?? path.join(os.homedir(), "jev-router", "router.py")

export default Plugin.define({
  id: "wriggle.jev-router",
  async setup(ctx) {
    const skillsDir = path.join(ctx.location.directory, ".opencode", "skills")
    await ctx.session.hook("prompt", async (event) => {
      try {
        const { stdout } = await run("python3", [router, "--json", "--skills-dir", skillsDir, event.prompt.text])
        const decision = JSON.parse(stdout)
        const [providerID, ...id] = decision.model.split("/")
        event.prompt.text = decision.prompt
        await ctx.session.switchModel({ sessionID: event.sessionID, model: { providerID, id: id.join("/") } })
      } catch (error) {
        console.error("jev router failed, sending prompt unchanged", error)
      }
    })
  },
})
