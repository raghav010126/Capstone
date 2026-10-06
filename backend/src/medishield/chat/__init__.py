"""Role-aware assistant: questions about policies, cases and operations, answered with citations.

Access follows the same permission matrix as the API (``api.security.PERMISSIONS``), enforced where the data is read: the
policy search, the case tools and a per-request read-only analytics database. The router only chooses the path and words the
refusal; it is not the security boundary.
"""
