import shlex
from legion.slack.registry import registry
from legion.slack.views.lab import LabSlackView
from legion.core.openstack.orchestrator import get_compute, fetch_and_filter_vms

@registry.register(
    name="/lab:vm-list",
    description="List all VMs in the lab environment.",
    usage_hint="[--filter <regex>]"
)
async def lab_vm_list(command, ack, say):
    """Handler for /lab:vm-list slash command."""
    await ack()
    
    # Simple argument parsing
    text = command.get("text", "")
    args = shlex.split(text)
    filter_pattern = None
    if "--filter" in args:
        idx = args.index("--filter")
        if idx + 1 < len(args):
            filter_pattern = args[idx + 1]

    # Initialize compute and fetch VMs
    compute = get_compute()
    vms = fetch_and_filter_vms(compute, pattern=filter_pattern or "*")
    
    view = LabSlackView()
    blocks = view.render_vm_list(vms, filter_pattern=filter_pattern)
    
    await say(blocks=blocks)
