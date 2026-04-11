"""Optional vector-store adapters for external RAG backends.

All adapters in this package import their backing libraries lazily so that
installing ``shipit_agent`` does not pull in heavy dependencies. Each
adapter raises a clear :class:`RAGDependencyError` when its backend is
unavailable.
"""
