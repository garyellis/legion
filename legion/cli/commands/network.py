from typing import Annotated, Optional, List
import typer
from datetime import datetime

from legion.plumbing.registry import register_command
from legion.core.network.dns_check import (
    DNSMigrationManager, 
    MigrationConfig
)
from legion.cli.views import (
    render_status,
    render_error,
    print_message
)
from legion.cli.views.network import display_dns_audit_report

@register_command("network", "dns-check")
def dns_check(
    domain: Annotated[str, typer.Argument(help="The zone/domain to monitor (e.g., example.com)")],
    target_ttl: Annotated[int, typer.Option(help="The TTL we want to reach before pivoting")] = 60,
    nameservers: Annotated[Optional[List[str]], typer.Option(help="Specific nameservers to query")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
) -> None:
    """
    Audit DNS records across TLD, Authoritative, and Local resolvers to track migration readiness.
    """
    config = MigrationConfig(
        domain=domain,
        target_ttl=target_ttl,
        nameservers=nameservers or [],
        is_verbose=verbose
    )
    
    manager = DNSMigrationManager(config)
    
    try:
        with render_status(f"Auditing DNS for {domain}"):
            manager.fetch_local_records()
            manager.fetch_authoritative_records()
            manager.fetch_parent_records()

        # Display Report
        display_dns_audit_report(manager, target_ttl)
        
    except Exception as e:
        render_error(str(e))
