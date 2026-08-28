/**
 * BackendManager — dono do ciclo de vida do backend Python.
 *
 * Um único fluxo para dev e produção: o app sobe o hermes gateway (se o
 * health falhar), o agente de voz (`app.py`) e aguarda a bridge responder.
 * Se algo já escuta na porta da bridge, nada é spawnado e o processo alheio
 * é reutilizado — o quit nunca mata o que não criou.
 *
 * Emite `status` (BackendStatus) a cada mudança de fase; o renderer acompanha
 * via IPC e o main usa `ready`/`external` para disparar a reconexão da bridge
 * na hora (sem esperar o backoff).
 */

import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";

import { app } from "electron";

import type { BackendStatus } from "../src/shared/backend";

const PORT_PROBE_TIMEOUT_MS = 400;
const HERMES_HEALTH_TIMEOUT_MS = 2_000;
const HERMES_WAIT_TRIES = 30; // espelho do maya.sh: 30 × 1 s
const BACKEND_READY_TIMEOUT_MS = 120_000; // 1º start baixa modelos (whisper/kokoro)
const BACKEND_POLL_MS = 500;
const KILL_GRACE_MS = 3_000;
const TAIL_MAX_BYTES = 8 * 1024;

const DEFAULT_BRIDGE_PORT = 8686;
const DEFAULT_HERMES_BASE_URL = "http://127.0.0.1:8642/v1";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Conecta na porta; resolve true quando algo aceita a conexão TCP. */
function probePort(host: string, port: number, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port });
    const done = (ok: boolean): void => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
  });
}

/** GET com timeout; resolve true apenas com status 200. */
function httpHealthOk(url: string, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
    req.on("error", () => resolve(false));
  });
}

/** Parser .env mínimo (KEY=VALUE, comentários, aspas, comentário inline). */
function parseDotEnv(content: string): Map<string, string> {
  const vars = new Map<string, string>();
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    const quoted = value.startsWith('"') || value.startsWith("'");
    if (quoted) {
      const quote = value[0];
      if (value.endsWith(quote) && value.length >= 2) value = value.slice(1, -1);
    } else {
      const hash = value.indexOf(" #");
      if (hash !== -1) value = value.slice(0, hash).trimEnd();
    }
    vars.set(key, value);
  }
  return vars;
}

function parseDotEnvFile(file: string): Map<string, string> {
  try {
    return parseDotEnv(fs.readFileSync(file, "utf8"));
  } catch {
    return new Map();
  }
}

function parsePort(raw: string | undefined, fallback: number): number {
  const value = Number.parseInt((raw ?? "").trim(), 10);
  return Number.isFinite(value) && value > 0 && value < 65536 ? value : fallback;
}

/** Procura o binário em PATH + ~/.local/bin (fora do PATH no lançamento por .desktop). */
function findExecutable(name: string): string | null {
  const home = process.env.HOME ?? "";
  const dirs = new Set<string>([
    ...(process.env.PATH ?? "").split(":").filter(Boolean),
    path.join(home, ".local", "bin"),
  ]);
  for (const dir of dirs) {
    const candidate = path.join(dir, name);
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
      return candidate;
    } catch {
      // segue procurando
    }
  }
  return null;
}

