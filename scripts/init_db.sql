-- PostgreSQL Schema初始化脚本

-- 用户表
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(64) NOT NULL,
  email VARCHAR(128) UNIQUE NOT NULL,
  department VARCHAR(64) NOT NULL,
  role VARCHAR(64) NOT NULL,
  max_security_level INT DEFAULT 2,
  status VARCHAR(20) DEFAULT 'active',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 项目表（跨部门协作空间）
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(128) NOT NULL,
  description TEXT,
  start_date DATE,
  end_date DATE,
  status VARCHAR(20) DEFAULT 'active',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 项目成员表
CREATE TABLE project_members (
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  role_in_project VARCHAR(64),
  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (project_id, user_id)
);

-- 文档表
CREATE TABLE documents (
  id VARCHAR(64) PRIMARY KEY,
  title VARCHAR(255),
  version INT DEFAULT 1,
  parent_doc_id VARCHAR(64),
  status VARCHAR(20) DEFAULT 'active',
  owner_dept VARCHAR(64),
  security_level INT DEFAULT 2,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  created_by UUID REFERENCES users(id),
  UNIQUE(id, version)
);

-- 文档-用户显式授权表
CREATE TABLE doc_visible_to_users (
  doc_id VARCHAR(64),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  granted_by UUID REFERENCES users(id),
  granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP,
  PRIMARY KEY (doc_id, user_id)
);

-- 用户权限缓存表（Redis预热数据源）
CREATE TABLE user_permission_cache (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  departments JSONB,
  roles JSONB,
  projects JSONB,
  max_security_level INT,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  cache_version INT DEFAULT 1
);

-- 审计日志表
CREATE TABLE audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  query TEXT,
  query_type VARCHAR(32),
  recalled_docs INT,
  filtered_docs INT,
  final_docs INT,
  answer TEXT,
  feedback VARCHAR(20),
  response_time_ms INT,
  model_used VARCHAR(32),
  token_usage INT,
  cost_cents INT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 知识库文件表 - 记录已入库文档的元数据
CREATE TABLE knowledge_base_files (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  filename VARCHAR(255) NOT NULL,
  original_file_path VARCHAR(512) NOT NULL,
  file_hash VARCHAR(64) NOT NULL UNIQUE,
  file_size INTEGER NOT NULL,
  total_chunks INTEGER DEFAULT 0,
  image_count INTEGER DEFAULT 0,
  source_type VARCHAR(64) DEFAULT 'document',
  chunk_strategy VARCHAR(64) DEFAULT 'character',
  chunk_strategy_version VARCHAR(64),
  chunk_size INTEGER,
  chunk_overlap INTEGER,
  hospital_name VARCHAR(255),
  metadata_json JSONB,
  status VARCHAR(20) DEFAULT 'active',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP
);

-- 搜索日志表 - 记录用户搜索和返回的信息
CREATE TABLE search_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  query TEXT NOT NULL,
  source_file_id UUID REFERENCES knowledge_base_files(id) ON DELETE CASCADE,
  result_count INTEGER DEFAULT 0,
  image_count INTEGER DEFAULT 0,
  response_time_ms INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 图片映射表 - 关联图片到源文件和chunk
CREATE TABLE image_mappings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_file_id UUID NOT NULL REFERENCES knowledge_base_files(id) ON DELETE CASCADE,
  image_path VARCHAR(512) NOT NULL UNIQUE,
  chunk_index INTEGER,
  image_description TEXT,
  image_url VARCHAR(512),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建索引
CREATE INDEX idx_users_department ON users(department);
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_status ON users(status);

CREATE INDEX idx_projects_status ON projects(status);

CREATE INDEX idx_documents_owner_dept ON documents(owner_dept);
CREATE INDEX idx_documents_security_level ON documents(security_level);
CREATE INDEX idx_documents_status ON documents(status);

CREATE INDEX idx_doc_visible_expires_at ON doc_visible_to_users(expires_at);

CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX idx_audit_logs_query_type ON audit_logs(query_type);

CREATE INDEX idx_knowledge_base_files_filename ON knowledge_base_files(filename);
CREATE INDEX idx_knowledge_base_files_file_hash ON knowledge_base_files(file_hash);
CREATE INDEX idx_knowledge_base_files_status ON knowledge_base_files(status);
CREATE INDEX idx_knowledge_base_files_hospital ON knowledge_base_files(hospital_name);
CREATE INDEX idx_knowledge_base_files_created_at ON knowledge_base_files(created_at);

CREATE INDEX idx_search_logs_user_id ON search_logs(user_id);
CREATE INDEX idx_search_logs_created_at ON search_logs(created_at);
CREATE INDEX idx_search_logs_source_file ON search_logs(source_file_id);

CREATE INDEX idx_image_mappings_source_file ON image_mappings(source_file_id);
CREATE INDEX idx_image_mappings_image_path ON image_mappings(image_path);

-- 创建视图：用户权限上下文
CREATE VIEW user_permission_context AS
SELECT
  u.id as user_id,
  u.name,
  u.email,
  u.department,
  u.role,
  u.max_security_level,
  COALESCE(ARRAY_AGG(DISTINCT pm.project_id) FILTER (WHERE pm.project_id IS NOT NULL), '{}') as project_ids
FROM users u
LEFT JOIN project_members pm ON u.id = pm.user_id AND pm.project_id IN (
  SELECT id FROM projects WHERE status = 'active'
)
WHERE u.status = 'active'
GROUP BY u.id, u.name, u.email, u.department, u.role, u.max_security_level;

GRANT CONNECT ON DATABASE knowledge_base TO admin;
GRANT USAGE ON SCHEMA public TO admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO admin;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO admin;
