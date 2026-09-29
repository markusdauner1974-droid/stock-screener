"""Fencing generations for Redis workload leases (see tasks/workload_fence)."""
from sqlalchemy import BigInteger, Column, String

from ..database import Base


class WorkloadFence(Base):
    """Latest lease generation per workload key; older holders may not commit."""

    __tablename__ = "workload_fences"

    key = Column(String(128), primary_key=True)
    generation = Column(BigInteger, nullable=False)
