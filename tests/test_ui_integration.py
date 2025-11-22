import asyncio
from kaiagotchi.ui.view import View
from kaiagotchi.ui.terminal_display import TerminalDisplay
try:
    from kaiagotchi.data.system_types import AgentMood
except ImportError:
    AgentMood = None

async def main():
    view = View(config={}, display=TerminalDisplay({}))
    await view.on_starting()
    await asyncio.sleep(2)
    if AgentMood:
        await view.update_mood(AgentMood.HAPPY)
    else:
        await view.update_mood("happy")
    await asyncio.sleep(2)
    await view.update_mood("bored")
    await asyncio.sleep(2)
    await view.on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())
