from __future__ import annotations

import asyncio
import html
import logging
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import web

logger = logging.getLogger("maya.approvals")

ApprovalPoster = Callable[[str, dict[str, Any]], Awaitable[bool]]

_LABELS = {
    "once": "Aprovar uma vez",
    "session": "Aprovar nesta sessão",
    "always": "Aprovar sempre",
    "deny": "Negar",
}


@dataclass(frozen=True, slots=True)
class PendingApproval:
    run_id: str
    request_id: str
    command: str
    description: str
    choices: tuple[str, ...]
    execution_generation: int | None = None


def parse_approval(payload: dict[str, Any]) -> PendingApproval | None:
    run_id = str(payload.get("run_id") or "").strip()
    request_id = str(payload.get("request_id") or "").strip()
    if not run_id or not request_id:
        return None
    raw_choices = payload.get("choices")
    choices = tuple(str(choice) for choice in raw_choices) if isinstance(raw_choices, list) else ()
    if not choices:
        choices = ("once", "deny")
    generation = payload.get("execution_generation")
    return PendingApproval(
        run_id=run_id,
        request_id=request_id,
        command=str(payload.get("command") or ""),
        description=str(payload.get("description") or ""),
        choices=choices,
        execution_generation=generation if isinstance(generation, int) else None,
    )


def resolution_body(approval: PendingApproval, choice: str) -> dict[str, Any]:
    body: dict[str, Any] = {"choice": choice, "request_id": approval.request_id}
    if approval.execution_generation is not None:
        body["execution_generation"] = approval.execution_generation
    return body


class ApprovalBroker:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        port: int,
        enabled: bool = True,
        notify: bool = True,
        poster: ApprovalPoster | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._port = port
        self._enabled = enabled
        self._notify = notify
        self._poster = poster or self._post
        self._pending: dict[str, PendingApproval] = {}
        self._runner: web.AppRunner | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._notify_tasks: set[asyncio.Task[None]] = set()
        self._close_task: asyncio.Task[None] | None = None

    @property
    def page_url(self) -> str:
        return f"http://127.0.0.1:{self._port}/"

    @property
    def pending(self) -> tuple[PendingApproval, ...]:
        return tuple(self._pending.values())

    def publish(self, payload: dict[str, Any]) -> None:
        approval = parse_approval(payload)
        if approval is None:
            logger.warning("ignoring malformed approval event: %s", payload)
            return
        self._pending[approval.request_id] = approval
        logger.info(
            "approval pending: run=%s request=%s command=%s",
            approval.run_id,
            approval.request_id,
            approval.command[:200],
        )
        if self._enabled and self._port > 0:
            self._ensure_server()
        if self._notify:
            self._notify_desktop(approval)

    async def resolve(self, approval: PendingApproval, choice: str) -> bool:
        if choice not in approval.choices:
            logger.warning("approval choice %s not in %s", choice, approval.choices)
            return False
        try:
            resolved = await self._poster(approval.run_id, resolution_body(approval, choice))
        except Exception:
            logger.exception("failed to resolve approval %s", approval.request_id)
            return False
        if resolved:
            self._pending.pop(approval.request_id, None)
        return resolved

    def close_later(self) -> None:
        if self._close_task is not None and not self._close_task.done():
            return
        try:
            self._close_task = asyncio.create_task(
                self.aclose(),
                name="maya-approval-close",
            )
        except RuntimeError:
            return

    async def aclose(self) -> None:
        if self._start_task is not None:
            self._start_task.cancel()
            self._start_task = None
        for task in tuple(self._notify_tasks):
            task.cancel()
        self._notify_tasks.clear()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def _ensure_server(self) -> None:
        if self._runner is not None or self._start_task is not None:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._start_task = asyncio.create_task(self._start_server(), name="maya-approval-page")

    async def _start_server(self) -> None:
        try:
            app = web.Application()
            app.router.add_get("/", self._handle_index)
            app.router.add_post("/resolve", self._handle_resolve)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", self._port)
            await site.start()
            self._runner = runner
            logger.info("approval page listening at %s", self.page_url)
        except Exception:
            logger.exception("failed to start approval page")
        finally:
            self._start_task = None

    async def _handle_index(self, request: web.Request) -> web.Response:
        if not self._pending:
            body = "<p>Nenhuma aprovação pendente.</p>"
        else:
            body = "".join(self._render_approval(approval) for approval in self._pending.values())
        page = (
            "<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
            "<title>Maya - aprovações</title>"
            "<body><h1>Aprovações pendentes</h1>"
            f"{body}</body></html>"
        )
        return web.Response(text=page, content_type="text/html")

    async def _handle_resolve(self, request: web.Request) -> web.Response:
        form = await request.post()
        request_id = str(form.get("request_id") or "")
        choice = str(form.get("choice") or "deny")
        approval = self._pending.get(request_id)
        if approval is None:
            return web.Response(text="Aprovação não encontrada.", status=404)
        resolved = await self.resolve(approval, choice)
        return web.Response(
            text="Resolvido." if resolved else "Não foi possível resolver a aprovação.",
            status=200 if resolved else 502,
            content_type="text/plain",
        )

    def _render_approval(self, approval: PendingApproval) -> str:
        choices = "".join(
            f"<button name='choice' value='{html.escape(choice)}'>"
            f"{html.escape(_LABELS.get(choice, choice))}</button>"
            for choice in approval.choices
        )
        description = html.escape(approval.description or "Comando pendente")
        command = html.escape(approval.command or "(sem comando)")
        return (
            f"<section><h2>{description}</h2>"
            f"<pre>{command}</pre>"
            f"<form method='post' action='/resolve'>"
            f"<input type='hidden' name='request_id' value='{html.escape(approval.request_id)}'>"
            f"{choices}</form></section>"
        )

    def _notify_desktop(self, approval: PendingApproval) -> None:
        if not shutil.which("notify-send"):
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        task = asyncio.create_task(
            self._send_notification(approval),
            name="maya-approval-notify",
        )
        self._notify_tasks.add(task)
        task.add_done_callback(self._notify_tasks.discard)

    async def _send_notification(self, approval: PendingApproval) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                "notify-send",
                "Maya precisa de aprovação",
                approval.command[:200] or "Comando pendente",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
        except Exception:
            logger.debug("notify-send failed", exc_info=True)

    async def _post(self, run_id: str, body: dict[str, Any]) -> bool:
        url = f"{self._base_url}/runs/{run_id}/approval"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=15.0)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
                url,
                json=body,
                headers=headers,
            ) as response:
                if response.status >= 400:
                    text = await response.text()
                    logger.warning(
                        "approval rejected: status=%s body=%s",
                        response.status,
                        text[:300],
                    )
                    return False
                return True
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.warning("approval request failed: %s", exc)
            return False
