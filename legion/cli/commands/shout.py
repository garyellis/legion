from legion.cli.registry import register_command
from legion.cli.views import print_message

@register_command("text", "shout")
def shout(text: str) -> None:
    print_message(f"{text.upper()}!!!", style="bold red")

@register_command("text", "count")
def count_words(text: str) -> None:
    word_count = len(text.split())
    print_message(f"Word count: {word_count}", style="green")

@register_command("text", "reverse")
def reverse_text(text: str) -> None:
    reversed_text = text[::-1]
    print_message(f"Reversed: {reversed_text}", style="cyan")
