import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from db import Base


class File(Base):
    __tablename__ = "files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_username = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    content_type = Column(String)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # CSV das localizações onde o ficheiro está replicado.
    # Mais simples que uma tabela `file_replicas` separada e suficiente para N=2.
    locations = Column(String, nullable=False, default="primary,replica")