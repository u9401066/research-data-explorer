"""Protocol boundary: SDK v2 concurrency, effect hints and machine-readable errors."""

from functools import wraps
from inspect import signature, Parameter
from threading import RLock
from typing import get_type_hints

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from mcp.server.mcpserver.exceptions import ToolError

from rde.interface.mcp.contracts import CONTRACTS
from rde.interface.mcp.results import (
    RdeResult,
    ResultError,
    ToolFailure,
    fingerprints,
    make_result,
    resolve_project,
)

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
                    execution_key = call_kwargs.pop("execution_key", None)
                    arguments = dict(signature(fn).bind(*call_args, **call_kwargs).arguments)
                    project = None if name == "init_project" else resolve_project(arguments)
                    operation_dir = None
                    if execution_key:
                        from rde.interface.mcp.operations import begin

                        try:
                            operation_dir, saved = begin(project, execution_key, name, arguments)
                            if saved is not None:
                                return saved
                        except (ValueError, OSError, KeyError) as error:
                            return RdeResult(
                                tool=name,
                                status="error",
                                message=str(error),
                                error=ResultError(
                                    code=str(error).split(":")[0], message=str(error)
                                ),
                            )
                    before = fingerprints(project)
                    value = fn(*call_args, **call_kwargs)
                    project = (
                        None
                        if name == "init_project" and isinstance(value, ToolFailure)
                        else resolve_project(arguments)
                    )
                    result = make_result(name, value, project, before)
                    if operation_dir is not None:
                        from rde.interface.mcp.operations import finish

                        result = finish(project, operation_dir, result)
                    return result

            # Preserve evaluated annotations including Resolve metadata through
            # the wrapper; postponed annotations belong to the original module.
            hints = get_type_hints(fn, include_extras=True)
            sig = signature(fn)
            parameters = [
                p.replace(annotation=hints.get(n, p.annotation)) for n, p in sig.parameters.items()
            ]
            if not contract.read_only and name != "init_project":
                parameters.append(
                    Parameter(
                        "execution_key", Parameter.KEYWORD_ONLY, default=None, annotation=str | None
                    )
                )
                hints["execution_key"] = str | None
            guarded.__signature__ = sig.replace(
                parameters=parameters,
                return_annotation=RdeResult,
            )
            guarded.__annotations__ = {**hints, "return": RdeResult}
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
                    "rde/result-contract": "rde-result-v1",
                },
            )
            register(*args, **options)(guarded)
            return fn

        return decorator

    async def call_tool(self, name, arguments, context=None):
        try:
            result = await super().call_tool(name, arguments, context)
        except ToolError as exc:
            payload = RdeResult(
                tool=name,
                status="error",
                message=str(exc),
                error=ResultError(code="RDE_CALL_ERROR", message=str(exc)),
            )
            return CallToolResult(
                content=[TextContent(type="text", text=payload.message)],
                structured_content=payload.model_dump(mode="json"),
                is_error=True,
            )
        if isinstance(result, CallToolResult):
            payload = RdeResult.model_validate(result.structured_content)
            result.is_error = payload.status == "error"
            result.content = [TextContent(type="text", text=payload.message)]
        return result
