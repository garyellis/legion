from typing import List, Dict, Any
from legion.core.openstack.models import VMInstance
from .base import SlackView

class LabSlackView(SlackView):
    """Render Lab (OpenStack) data for Slack."""

    def render_vm_list(self, vms: List[VMInstance], filter_pattern: str = None) -> List[Dict[str, Any]]:
        if not vms:
            return [self.section("ℹ️ _No VMs found matching the criteria._")]

        # Use a wider, more descriptive table. 
        # Slack code blocks will provide a horizontal scrollbar on Desktop if needed.
        lines = [
            f"{'Status':<12} | {'Name':<30} | {'IP Address':<15} | {'Flavor':<20}",
            "-" * 85
        ]

        for vm in vms:
            status = vm.status.value
            primary_ip = "N/A"
            for _, addr_list in vm.addresses.items():
                if addr_list:
                    primary_ip = addr_list[0]['addr']
                    break
            
            # Use longer name field to avoid truncation of important IDs
            lines.append(f"{status:<12} | {vm.name:<30} | {primary_ip:<15} | {vm.flavor_id:<20}")

        content = "```\n" + "\n".join(lines) + "\n```"
        
        blocks = [
            self.section(f"🧪 *Lab VM Inventory* {' (Filtered: `' + filter_pattern + '`)' if filter_pattern else ''}"),
            self.section(content),
            self.context(f"Total VMs: {len(vms)}")
        ]
        return blocks
