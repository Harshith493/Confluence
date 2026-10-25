"""Use a selector loop for Windows tests in restricted desktop sandboxes."""
import asyncio
import os

if os.name == "nt" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
