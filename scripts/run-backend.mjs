import { spawn } from "node:child_process";
import { join } from "node:path";
import { venvPython } from "./py.mjs";

const backend = join(import.meta.dirname, "..", "backend");
const args = process.argv.length > 2 ? process.argv.slice(2) : ["main.py"];
const child = spawn(venvPython(backend), args, { cwd: backend, stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 0));
