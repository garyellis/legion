from typing import List
from rich.table import Table
from legion.cli.views.base import console
from legion.core.openstack.models import VMInstance, LifecycleResult

def display_vm_list(vms: List[VMInstance], filter_pattern: str, extended: bool = False):
    """Displays a detailed list of VMs and their network addresses."""
    table = Table(
        title=f"OpenStack Virtual Machines (Filter: '{filter_pattern}')", 
        header_style="bold magenta",
        expand=True
    )
    table.add_column("Instance Name", style="bold blue")
    table.add_column("Status", justify="center")
    table.add_column("IPv4 Addresses", style="cyan")
    
    if extended:
        table.add_column("Hardware Specs", style="green")
        table.add_column("Image / OS", style="yellow")
    else:
        table.add_column("Flavor ID", style="dim")
        table.add_column("Created At", style="dim")

    for vm in sorted(vms, key=lambda x: x.name):
        status_color = "green" if vm.is_running else "yellow" if vm.status.value == "BUILD" else "red"
        ips = ", ".join(vm.ipv4_addresses) or "None"
        
        if extended:
            table.add_row(
                vm.name,
                f"[{status_color}]{vm.status.value}[/]",
                ips,
                vm.specs_str,
                f"{vm.image_name} ({vm.os_distro})"
            )
        else:
            table.add_row(
                vm.name,
                f"[{status_color}]{vm.status.value}[/]",
                ips,
                vm.flavor_id,
                vm.created_at
            )

    console.print("\n")
    console.print(table)
    console.print(f"[dim]Total matches: {len(vms)}[/dim]\n")

def display_lifecycle_summary(results: List[LifecycleResult], action_name: str):
    """Displays a summary table of the results."""
    table = Table(
        title=f"Lifecycle Summary: {action_name.upper()}", 
        header_style="bold magenta",
        expand=True
    )
    table.add_column("Instance Name", style="bold blue")
    table.add_column("Status", justify="center")
    table.add_column("Message")
    table.add_column("Success", justify="center")

    for r in sorted(results, key=lambda x: x.vm_name):
        success_icon = "✅" if r.success else "❌"
        status_color = "green" if r.success else "red"
        
        table.add_row(
            r.vm_name,
            f"[{status_color}]{r.final_status.value if r.final_status else 'N/A'}[/]",
            r.message,
            success_icon
        )

    console.print("\n")
    console.print(table)
