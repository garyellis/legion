import functools
from typing import Any, Callable, Dict, List, Optional


class SlackCommand:
    def __init__(
        self,
        name: str,
        description: str,
        usage_hint: str,
        handler: Callable[..., Any] | None = None,
    ):
        self.name = name
        self.description = description
        self.usage_hint = usage_hint
        self.handler = handler


class SlackRegistry:
    def __init__(self) -> None:
        self.commands: Dict[str, SlackCommand] = {}

    def register(self, name: str, description: str, usage_hint: str = "[options]"):
        """Decorator to register a Slack slash command with its handler."""

        def decorator(func: Callable[..., Any]):
            self.commands[name] = SlackCommand(
                name=name,
                description=description,
                usage_hint=usage_hint,
                handler=func,
            )

            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    def register_metadata(
        self, name: str, description: str, usage_hint: str = ""
    ) -> None:
        """Register command metadata only (handler wired separately via DI)."""
        self.commands[name] = SlackCommand(
            name=name,
            description=description,
            usage_hint=usage_hint,
        )

    def get_command(self, name: str) -> Optional[SlackCommand]:
        return self.commands.get(name)

    def list_commands(self) -> List[SlackCommand]:
        return list(self.commands.values())

    def list_all_metadata(self) -> List[SlackCommand]:
        """Return all registered commands (with or without handlers)."""
        return list(self.commands.values())


# Global registry instance
registry = SlackRegistry()
