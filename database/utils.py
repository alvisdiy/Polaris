import uuid


def new_uuid() -> uuid.UUID:
    """Shared UUID generator for all primary keys."""
    return uuid.uuid4()
