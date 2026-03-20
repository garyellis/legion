from legion.slack.registry import registry
from legion.slack.views.network import NetworkSlackView
from legion.core.network.dns_check import DNSMigrationManager, MigrationConfig

@registry.register(
    name="/network:dns-audit",
    description="Perform a DNS propagation audit.",
    usage_hint="[refresh]"
)
async def network_dns_audit(command, ack, say):
    """Handler for /network:dns-audit slash command."""
    await ack()
    
    domain = "k8s.home.lab.io"
    config = MigrationConfig(domain=domain)
    manager = DNSMigrationManager(config)
    
    # Perform the audit by fetching records from all sources
    manager.fetch_parent_records()
    manager.fetch_authoritative_records()
    manager.fetch_local_records()
    
    view = NetworkSlackView()
    blocks = view.render_dns_audit(manager.records)
    
    await say(blocks=blocks)
