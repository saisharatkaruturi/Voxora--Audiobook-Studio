import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { venvPython } from "./py.mjs";

const backend = join(import.meta.dirname, "..", "backend");
if (!existsSync(join(backend, ".venv"))) {
  execFileSync(process.platform === "win32" ? "python" : "python3", ["-m", "venv", ".venv"], { cwd: backend, stdio: "inherit" });
}
execFileSync(venvPython(backend), ["-m", "pip", "install", "-r", "requirements.txt"], { cwd: backend, stdio: "inherit" });
