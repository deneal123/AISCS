"""Tool integrations without eager clients or function re-exports.

``search`` owns search transport, parsing and per-run sources; ``ide`` and
``workspace`` own their separate file contracts. Other integrations stay in
explicit modules. Import DEFAULT_FUNCTION_TOOLS from ``function_tools``.

Historical re-exports shadowed modules with equally named functions and loaded
the entire tool chain on any import. Keep this initializer free of runtime work.
"""