/** Libs CUDA pip-instaladas (subdiretórios 'lib' de site-packages/nvidia) — o maya.sh faz o mesmo. */
function computeNvLibraryPath(python: string): string {
  try {
    const res = spawnSync(python, ["-c", "import site; print(site.getsitepackages()[0])"], {
      timeout: 10_000,
      encoding: "utf8",
    });
    const site = (res.stdout ?? "").trim();
    if (!site || !fs.existsSync(site)) return "";
    const nvidiaDir = path.join(site, "nvidia");
    if (!fs.existsSync(nvidiaDir)) return "";
    const libs: string[] = [];
    for (const entry of fs.readdirSync(nvidiaDir, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const lib = path.join(nvidiaDir, entry.name, "lib");
      if (fs.existsSync(lib)) libs.push(lib);
    }
    return libs.join(":");
  } catch {
    return "";
  }
}

export class BackendManager extends EventEmitter {
  readonly isPackaged = app.isPackaged;

  /** Diretório do backend: resources/backend (prod) ou a raiz do repo (dev). */
  readonly backendDir = this.isPackaged
    ? path.join(process.resourcesPath, "backend")
    : path.resolve(__dirname, "..", "..", "..");

  readonly python = this.isPackaged
    ? path.join(this.backendDir, "venv/bin/python")
    : path.join(this.backendDir, ".venv/bin/python");

  readonly logsDir = path.join(app.getPath("userData"), "logs");

  /** .env efetivo: userData (prod, gravável) ou a raiz do repo (dev). */
  readonly envFile = this.isPackaged
    ? path.join(app.getPath("userData"), ".env")
    : path.join(this.backendDir, ".env");

  private readonly children = new Map<string, ChildProcess>();
  private readonly tails = new Map<string, string>();
  private current: BackendStatus = { phase: "starting" };
  private aborted = false;
  private stopped = false;
  private spawnError: Error | null = null;
  private bridgePort = DEFAULT_BRIDGE_PORT;
  private hermesBaseUrl = DEFAULT_HERMES_BASE_URL;

  constructor() {
    super();
    try {
      fs.mkdirSync(this.logsDir, { recursive: true });
    } catch {
      // userData exótico: segue sem log em arquivo.
    }
  }

  getStatus(): BackendStatus {
    return this.current;
  }

  async start(): Promise<void> {
    if (process.env.MAYA_SKIP_BACKEND === "1") {
      this.setStatus({
        phase: "skipped",
        detail: "MAYA_SKIP_BACKEND=1 — backend não gerenciado pelo app.",
      });
      return;
    }
    this.aborted = false;
    this.stopped = false;
    this.spawnError = null;

    // Prod: garante um .env gravável em userData e valida a chave antes de
    // spawnar (fail-fast com o caminho exato — melhor que o crash do Python).
    let createdEnv = false;
    if (this.isPackaged) {
      if (!fs.existsSync(this.envFile)) {
        const example = path.join(this.backendDir, ".env.example");
        try {
          fs.copyFileSync(example, this.envFile);
          createdEnv = true;
        } catch (error) {
          this.setStatus({
            phase: "failed",
            detail: `Não consegui criar ${this.envFile} (${String(error)}).`,
          });
          return;
        }
      }
      const env = parseDotEnvFile(this.envFile);
      const apiKey = env.get("HERMES_API_KEY") ?? "";
      if (!apiKey || apiKey === "change-me-local-dev" || apiKey.includes("<")) {
        this.setStatus({
          phase: "failed",
          detail: `Configure sua HERMES_API_KEY em ${this.envFile} e reinicie o Maya.`,
          logFile: this.envFile,
        });
        return;
      }
      this.bridgePort = parsePort(env.get("BRIDGE_WS_PORT"), DEFAULT_BRIDGE_PORT);
      this.hermesBaseUrl = (env.get("HERMES_BASE_URL") ?? DEFAULT_HERMES_BASE_URL).replace(
        /\/+$/,
        "",
      );
    } else {
      const env = parseDotEnvFile(this.envFile);
      this.bridgePort = parsePort(env.get("BRIDGE_WS_PORT"), DEFAULT_BRIDGE_PORT);
      this.hermesBaseUrl = (env.get("HERMES_BASE_URL") ?? DEFAULT_HERMES_BASE_URL).replace(
        /\/+$/,
        "",
      );
    }

    this.setStatus({
      phase: "starting",
      detail: createdEnv ? `Primeira execução: .env criado em ${this.envFile}` : undefined,
    });

    // Backend já no ar (maya.sh, mock, órfão de crash)? Reutiliza — nada spawnado.
    if (await probePort("127.0.0.1", this.bridgePort, PORT_PROBE_TIMEOUT_MS)) {
      this.setStatus({
        phase: "external",
        detail: `Backend já em execução na porta ${this.bridgePort} — reutilizando.`,
      });
      return;
    }

    if (!(await this.ensureHermes())) return;

    // LD_LIBRARY_PATH ANTES do Python iniciar (ctranslate2 precisa de libcublas).
    const nvLibs = computeNvLibraryPath(this.python);
    if (nvLibs) {
      this.setStatus({ phase: "starting", detail: "Preparando libs CUDA…" });
    } else {
      console.warn(
        "[backend] libs nvidia não encontradas no venv — se STT_DEVICE=cuda, o import do ctranslate2 vai falhar (veja o log).",
      );
    }

    if (this.spawnBackend(nvLibs)) {
      await this.waitForReady();
    }
  }

  async stop(): Promise<void> {
    if (this.stopped) return;
    this.stopped = true;
    this.aborted = true;

    for (const child of this.children.values()) {
      this.killGroup(child, false);
    }
    await delay(KILL_GRACE_MS);
    for (const child of this.children.values()) {
      this.killGroup(child, true);
    }
    this.children.clear();
    this.setStatus({ phase: "stopped" });
  }

  /** Sobe o hermes gateway se o health falhar; resolve false já com `failed` emitido. */
  private async ensureHermes(): Promise<boolean> {
    if (await httpHealthOk(`${this.hermesBaseUrl}/health`, HERMES_HEALTH_TIMEOUT_MS)) {
      return true;
    }
    const hermesBin = findExecutable("hermes");
    if (!hermesBin) {
      this.setStatus({
        phase: "failed",
        detail:
          "CLI 'hermes' não encontrada. Instale o Hermes Agent (hermes gateway fica em ~/.local/bin) ou suba-o manualmente.",
      });
      return false;
    }
    return this.spawnHermes(hermesBin);
  }

  private spawnHermes(hermesBin: string): Promise<boolean> {
    return new Promise((resolve) => {
      const logFile = path.join(this.logsDir, "hermes.log");
      this.setStatus({
        phase: "starting",
        detail: `Subindo hermes gateway (log: ${logFile})…`,
        logFile,
      });
      const child = spawn(hermesBin, ["gateway"], {
        detached: true,
        stdio: ["ignore", "pipe", "pipe"],
      });
      this.children.set("hermes", child);
      this.attachLogging(child, "hermes");
      child.once("error", (error) => {
        this.children.delete("hermes");
        this.setStatus({
          phase: "failed",
          detail: `Falha ao iniciar '${hermesBin}': ${error.message}`,
          logFile,
        });
        resolve(false);
      });

      const startedAt = Date.now();
      const poll = async (): Promise<void> => {
        if (this.aborted) {
          resolve(false);
          return;
        }
        if (child.exitCode !== null) {
          this.children.delete("hermes");
          this.setStatus({
            phase: "failed",
            detail: "hermes gateway morreu ao subir.",
            exitCode: child.exitCode,
            logTail: this.getTail("hermes"),
            logFile,
          });
          resolve(false);
          return;
        }
        if (await httpHealthOk(`${this.hermesBaseUrl}/health`, HERMES_HEALTH_TIMEOUT_MS)) {
          resolve(true);
          return;
        }
        if (Date.now() - startedAt >= HERMES_WAIT_TRIES * 1_000) {
          this.setStatus({
            phase: "failed",
            detail: `Hermes gateway não respondeu em ${HERMES_WAIT_TRIES}s — ver log: ${logFile}`,
            logFile,
          });
          resolve(false);
          return;
        }
        setTimeout(() => void poll(), 1_000);
      };
      void poll();
    });
  }

  private spawnBackend(nvLibs: string): boolean {
    const logFile = path.join(this.logsDir, "backend.log");
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      MAYA_ENV_FILE: this.envFile,
    };
    if (nvLibs) {
      env.LD_LIBRARY_PATH = nvLibs + (process.env.LD_LIBRARY_PATH ? `:${process.env.LD_LIBRARY_PATH}` : "");
    }
    const child = spawn(this.python, ["app.py"], {
      cwd: this.backendDir,
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
      env,
    });
    this.children.set("backend", child);
    this.attachLogging(child, "backend");
    console.log(`[backend] spawn: ${this.python} app.py (cwd=${this.backendDir})`);
    this.setStatus({
      phase: "starting",
      detail: "Iniciando agente de voz…",
      pid: child.pid,
      logFile,
    });
    child.once("error", (error) => {
      this.spawnError = error;
    });
    child.once("exit", (code) => {
      this.children.delete("backend");
      // Já estava rodando e caiu: avisa, a bridge segue reconectando sozinha
      // (o próximo launch do app reutiliza a porta, se o órfão sobreviver).
      if (this.current.phase === "ready" || this.current.phase === "starting") {
        this.setStatus({
          phase: "failed",
          detail: "Backend encerrou inesperadamente.",
          exitCode: code,
          logTail: this.getTail("backend"),
          logFile,
        });
      }
    });
    return true;
  }

  private async waitForReady(): Promise<void> {
    const child = this.children.get("backend");
    const startedAt = Date.now();
    for (;;) {
      if (this.aborted) return;
      if (this.spawnError) {
        this.setStatus({
          phase: "failed",
          detail: `Falha ao iniciar o Python: ${this.spawnError.message}`,
          logFile: path.join(this.logsDir, "backend.log"),
        });
        return;
      }
      if (child && child.exitCode !== null) {
        this.setStatus({
          phase: "failed",
          detail: "Backend encerrou antes de abrir a bridge.",
          exitCode: child.exitCode,
          logTail: this.getTail("backend"),
          logFile: path.join(this.logsDir, "backend.log"),
        });
        return;
      }
      if (await probePort("127.0.0.1", this.bridgePort, PORT_PROBE_TIMEOUT_MS)) {
        this.setStatus({ phase: "ready", pid: child?.pid });
        return;
      }
      if (Date.now() - startedAt >= BACKEND_READY_TIMEOUT_MS) {
        const logFile = path.join(this.logsDir, "backend.log");
        this.setStatus({
          phase: "failed",
          detail: `Backend não abriu a bridge em ${BACKEND_READY_TIMEOUT_MS / 1_000}s — ver log: ${logFile}`,
          logFile,
        });
        if (child) this.killGroup(child, true);
        return;
      }
      await delay(BACKEND_POLL_MS);
    }
  }

  /** stdout/stderr → log em arquivo + tail rolante em memória. */
  private attachLogging(child: ChildProcess, key: string): void {
    const logFile = path.join(this.logsDir, `${key}.log`);
    const stream = fs.createWriteStream(logFile, { flags: "a" });
    const sink = (chunk: Buffer | string): void => {
      stream.write(chunk);
      const prev = this.tails.get(key) ?? "";
      const next = (prev + String(chunk)).slice(-TAIL_MAX_BYTES);
      this.tails.set(key, next);
    };
    child.stdout?.on("data", sink);
    child.stderr?.on("data", sink);
    child.once("exit", () => stream.end());
  }

  private getTail(key: string): string {
    return this.tails.get(key) ?? "";
  }

  private killGroup(child: ChildProcess, force: boolean): void {
    if (child.exitCode !== null || child.pid === undefined) return;
    try {
      // detached → grupo próprio; kill(-pid) derruba o grupo inteiro.
      process.kill(-child.pid, force ? "SIGKILL" : "SIGTERM");
    } catch {
      // já foi
    }
  }

  private setStatus(partial: Partial<BackendStatus>): void {
    this.current = { ...this.current, ...partial };
    this.emit("status", this.current);
  }
}
