"""Background jobs using dynamic dispatch — invisible to a static call graph."""
from app import config, handlers


def run_task(name, payload):
    # [D11] the target is built from a config string at runtime, so no static
    # call edge exists between tasks.py and handlers.py's functions.
    fn_name = config.get("TASK_HANDLER_PREFIX") + name
    fn = getattr(handlers, fn_name, None)
    if fn is None:
        raise LookupError(fn_name)
    return fn(payload)
