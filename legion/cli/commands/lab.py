from typing import Annotated, Optional
import json
import typer

from legion.plumbing.registry import register_command
from legion.core.network.ssh_client import SSH
from legion.core.network.wol import WoLPort, wake
from legion.core.openstack.orchestrator import (
    get_compute,
    fetch_and_filter_vms,
    run_batch_lifecycle
)
from legion.cli.views import (
    get_progress_bar, 
    render_error, 
    render_status,
    print_message
)
from legion.cli.views.lab import (
    display_vm_list, 
    display_lifecycle_summary
)

@register_command("lab", "wake")
def lab_wake(
    mac: Annotated[str, typer.Argument(help="Target MAC address")] = "a0:ad:9f:32:99:2e",
    broadcast: Annotated[str, typer.Argument(help="Broadcast address")] = "192.168.1.255",
    ) -> None:
    """Send Wake packet to the lab primary interface"""
    try:
        wake(
            mac=mac,
            broadcast=broadcast,
            port=WoLPort.DISCARD)
        print_message(f"Magic packet sent to {mac}", style="green")
    except Exception as e:
        render_error(str(e))

@register_command("lab", "shutdown")
def lab_shutdown() -> None:
    """Shutddown the lab host"""
    lab_hostname = "ai1.lab"

    with SSH() as ssh:
        results = ssh.to(lab_hostname).run("sudo shutdown").results

        if results:
            result_as_dicts = [r.to_json() for r in results]
            print_message(json.dumps(result_as_dicts, indent=4))

# --- Cloud Lifecycle Commands ---

@register_command("lab", "vm-list")
def lab_cloud_list(
    filter: Annotated[str, typer.Option(help="Glob pattern (e.g. 'web-*') or Regex")] = "*",
    regex: Annotated[bool, typer.Option(help="Use regex")] = False,
    extended: Annotated[bool, typer.Option(help="Show hardware specs and OS info")] = False,
    cloud: Annotated[Optional[str], typer.Option(help="Cloud name")] = None,
) -> None:
    """List lab virtual machines"""
    try:
        compute = get_compute(cloud)
        with render_status("Fetching VM list"):
            vms = fetch_and_filter_vms(compute, filter, regex, extended=extended)
        
        if not vms:
            print_message(f"No VMs matched: '{filter}'", style="yellow")
            return
            
        display_vm_list(vms, filter, extended=extended)
    except Exception as e:
        render_error(str(e))

def _execute_lifecycle(action: str, filter: str, regex: bool, cloud: Optional[str]):
    try:
        compute = get_compute(cloud)
        
        # 1. Fetch and Filter
        with render_status(f"Finding VMs for {action}"):
            matched_vms = fetch_and_filter_vms(compute, filter, regex, extended=False)
        
        if not matched_vms:
            print_message(f"No VMs matched the filter: '{filter}'", style="yellow")
            return

        # 2. Execute Action with Progress
        print_message(f"\n🚀 Batch Operation: {action.upper()} on {len(matched_vms)} instances\n", style="bold cyan")
        
        with get_progress_bar(f"Processing {action}...", total=len(matched_vms)) as progress:
            main_task = progress.add_task(f"Processing...", total=len(matched_vms))
            
            def on_tick(vm_name: str):
                progress.update(main_task, advance=1, description=f"[green]Done:[/] {vm_name}")
            
            results = run_batch_lifecycle(compute, matched_vms, action=action, on_tick=on_tick)
        
        if results:
            display_lifecycle_summary(results, action)
            
    except Exception as e:
        render_error(str(e))

@register_command("lab", "vm-start")
def lab_cloud_start(
    filter: Annotated[str, typer.Option(help="Filter VMs to start")] = "*",
    regex: Annotated[bool, typer.Option(help="Use regex")] = False,
    cloud: Annotated[Optional[str], typer.Option(help="Cloud name")] = None,
) -> None:
    """Start matched virtual machines in the lab cloud"""
    _execute_lifecycle("start", filter, regex, cloud)

@register_command("lab", "vm-stop")
def lab_cloud_stop(
    filter: Annotated[str, typer.Option(help="Filter VMs to stop")] = "*",
    regex: Annotated[bool, typer.Option(help="Use regex")] = False,
    cloud: Annotated[Optional[str], typer.Option(help="Cloud name")] = None,
) -> None:
    """Stop matched virtual machines in the lab cloud"""
    _execute_lifecycle("stop", filter, regex, cloud)

@register_command("lab", "vm-reboot")
def lab_cloud_reboot(
    filter: Annotated[str, typer.Option(help="Filter VMs to reboot")] = "*",
    regex: Annotated[bool, typer.Option(help="Use regex")] = False,
    cloud: Annotated[Optional[str], typer.Option(help="Cloud name")] = None,
) -> None:
    """Reboot matched virtual machines in the lab cloud"""
    _execute_lifecycle("reboot", filter, regex, cloud)
