"""Protocol boundary: SDK v2 concurrency, effect hints and machine-readable errors."""

from functools import wraps
from inspect import signature
from threading import RLock
from typing import get_type_hints

from mcp.server import MCPServer
from mcp.types import CallToolResult, ToolAnnotations

from rde.interface.mcp.contracts import CONTRACTS

# The application registry is process-global; the lock must be too. Sync v2
# handlers run on worker threads. Do not lock the event loop while they execute.
STATE_LOCK = RLock()


class RDEServer(MCPServer):
    def tool(self, *args, **kwargs):
        register = super().tool

        def decorator(fn):
            name = kwargs.get("name") or (args[0] if args else None) or fn.__name__
            contract = CONTRACTS[name]

            @wraps(fn)
            def guarded(*call_args, **call_kwargs):
                with STATE_LOCK:
                    return fn(*call_args, **call_kwargs)

            # Preserve evaluated annotations including Resolve metadata through
            # the wrapper; postponed annotations belong to the original module.
            hints = get_type_hints(fn, include_extras=True)
            sig = signature(fn)
            guarded.__signature__ = sig.replace(
                parameters=[
                    p.replace(annotation=hints.get(n, p.annotation))
                    for n, p in sig.parameters.items()
                ],
                return_annotation=hints.get("return", sig.return_annotation),
            )
            guarded.__annotations__ = hints
            options = dict(kwargs)
            options.setdefault(
                "annotations",
                ToolAnnotations(
                    read_only_hint=contract.read_only,
                    destructive_hint=contract.destructive,
                    idempotent_hint=contract.read_only,
                    open_world_hint=contract.open_world,
                ),
            )
            options.setdefault(
                "meta",
                {
                    "rde/phase": contract.phase,
                    "rde/gate": contract.gate,
                    "rde/effects": contract.effects,
                },
            )
            register(*args, **options)(guarded)
            return fn

        return decorator

    async def call_tool(self, name, arguments, context=None):
        result = await super().call_tool(name, arguments, context)
        if isinstance(result, CallToolResult):
            markdown = "\n".join(block.text for block in result.content if block.type == "text")
            if markdown.lstrip().startswith("❌"):
                result.is_error = True
            if result.structured_content is not None:
                result.structured_content.update(
                    {
                        "rde_status": "error" if result.is_error else "ok",
                        "rde_tool": name,
                    }
                )
        return result
