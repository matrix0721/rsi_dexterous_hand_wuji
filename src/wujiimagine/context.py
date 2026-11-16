"""The same controller interface for in-process and persistent HTTP sessions."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

METHODS = ("status", "skills", "observe", "pixel_to_world", "world", "world_state",
           "plan_grasp", "imagine", "execute", "compare", "learn_dynamics", "remember",
           "references", "operation", "check", "freeze")


class Context:
    def __init__(self, session=None, timeout=300):
        self.timeout = timeout
        self.local = session if session is not None and not isinstance(session, (str, Path)) else None
        if self.local is None:
            path = session or os.environ.get("WUJIIMAGINE_SESSION")
            if not path:
                raise ValueError("pass session.json or set WUJIIMAGINE_SESSION")
            self.descriptor = json.loads(Path(path).read_text(encoding="utf-8"))

    def call(self, method, **params):
        if method not in METHODS:
            raise ValueError(f"unknown tool: {method}")
        if self.local is not None:
            return getattr(self.local, method)(**params)
        request = urllib.request.Request(self.descriptor["url"] + "/call",
                  data=json.dumps({"method": method, "params": params}, allow_nan=False).encode(),
                  headers={"Content-Type": "application/json",
                           "Authorization": "Bearer " + self.descriptor["token"]})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(detail) from exc
        # No retries: transport failure does not mean a motion was unexecuted.
        return result

    def __getattr__(self, name):
        if name == "skill":
            return lambda name: self.call("skills", name=name)
        if name in METHODS:
            # Match the common positional controller calls while RPC uses named arguments.
            first = {"skills": "name", "pixel_to_world": "pixel", "imagine": "actions",
                     "execute": "actions", "compare": "prediction", "learn_dynamics": "prediction",
                     "remember": "text", "operation": "action", "check": "condition", "freeze": "controller"}
            def invoke(*args, **kwargs):
                if args:
                    if len(args) != 1 or name not in first or first[name] in kwargs:
                        raise TypeError("use named arguments for this tool")
                    kwargs[first[name]] = args[0]
                return self.call(name, **kwargs)
            return invoke
        raise AttributeError(name)
