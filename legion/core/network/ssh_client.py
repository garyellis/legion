from dataclasses import dataclass, asdict
from enum import Enum, auto
from typing import List, Dict, Any, Optional
import paramiko
from pathlib import Path

class ConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTED = auto()
    FAILED = auto()

@dataclass
class CommandResult:
    host: str
    cmd: str
    stdout: str
    stderr: str
    exit_code: int

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    @property
    def failed(self) -> bool:
        return self.exit_code != 0

    def to_json(self):
        return asdict(self)

class SSH(object):
    def __init__(self):
        self.host:  Optional[str] = None
        self.client: Optional[paramiko.SSHClient] = None
        self.results: List[CommandResult] = []
        self._config = self._load_config()
        self.state = ConnectionState.DISCONNECTED

    def is_connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED

    def _load_config(self) -> paramiko.SSHConfig:
        path = Path.home() / ".ssh" / "config"
        if path.exists():
            return paramiko.SSHConfig().from_path(path)

        return paramiko.SSHConfig()

    def to(self, host: str) -> "SSH":
        self.host = host
        return self

    def connect(self) -> "SSH":
        if not self.host:
            raise ValueError("Host must be set before connecting. Use .to(host)")

        if self.client:
            return self

        host_info = self._config.lookup(self.host)
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        timeout = int(host_info.get('connecttimeout', 10))

        try:
            self.client.connect(
                hostname=host_info.get('hostname', self.host),
                username=host_info.get('user'),
                port=int(host_info.get('port', 22)),
                key_filename=host_info.get('identityfile'),
                sock=paramiko.ProxyCommand(host_info['proxycommand']) if 'proxycommand' in host_info else None,
                allow_agent=host_info.get('forwardagent', 'no') == 'yes',
                timeout=timeout,
                banner_timeout=30
            )
            self.state = ConnectionState.CONNECTED
        except Exception:
            self.state = ConnectionState.FAILED
            raise
        return self

    def run(self, cmd: str, timeout: int = 600) -> "SSH":
        if self.state != ConnectionState.CONNECTED:
            self.connect()

        if self.client is None:
            raise RuntimeError("Failed to establish an SSH connection.")

        if self.host is None:
            raise ValueError("Host is not set")

        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        result = CommandResult(
            host=self.host,
            cmd=cmd,
            stdout=stdout.read().decode('utf-8').strip(),
            stderr=stderr.read().decode('utf-8').strip(),
            exit_code=stdout.channel.recv_exit_status()
        )

        self.results.append(result)
        return self

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
            self.state = ConnectionState.DISCONNECTED
        return self

    def last_result(self) -> Optional[CommandResult]:
        return self.results[-1] if self.results else None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
