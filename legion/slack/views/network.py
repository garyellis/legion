from typing import List, Dict, Any
from legion.core.network.dns_check import DNSRecord, RecordSource
from .base import SlackView

class NetworkSlackView(SlackView):
    """Render Network (DNS) data for Slack."""

    def render_dns_audit(self, records: List[DNSRecord]) -> List[Dict[str, Any]]:
        if not records:
            return [self.section("🌐 _No records found during audit._")]

        blocks = [self.header("🌐 DNS Propagation Audit")]

        # Group records by source
        grouped = {
            RecordSource.PARENT: "🏢 Parent (TLD)",
            RecordSource.AUTHORITATIVE: "👑 Authoritative",
            RecordSource.LOCAL: "💻 Local Resolver"
        }

        for source, label in grouped.items():
            source_records = [r for r in records if r.source == source]
            if not source_records:
                continue

            # Increase widths for DNS names and values
            lines = [
                f"{'Name':<40} | {'Type':<5} | {'Values':<40} | {'TTL':<5}",
                "-" * 95
            ]

            for rec in source_records:
                val_str = ", ".join(rec.values)
                
                lines.append(f"{rec.name:<40} | {rec.rtype:<5} | {val_str:<40} | {rec.ttl:<5}")

            content = f"*{label}*\n```\n" + "\n".join(lines) + "\n```"
            blocks.append(self.section(content))

        return blocks
