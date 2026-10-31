# Autonomous Agentic AI Local Client

This is a **developer library**, not a desktop installer. It provides a small, loopback-only JavaScript client for the project's authenticated Python API.

Install from GitHub Packages (GitHub authentication may be required):

```bash
npm install @samadalam481470sa-cmd/autonomous-agentic-ai-client --registry=https://npm.pkg.github.com
```

Example:

```js
import { AgenticClient } from "@samadalam481470sa-cmd/autonomous-agentic-ai-client";
const client = new AgenticClient({ token: process.env.AGENT_ADMIN_TOKEN });
console.log(await client.listProjects());
```

The backend must be running locally. No cloud inference or autonomous model training is included in this package. Desktop installers are distributed separately through GitHub Releases once their builds succeed.
