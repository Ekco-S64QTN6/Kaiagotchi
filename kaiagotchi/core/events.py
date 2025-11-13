import inspect
import logging
from typing import Dict, Set, Callable, Any, Coroutine, Union
from threading import Lock

class EventEmitter:
    """Thread-safe async event emitter."""
    
    def __init__(self):
        self._handlers: Dict[str, Set[Union[Callable, Callable[..., Coroutine]]]] = {}
        self._lock = Lock()
        self.logger = logging.getLogger(__name__)
        
    def on(self, event: str, handler: Union[Callable, Callable[..., Coroutine]]) -> None:
        """Register sync or async event handler."""
        with self._lock:
            if event not in self._handlers:
                self._handlers[event] = set()
            self._handlers[event].add(handler)
                
    async def emit(self, event: str, *args: Any, **kwargs: Any) -> None:
        """Emit event to all handlers."""
        handlers = set()
        
        with self._lock:
            if event in self._handlers:
                handlers = self._handlers[event].copy()
                
        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(*args, **kwargs)
                else:
                    handler(*args, **kwargs)
            except Exception as e:
                self.logger.error(f"Error in handler: {e}", exc_info=True)
