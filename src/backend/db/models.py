"""
SQLAlchemy ORM模型定义
"""
from sqlalchemy import Column, String, Integer, DateTime, UUID, Text, ForeignKey, Boolean, JSON, Table, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import uuid

from src.backend.db.database import Base

# 关联表：项目成员
project_members = Table(
    'project_members',
    Base.metadata,
    Column('project_id', UUID(as_uuid=True), ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True),
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('role_in_project', String(64)),
    Column('joined_at', DateTime, server_default=func.now())
)

class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(64), nullable=False)
    email = Column(String(128), unique=True, nullable=False, index=True)
    department = Column(String(64), nullable=False, index=True)
    role = Column(String(64), nullable=False, index=True)
    max_security_level = Column(Integer, default=2)
    status = Column(String(20), default='active', index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    projects = relationship("Project", secondary=project_members, back_populates="members")
    documents = relationship("Document", back_populates="creator")
    audit_logs = relationship("AuditLog", back_populates="user")

    def __repr__(self):
        return f"<User {self.email}>"


class ChatSession(Base):
    """对话会话表"""
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(200), nullable=False, default="新对话")
    user_dept = Column(String(64), nullable=False, index=True)  # 部门
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # 关系
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at")


class ChatMessage(Base):
    """对话消息表"""
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # 'user' 或 'assistant'
    content = Column(Text, nullable=False)
    sources = Column(JSON, nullable=True)  # 来源文档
    images = Column(JSON, nullable=True)  # 图片信息
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # 关系
    session = relationship("ChatSession", back_populates="messages")

    def __repr__(self):
        return f"<ChatMessage {self.id} ({self.role})>"


class Project(Base):
    """项目表"""
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), nullable=False)
    description = Column(Text)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    status = Column(String(20), default='active')
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    members = relationship("User", secondary=project_members, back_populates="projects")

    def __repr__(self):
        return f"<Project {self.name}>"

class Document(Base):
    """文档表"""
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint('id', 'version', name='uq_doc_version'),
    )

    id = Column(String(64), primary_key=True)
    title = Column(String(255), nullable=False)
    version = Column(Integer, default=1, primary_key=True)
    parent_doc_id = Column(String(64), nullable=True)
    status = Column(String(20), default='active', index=True)
    owner_dept = Column(String(64), nullable=False, index=True)
    security_level = Column(Integer, default=2, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # 关系
    creator = relationship("User", back_populates="documents")

    def __repr__(self):
        return f"<Document {self.id}@v{self.version}>"

class DocVisibleToUser(Base):
    """文档-用户显式授权表"""
    __tablename__ = "doc_visible_to_users"

    doc_id = Column(String(64), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    granted_by = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    granted_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<DocVisibleToUser {self.doc_id} -> {self.user_id}>"

class UserPermissionCache(Base):
    """用户权限缓存表（Redis预热源）"""
    __tablename__ = "user_permission_cache"

    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    departments = Column(JSON, nullable=True)
    roles = Column(JSON, nullable=True)
    projects = Column(JSON, nullable=True)
    max_security_level = Column(Integer)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    cache_version = Column(Integer, default=1)

    def __repr__(self):
        return f"<UserPermissionCache {self.user_id}>"

class AuditLog(Base):
    """审计日志表"""
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    query = Column(Text)
    query_type = Column(String(32))
    recalled_docs = Column(Integer)
    filtered_docs = Column(Integer)
    final_docs = Column(Integer)
    answer = Column(Text)
    feedback = Column(String(20))
    response_time_ms = Column(Integer)
    model_used = Column(String(32))
    token_usage = Column(Integer)
    cost_cents = Column(Integer)
    created_at = Column(DateTime, server_default=func.now(), index=True)

    # 关系
    user = relationship("User", back_populates="audit_logs")

    def __repr__(self):
        return f"<AuditLog {self.id}>"

class KnowledgeBaseFile(Base):
    """知识库文件表 - 记录已入库文档的元数据"""
    __tablename__ = "knowledge_base_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False, index=True)
    original_file_path = Column(String(512), nullable=False)
    file_hash = Column(String(64), nullable=False, unique=True, index=True)
    file_size = Column(Integer, nullable=False)
    total_chunks = Column(Integer, default=0)
    image_count = Column(Integer, default=0)
    source_type = Column(String(64), default='document')  # document, hospital, etc.
    chunk_strategy = Column(String(64), default='character', index=True)
    chunk_strategy_version = Column(String(64), nullable=True)
    chunk_size = Column(Integer, nullable=True)
    chunk_overlap = Column(Integer, nullable=True)
    hospital_name = Column(String(255), nullable=True, index=True)  # 医院名称（如果是医院文件）
    metadata_json = Column(JSON, nullable=True)  # 扩展元数据
    status = Column(String(20), default='active', index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime, nullable=True)

    # 关系
    search_logs = relationship("SearchLog", back_populates="source_file")
    image_mappings = relationship("ImageMapping", back_populates="source_file")

    def __repr__(self):
        return f"<KnowledgeBaseFile {self.filename} ({self.total_chunks} chunks, {self.image_count} images)>"


class SearchLog(Base):
    """搜索日志表 - 记录用户搜索和返回的信息"""
    __tablename__ = "search_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    query = Column(Text, nullable=False)
    source_file_id = Column(UUID(as_uuid=True), ForeignKey('knowledge_base_files.id', ondelete='CASCADE'), nullable=True)
    result_count = Column(Integer, default=0)
    image_count = Column(Integer, default=0)
    response_time_ms = Column(Integer)
    created_at = Column(DateTime, server_default=func.now(), index=True)

    # 关系
    source_file = relationship("KnowledgeBaseFile", back_populates="search_logs")

    def __repr__(self):
        return f"<SearchLog query={self.query[:50]} results={self.result_count}>"


class ImageMapping(Base):
    """图片映射表 - 关联图片到源文件和chunk"""
    __tablename__ = "image_mappings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_file_id = Column(UUID(as_uuid=True), ForeignKey('knowledge_base_files.id', ondelete='CASCADE'), nullable=False, index=True)
    image_path = Column(String(512), nullable=False, unique=True, index=True)
    chunk_index = Column(Integer, nullable=True)  # 所属chunk的索引
    image_description = Column(Text, nullable=True)  # 图片描述（Claude Vision分析结果）
    image_url = Column(String(512), nullable=True)  # 访问URL
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    source_file = relationship("KnowledgeBaseFile", back_populates="image_mappings")

    def __repr__(self):
        return f"<ImageMapping {self.image_path}>"

