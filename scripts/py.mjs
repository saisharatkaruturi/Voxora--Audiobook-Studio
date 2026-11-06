import { existsSync } from "node:fs";
import { join } from "node:path";

/** The backend venv's Python on any OS, falling back to the system Python. */
export function venvPython(backend) {
  const win = join(backend, ".venv", "Scripts", "python.exe");
  const nix = join(backend, ".venv", "bin", "python");
  if (existsSync(win)) return win;
  if (existsSync(nix)) return nix;
  return process.platform === "win32" ? "python" : "python3";
}
