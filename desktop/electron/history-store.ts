/**
 * Histórico do chat — JSON em `userData/history.json` (espelho de UI; o
 * contexto real da conversa vive na sessão do Hermes).
 *
 * Escrita com debounce + rename atômico (tmp → destino), cap de mensagens.
 */

import fs from "node:fs";
import path from "node:path";

import { app } from "electron";

const MAX_MESSAGES = 200;
const SAVE_DEBOUNCE_MS = 1000;

interface PersistedMessage {
  id: string;
  role: "user" | "agent";
  text: string;
  ts: number;
  final: boolean;
}

let cache: PersistedMessage[] = [];
let saveTimer: NodeJS.Timeout | null = null;

function historyPath(): string {
  return path.join(app.getPath("userData"), "history.json");
}

export function loadHistory(): PersistedMessage[] {
  try {
    const raw = fs.readFileSync(historyPath(), "utf8");
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    cache = parsed.filter(
      (m): m is PersistedMessage =>
        typeof m === "object" &&
        m !== null &&
        typeof (m as PersistedMessage).id === "string" &&
        ((m as PersistedMessage).role === "user" ||
          (m as PersistedMessage).role === "agent") &&
        typeof (m as PersistedMessage).text === "string",
    );
  } catch {
    cache = [];
  }
  return cache;
}

export function saveHistory(messages: PersistedMessage[]): void {
  cache = messages.slice(-MAX_MESSAGES);
  if (saveTimer !== null) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    flush();
  }, SAVE_DEBOUNCE_MS);
}

export function clearHistory(): void {
  cache = [];
  if (saveTimer !== null) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  try {
    fs.unlinkSync(historyPath());
  } catch {
    // Arquivo inexistente é o caso normal.
  }
}

export function flush(): void {
  if (saveTimer !== null) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  try {
    const target = historyPath();
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const tmp = `${target}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(cache));
    fs.renameSync(tmp, target);
  } catch (error) {
    console.warn(`Falha ao salvar o histórico do chat: ${(error as Error).message}`);
  }
}
