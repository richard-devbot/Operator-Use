"""MCP Manager — handles MCP server connection lifecycle via fastmcp."""

import logging
from typing import TYPE_CHECKING

from operator_use.mcp.tool import MCPTool

if TYPE_CHECKING:
    from fastmcp import Client
    from operator_use.config.service import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPManager:
    """Manages MCP server connections and tool lifecycle.

    Supports multi-agent usage with reference counting:
    - Shared sessions: if Agent A connects to MCP 1, Agent B can reuse the same connection
    - Per-agent visibility: Agent A only sees tools if it explicitly connected
    - Automatic cleanup: server killed only when last agent disconnects
    """

    def __init__(self, server_configs: "list[MCPServerConfig]"):
        self._configs: dict[str, "MCPServerConfig"] = {c.name: c for c in server_configs}
        # Map server_name -> fastmcp.Client (kept alive after __aenter__)
        self._clients: dict[str, "Client"] = {}
        self._tools: dict[str, list[MCPTool]] = {}
        self._connection_count: dict[str, int] = {}
        self._agent_connections: dict[str, set[str]] = {}

    def is_connected(self, agent_id: str, server_name: str) -> bool:
        return server_name in self._agent_connections.get(agent_id, set())

    def is_server_connected(self, server_name: str) -> bool:
        return self._connection_count.get(server_name, 0) > 0

    def list_servers(self, agent_id: str | None = None) -> list[dict]:
        result = []
        for name, cfg in self._configs.items():
            if agent_id is not None:
                if name not in self._agent_connections.get(agent_id, set()):
                    continue
            result.append({
                "name": name,
                "transport": cfg.transport,
                "connected": self.is_server_connected(name),
                "agent_connected": self.is_connected(agent_id, name) if agent_id else None,
                "tool_count": len(self._tools.get(name, [])),
                "connection_count": self._connection_count.get(name, 0),
            })
        return result

    async def connect(self, agent_id: str, server_name: str) -> list[MCPTool]:
        """Connect an agent to an MCP server and return its tools."""
        if self.is_connected(agent_id, server_name):
            logger.info(f"Agent {agent_id} already connected to MCP server '{server_name}'")
            return self._tools.get(server_name, [])

        cfg = self._configs.get(server_name)
        if cfg is None:
            raise ValueError(f"No MCP server config found for '{server_name}'")

        is_first_connection = self._connection_count.get(server_name, 0) == 0

        if is_first_connection:
            client = await self._open_client(cfg)
            try:
                tools_list = await client.list_tools()
            except Exception:
                await client.__aexit__(None, None, None)
                raise

            mcp_tools = [
                MCPTool(
                    server_name=server_name,
                    mcp_tool_name=t.name,
                    description=t.description or "",
                    input_schema=t.inputSchema,
                    client=client,
                )
                for t in tools_list
            ]

            self._clients[server_name] = client
            self._tools[server_name] = mcp_tools
            logger.info(f"MCP server opened | server={server_name} tools={len(mcp_tools)}")

        if agent_id not in self._agent_connections:
            self._agent_connections[agent_id] = set()
        self._agent_connections[agent_id].add(server_name)
        self._connection_count[server_name] = self._connection_count.get(server_name, 0) + 1

        logger.info(
            f"Agent {agent_id} connected to MCP '{server_name}' "
            f"(connection count: {self._connection_count[server_name]})"
        )
        return self._tools.get(server_name, [])

    async def disconnect(self, agent_id: str, server_name: str) -> list[str]:
        """Disconnect an agent from an MCP server."""
        if server_name not in self._agent_connections.get(agent_id, set()):
            raise ValueError(f"Agent {agent_id} is not connected to MCP server '{server_name}'")

        tool_names = [t.name for t in self._tools.get(server_name, [])]

        self._agent_connections[agent_id].discard(server_name)
        self._connection_count[server_name] -= 1

        logger.info(
            f"Agent {agent_id} disconnected from MCP '{server_name}' "
            f"(connection count: {self._connection_count[server_name]})"
        )

        if self._connection_count[server_name] == 0:
            client = self._clients.pop(server_name, None)
            if client is not None:
                try:
                    await client.__aexit__(None, None, None)
                except (RuntimeError, GeneratorExit) as e:
                    logger.debug(f"Non-fatal error closing MCP client for '{server_name}': {e}")
                except Exception as e:
                    logger.warning(f"Error closing MCP client for '{server_name}': {e}")
            self._tools.pop(server_name, None)
            logger.info(f"MCP server closed | server={server_name}")

        return tool_names

    async def disconnect_all(self, agent_id: str | None = None) -> None:
        """Gracefully disconnect all connected servers for an agent (or all agents)."""
        if agent_id is not None:
            servers_to_disconnect = list(self._agent_connections.get(agent_id, set()))
            for server_name in servers_to_disconnect:
                try:
                    await self.disconnect(agent_id, server_name)
                except (RuntimeError, GeneratorExit):
                    logger.debug(f"Non-fatal error disconnecting agent {agent_id} from '{server_name}'")
                except Exception as e:
                    logger.warning(f"Error disconnecting agent {agent_id} from '{server_name}': {e}")
        else:
            all_agents = list(self._agent_connections.keys())
            for agent in all_agents:
                servers = list(self._agent_connections.get(agent, set()))
                for server_name in servers:
                    try:
                        await self.disconnect(agent, server_name)
                    except (RuntimeError, GeneratorExit):
                        logger.debug(f"Non-fatal error disconnecting agent {agent} from '{server_name}'")
                    except Exception as e:
                        logger.warning(f"Error disconnecting agent {agent} from '{server_name}': {e}")

    @staticmethod
    async def _open_client(cfg: "MCPServerConfig") -> "Client":
        """Create and enter a fastmcp Client for the given server config."""
        from fastmcp import Client

        if cfg.transport == "stdio":
            from fastmcp.client.transports import StdioTransport

            if not cfg.command:
                raise ValueError(
                    f"MCP server '{cfg.name}' with transport=stdio requires a command"
                )

            transport = StdioTransport(
                command=cfg.command,
                args=cfg.args,
                env=cfg.env or None,
            )
            client = Client(transport)

        elif cfg.transport in ("http", "sse"):
            if not cfg.url:
                raise ValueError(
                    f"MCP server '{cfg.name}' with transport={cfg.transport} requires a url"
                )

            headers: dict[str, str] = {}
            if cfg.auth_token:
                headers["Authorization"] = f"Bearer {cfg.auth_token}"

            if cfg.transport == "sse":
                from fastmcp.client.transports import SSETransport
                transport = SSETransport(cfg.url, headers=headers or None)
            else:
                from fastmcp.client.transports import StreamableHttpTransport
                transport = StreamableHttpTransport(cfg.url, headers=headers or None)

            client = Client(transport)

        else:
            raise ValueError(f"Unknown MCP transport '{cfg.transport}' for server '{cfg.name}'")

        await client.__aenter__()
        return client
