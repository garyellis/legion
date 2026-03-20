import openstack
import logging
from typing import List, Optional, Dict, Any
from .models import (
    VMInstance, VMStatus, HypervisorResource, QuotaUsage, LifecycleResult
)

logger = logging.getLogger(__name__)

class OpenStackCompute:
    """
    A clean wrapper around OpenStack compute (Nova) operations.
    Includes lifecycle management, hypervisor monitoring, and quotas.
    """
    def __init__(self, cloud_name: Optional[str] = None):
        """
        Initializes the connection. If cloud_name is None, uses OS_CLOUD env var.
        """
        self.conn = openstack.connect(cloud=cloud_name)

    def list_vms(self, extended: bool = False) -> List[VMInstance]:
        """
        Fetch all servers. If extended is True, maps flavors and images for more info.
        """
        servers = list(self.conn.compute.servers())
        
        flavors = {}
        images = {}
        
        if extended:
            # Batch fetch flavors (including private ones) and images
            try:
                flavors = {f.id: f for f in self.conn.compute.flavors(is_public=None)}
            except Exception as e:
                logger.warning(f"Could not batch fetch flavors: {e}")
                
            try:
                images = {i.id: i for i in self.conn.image.images()}
            except Exception as e:
                logger.warning(f"Could not batch fetch images: {e}")

        vms = []
        for s in servers:
            # Fallback for flavors not in the batch (e.g., deleted or very specific project flavors)
            f_id = s.flavor.get("id")
            if extended and f_id and f_id not in flavors:
                try:
                    flavors[f_id] = self.conn.compute.get_flavor(f_id)
                except Exception:
                    pass
            
            vms.append(self._to_vm_model(s, flavors, images))
            
        return vms

    def find_vm(self, name_or_id: str) -> Optional[VMInstance]:
        """Find a single VM by name or ID."""
        server = self.conn.compute.find_server(name_or_id)
        return self._to_vm_model(server) if server else None

    def start_vm(self, name_or_id: str, wait: bool = True, timeout: int = 600) -> LifecycleResult:
        """Power on a VM and return a detailed result."""
        return self._run_lifecycle_action(name_or_id, "start", "ACTIVE", wait, timeout)

    def stop_vm(self, name_or_id: str, wait: bool = True, timeout: int = 600) -> LifecycleResult:
        """Power off a VM and return a detailed result."""
        return self._run_lifecycle_action(name_or_id, "stop", "SHUTOFF", wait, timeout)

    def reboot_vm(self, name_or_id: str, hard: bool = False, wait: bool = True, timeout: int = 600) -> LifecycleResult:
        """Reboot a VM and return a detailed result."""
        action = "reboot_hard" if hard else "reboot_soft"
        return self._run_lifecycle_action(name_or_id, action, "ACTIVE", wait, timeout)

    def suspend_vm(self, name_or_id: str, wait: bool = True, timeout: int = 600) -> LifecycleResult:
        """Suspend a VM and return a detailed result."""
        return self._run_lifecycle_action(name_or_id, "suspend", "SUSPENDED", wait, timeout)

    def resume_vm(self, name_or_id: str, wait: bool = True, timeout: int = 600) -> LifecycleResult:
        """Resume a suspended VM and return a detailed result."""
        return self._run_lifecycle_action(name_or_id, "resume", "ACTIVE", wait, timeout)

    def delete_vm(self, name_or_id: str, wait: bool = True, timeout: int = 600) -> LifecycleResult:
        """Delete a VM and return a detailed result."""
        server = self.conn.compute.find_server(name_or_id)
        if not server:
            return LifecycleResult(vm_name=name_or_id, action="delete", success=False, message="Not Found")
        
        try:
            self.conn.compute.delete_server(server)
            if wait:
                self.conn.compute.wait_for_delete(server, wait=timeout)
            return LifecycleResult(
                vm_name=server.name, action="delete", success=True, 
                message="Deleted successfully", final_status=VMStatus.DELETED
            )
        except Exception as e:
            return LifecycleResult(vm_name=server.name, action="delete", success=False, message=str(e))

    def _run_lifecycle_action(self, name_or_id: str, action: str, target_status: str, wait: bool, timeout: int) -> LifecycleResult:
        """Internal helper to safely run lifecycle actions with results."""
        server = self.conn.compute.find_server(name_or_id)
        if not server:
            return LifecycleResult(vm_name=name_or_id, action=action, success=False, message="Not Found")

        if server.status == target_status:
            return LifecycleResult(
                vm_name=server.name, action=action, success=True, 
                message=f"Already in target state: {target_status}", 
                final_status=VMStatus(server.status)
            )

        try:
            action_map = {
                "start": self.conn.compute.start_server,
                "stop": self.conn.compute.stop_server,
                "reboot_soft": lambda s: self.conn.compute.reboot_server(s, "SOFT"),
                "reboot_hard": lambda s: self.conn.compute.reboot_server(s, "HARD"),
                "suspend": self.conn.compute.suspend_server,
                "resume": self.conn.compute.resume_server,
            }
            action_func = action_map.get(action)
            action_func(server)
            
            if wait:
                server = self.conn.compute.wait_for_server(server, status=target_status, wait=timeout)
            
            return LifecycleResult(
                vm_name=server.name, action=action, success=True, 
                message=f"Action '{action}' completed.", 
                final_status=VMStatus(server.status)
            )
        except Exception as e:
            return LifecycleResult(
                vm_name=server.name, action=action, success=False, 
                message=str(e), final_status=VMStatus(server.status)
            )

    def list_hypervisors(self) -> List[HypervisorResource]:
        """Returns resource utilization for all hypervisors."""
        hypers = self.conn.compute.hypervisors()
        results = []
        for h in hypers:
            results.append(HypervisorResource(
                id=h.id, hostname=h.name, state=h.state, status=h.status,
                vcpus_used=h.vcpus_used or 0, vcpus_total=h.vcpus or 0,
                memory_used_mb=(h.memory_size or 0) - (h.memory_free or 0),
                memory_total_mb=h.memory_size or 0,
                disk_used_gb=h.local_disk_used or 0, disk_total_gb=h.local_disk_size or 0,
                running_vms=h.running_vms or 0
            ))
        return results

    def get_quotas(self) -> List[QuotaUsage]:
        """Returns a flat list of compute quota usage."""
        project_id = self.conn.current_project_id
        quotas = self.conn.compute.get_quota_set(project_id, usage=True)
        q_dict = quotas.to_dict()
        usage_dict = q_dict.get('usage', {})
        results = []
        mapping = {"instances": "Instances", "cores": "vCPUs", "ram": "RAM (MB)"}
        for key, label in mapping.items():
            results.append(QuotaUsage(
                service="Compute", resource=label, 
                used=usage_dict.get(key, 0), limit=q_dict.get(key, -1)
            ))
        return results

    def _to_vm_model(self, server, flavors: Dict[str, Any] = {}, images: Dict[str, Any] = {}) -> VMInstance:
        """Helper to convert OpenStack SDK server to our VMInstance model."""
        # Note: server.flavor is typically a snapshot dictionary/object 
        # that contains vcpus, ram, and disk directly (Nova microversion 2.47+).
        flavor_data = server.flavor
        flavor_id = flavor_data.get("id", "unknown")
        image_id = server.image.get("id") if server.image else None
        
        # Priority 1: Use the snapshot data directly from the server object
        vcpus = flavor_data.get("vcpus")
        ram = flavor_data.get("ram")
        disk = flavor_data.get("disk")

        # Priority 2: Fallback to the provided flavors catalog if snapshot is incomplete
        if vcpus is None or ram is None:
            catalog_flavor = flavors.get(flavor_id)
            if catalog_flavor:
                vcpus = getattr(catalog_flavor, "vcpus", vcpus)
                ram = getattr(catalog_flavor, "ram", ram)
                disk = getattr(catalog_flavor, "disk", disk)

        image = images.get(image_id) if image_id else None
        
        return VMInstance(
            id=server.id,
            name=server.name,
            status=VMStatus(server.status),
            addresses=server.addresses,
            flavor_id=flavor_id,
            image_id=image_id,
            created_at=server.created_at,
            # Extended Info
            vcpus=vcpus,
            ram_mb=ram,
            disk_gb=disk,
            image_name=image.name if image else "N/A",
            os_distro=image.get("os_distro", "N/A") if image else "N/A"
        )
