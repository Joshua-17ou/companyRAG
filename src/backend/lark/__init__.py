"""
飞书（Lark）免登模块 —— 与原网页版解耦

设计原则：
1. 默认关闭。LARK_ENABLED=false 时本模块完全不参与运行，原网页版行为一字不变。
2. 不修改原有数据库结构、不修改原有业务路由代码。
   - 飞书用户复用 users 表，用 `{open_id}@lark.local` 作为唯一 email 作为身份映射
   - 飞书会话复用 chat_sessions.user_dept，用 `lark:{open_id}` 命名空间实现「按用户私有」
3. 只有 3 处对原文件的改动，且全部为附加式、默认不生效：
   - requirements.txt 增加 PyJWT
   - rag_service.py 增加「全员」短路（仅当 user_dept == 全员 时触发，原网页版永不传该值）
   - main.py 增加 install_lark(app) 调用（内部判断开关）

开启方式：.env 里设置 LARK_ENABLED=true 及 LARK_APP_ID / LARK_APP_SECRET / LARK_REDIRECT_URI
"""
from src.backend.lark.config import lark_settings

__all__ = ["lark_settings"]