from sqlalchemy import Column, Integer, String, Text, Index
from app.db.base_class import Base

class QueryLog(Base):
    __tablename__ = 'query_logs'

    id = Column(Integer, primary_key=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    sources = Column(String, nullable=True)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    response_time_ms = Column(Integer)

    __table_args__ = (
        # По времени ответа (для анализа производительности)
        Index('ix_query_logs_response_time_ms', response_time_ms),
        # Для эффективной пагинации медленных запросов
        Index('ix_query_logs_slowest', response_time_ms.desc(), id.desc()),
        # Индекс по дате создания — для выборок последних логов/очисток по времени
        Index('ix_query_logs_created_at', 'created_at'),
    )