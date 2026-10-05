"""MediShield multi-agent document intake."""

try:  # use the OS trust store (corporate TLS proxies) for model downloads and API calls
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover
    pass
