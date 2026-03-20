from datetime import datetime
from rich.table import Table
from legion.cli.views.base import console, print_message
from legion.core.network.dns_check import DNSMigrationManager

def display_dns_audit_report(manager: DNSMigrationManager, target_ttl: int):
    """
    Renders a detailed DNS audit report as a table.
    """
    table = Table(
        title=f"DNS Audit Report: [bold blue]{manager.config.domain}[/bold blue]",
        caption=f"Target TTL: {target_ttl}s | Current State: {manager.state.name}",
        header_style="bold magenta"
    )
    
    table.add_column("Source", style="cyan")
    table.add_column("Type", justify="center")
    table.add_column("TTL", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Expires In", justify="right")

    for record in manager.records:
        is_clean = record.ttl <= target_ttl
        status_color = "green" if is_clean else "yellow"
        status_text = "CLEAN" if is_clean else "HIGH TTL"
        
        # Format time remaining
        remaining = str(record.time_remaining()).split(".")[0]
        
        table.add_row(
            record.source.name,
            record.rtype,
            str(record.ttl),
            f"[{status_color}]{status_text}[/]",
            remaining
        )

    console.print("\n")
    console.print(table)
    
    horizon = manager.get_migration_horizon()
    if horizon:
        wait_time = horizon - datetime.now()
        if wait_time.total_seconds() > 0:
            print_message(f"Status: WAITING (Safe to pivot in {str(wait_time).split('.')[0]})", style="yellow")
            print_message(f"Migration Horizon: {horizon.strftime('%Y-%m-%d %H:%M:%S')}", style="dim")
        else:
            print_message("Status: READY (All cached records have expired)", style="green")
    console.print("\n")
