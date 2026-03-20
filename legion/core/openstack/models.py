from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class VMStatus(str, Enum):
    """
    OpenStack server statuses. Using str-mixed Enum for better 
    JSON serialization and comparison.
    """
    ACTIVE = "ACTIVE"
    SHUTOFF = "SHUTOFF"
    ERROR = "ERROR"
    BUILD = "BUILD"
    DELETED = "DELETED"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN

class VMInstance(BaseModel):
    """
    A typed representation of an OpenStack VM instance.
    """
    id: str
    name: str
    status: VMStatus
    # OpenStack's addresses field is a dict: {'network_name': [{'addr': '1.2.3.4', 'version': 4}, ...]}
    addresses: Dict[str, List[Dict]] = Field(default_factory=dict)
    flavor_id: str
    image_id: Optional[str] = None
    created_at: str
    
    # Extended Info (populated optionally)
    vcpus: Optional[int] = None
    ram_mb: Optional[int] = None
    disk_gb: Optional[int] = None
    image_name: Optional[str] = "N/A"
    os_distro: Optional[str] = "N/A"

    @property
    def specs_str(self) -> str:
        """Returns a compact string of the VM hardware specs."""
        if self.vcpus is None:
            return "N/A"
        return f"{self.vcpus} vCPU | {self.ram_mb/1024:.1f} GB RAM | {self.disk_gb} GB Disk"
    
    @property
    def is_running(self) -> bool:
        """Helper to check if the VM is currently active."""
        return self.status == VMStatus.ACTIVE

    @property
    def ipv4_addresses(self) -> List[str]:
        """
        Extracts all IPv4 addresses from the complex OpenStack addresses structure.
        Returns a flat list of strings.
        """
        ips = []
        for _, addr_list in self.addresses.items():
            for addr in addr_list:
                if addr.get("version") == 4:
                    ips.append(addr.get("addr"))
        return ips

    def __str__(self):
        status_color = "🟢" if self.is_running else "🔴"
        return f"{status_color} {self.name:<20} | {self.status.value:<10} | {', '.join(self.ipv4_addresses)}"

class HypervisorResource(BaseModel):
    """
    Represents a physical hypervisor and its resource utilization.
    """
    id: str
    hostname: str
    state: str  # 'up', 'down'
    status: str # 'enabled', 'disabled'
    vcpus_used: int
    vcpus_total: int
    memory_used_mb: int
    memory_total_mb: int
    disk_used_gb: int
    disk_total_gb: int
    running_vms: int

    @property
    def is_up(self) -> bool:
        return self.state == "up" and self.status == "enabled"

class QuotaUsage(BaseModel):
    """
    A standardized view of quota usage across services.
    """
    service: str
    resource: str
    used: int
    limit: int

    @property
    def usage_percent(self) -> float:
        if self.limit <= 0:
            return 0.0
        return (self.used / self.limit) * 100

class AgentStatus(BaseModel):
    """
    Health status for Neutron/Nova agents.
    """
    binary: str
    host: str
    is_alive: bool
    is_admin_up: bool
    last_heartbeat: Optional[str] = None

class LifecycleResult(BaseModel):
    """
    The outcome of a lifecycle action (start, stop, etc) on a VM.
    Useful for batch operations and reporting.
    """
    vm_name: str
    action: str
    success: bool
    message: str
    final_status: Optional[VMStatus] = None

