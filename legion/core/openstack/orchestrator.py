import logging
import re
import fnmatch
from typing import List, Callable, Optional
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

# Import our production-grade manager and models
from legion.core.openstack.compute import OpenStackCompute
from legion.core.openstack.models import VMInstance, LifecycleResult

# Configure logging
logger = logging.getLogger(__name__)

def get_compute(cloud: str | None = None) -> OpenStackCompute:
    """Helper to initialize the OpenStack manager."""
    try:
        return OpenStackCompute(cloud_name=cloud)
    except Exception as e:
        logger.error(f"Could not connect to OpenStack: {e}")
        raise RuntimeError(f"Could not connect to OpenStack: {e}")

def fetch_and_filter_vms(compute: OpenStackCompute, pattern: str = "*", use_regex: bool = False, extended: bool = False) -> List[VMInstance]:
    """
    Fetches all VMs and filters them by name using Glob or Regex.
    """
    all_vms = compute.list_vms(extended=extended)
    
    if not pattern or pattern == "*":
        return all_vms

    filtered = []
    for vm in all_vms:
        if use_regex:
            if re.search(pattern, vm.name):
                filtered.append(vm)
        else:
            if fnmatch.fnmatch(vm.name, pattern):
                filtered.append(vm)
                
    return filtered

def run_batch_lifecycle(
    compute: OpenStackCompute, 
    vms: List[VMInstance], 
    action: str = "start",
    on_tick: Optional[Callable[[str], None]] = None
) -> List[LifecycleResult]:
    """
    Orchestrates a batch lifecycle action across a list of VMInstance objects.
    """
    if not vms:
        return []

    results = []
    action_map = {
        "start": compute.start_vm,
        "stop": compute.stop_vm,
        "reboot": compute.reboot_vm,
        "suspend": compute.suspend_vm,
        "resume": compute.resume_vm,
    }
    
    if action not in action_map:
        raise ValueError(f"Unknown action: {action}")
    action_func = action_map[action]

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_vm: dict[Future[LifecycleResult], str] = {
            executor.submit(action_func, vm.id): vm.name  # type: ignore[arg-type]
            for vm in vms
        }
        
        for future in as_completed(future_to_vm):
            vm_name = future_to_vm[future]
            try:
                result = future.result()
                results.append(result)
                if on_tick:
                    on_tick(vm_name)
            except Exception as e:
                logger.error(f"Error processing {vm_name}: {e}")
                results.append(LifecycleResult(
                    vm_name=vm_name, action=action, success=False, message=str(e)
                ))
                if on_tick:
                    on_tick(vm_name)

    return results
