"""
创建会话表的数据库迁移脚本
"""
from sqlalchemy import text
from src.backend.db.database import engine

def upgrade():
    """创建会话表"""
    with engine.connect() as conn:
        # 创建会话表
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                title VARCHAR(200) NOT NULL DEFAULT '新对话',
                user_dept VARCHAR(64) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """))

        # 创建索引
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_dept
            ON chat_sessions(user_dept);
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at
            ON chat_sessions(updated_at DESC);
        """))

        # 创建消息表
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                sources JSONB,
                images JSONB,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """))

        # 创建索引
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
            ON chat_messages(session_id);
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at
            ON chat_messages(created_at);
        """))

        conn.commit()
        print("✅ 会话表创建成功")

def downgrade():
    """删除会话表"""
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS chat_messages CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS chat_sessions CASCADE;"))
        conn.commit()
        print("✅ 会话表删除成功")

if __name__ == "__main__":
    print("=== 开始创建会话表 ===")
    upgrade()
    print("=== 完成 ===")
