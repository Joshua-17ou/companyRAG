"""
Streamlit前端 - RAG知识库问答系统
"""
import streamlit as st
import sys
import os
import json
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root.parent))

from src.backend.agent.qa_agent import RAGQAAgent
from src.backend.core.logger import logger


def init_session_state():
    """初始化Streamlit session state"""
    # 初始化用户部门
    if "user_dept" not in st.session_state:
        st.session_state.user_dept = None

    if "agent" not in st.session_state:
        st.session_state.agent = RAGQAAgent(
            api_base=st.session_state.get("api_base", "http://localhost:8000"),
            user_dept=st.session_state.user_dept
        )

    # 加载图片URL映射表
    if "image_mapping" not in st.session_state:
        mapping_file = Path(__file__).parent / ".image_mapping.json"
        if mapping_file.exists():
            import json
            with open(mapping_file, "r", encoding="utf-8") as f:
                st.session_state.image_mapping = json.load(f)
        else:
            st.session_state.image_mapping = {}

    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "api_base" not in st.session_state:
        st.session_state.api_base = "http://localhost:8000"


def render_message(role: str, content: str):
    """渲染消息"""
    if role == "user":
        with st.chat_message("user", avatar="👤"):
            st.write(content)
    else:
        with st.chat_message("assistant", avatar="🤖"):
            st.write(content)


def show_knowledge_base_page(api_base: str):
    """知识库管理页面"""
    st.header("📚 知识库管理")

    import requests

    # 获取统计信息
    try:
        stats_response = requests.get(
            f"{api_base}/api/knowledge-base/stats",
            timeout=10
        )
        stats = stats_response.json() if stats_response.status_code == 200 else {}
    except Exception as e:
        st.error(f"❌ 获取统计信息失败: {str(e)}")
        stats = {}

    # 显示统计面板
    if stats.get("status") == "success":
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("📄 总文件数", stats.get("total_files", 0))
        with col2:
            st.metric("📦 总Chunk数", stats.get("total_chunks", 0))
        with col3:
            st.metric("🖼️ 总图片数", stats.get("total_images", 0))
        with col4:
            st.metric("💾 总大小(MB)", stats.get("total_size_mb", 0))
        with col5:
            st.metric("📊 平均Chunk数", round(stats.get("avg_chunks_per_file", 0), 1))

    st.markdown("---")

    # 获取文件列表
    files = stats.get("files", [])
    if files:
        st.subheader(f"📋 文件列表 ({len(files)} 个)")

        # 创建表格数据
        cols = st.columns([2, 1, 1, 1, 1, 0.5])
        with cols[0]:
            st.write("**文件名**")
        with cols[1]:
            st.write("**Chunks**")
        with cols[2]:
            st.write("**图片**")
        with cols[3]:
            st.write("**医院**")
        with cols[4]:
            st.write("**类型**")
        with cols[5]:
            st.write("**操作**")

        st.divider()

        # 显示每个文件
        for file_info in files:
            cols = st.columns([2, 1, 1, 1, 1, 0.5])
            with cols[0]:
                st.write(file_info.get("filename", "未知"))
            with cols[1]:
                st.write(str(file_info.get("chunks", 0)))
            with cols[2]:
                image_count = file_info.get("images", 0)
                st.write(f"{image_count} 张" if image_count > 0 else "-")
            with cols[3]:
                hospital = file_info.get("hospital", "-")
                st.write(hospital if hospital else "-")
            with cols[4]:
                source_type = file_info.get("source_type", "document")
                type_display = "医院" if source_type == "hospital" else "文档"
                st.write(type_display)
            with cols[5]:
                if st.button("🗑️", key=f"delete_{file_info.get('id')}"):
                    # 删除文件
                    try:
                        with st.spinner("删除中..."):
                            delete_response = requests.delete(
                                f"{api_base}/api/knowledge-base/{file_info.get('id')}",
                                timeout=60
                            )
                            if delete_response.status_code == 200:
                                st.success(f"✅ 已删除: {file_info.get('filename')}")
                                st.rerun()
                            else:
                                st.error(f"❌ 删除失败")
                    except Exception as e:
                        st.error(f"❌ 删除出错: {str(e)}")
    else:
        st.info("📭 知识库为空，请上传文档")

    st.markdown("---")

    # 刷新按钮
    if st.button("🔄 刷新", width='stretch'):
        st.rerun()



def main():
    """主程序"""
    st.set_page_config(
        page_title="RAG知识库问答系统",
        page_icon="🤖",
        layout="wide"
    )

    st.title("🤖 RAG知识库问答系统")

    # 初始化session state（必须在任何访问 session_state 之前）
    init_session_state()

    # 初始化当前页面
    if "current_page" not in st.session_state:
        st.session_state.current_page = "对话"

    # 页面选择标签
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("💬 对话", width='stretch'):
            st.session_state.current_page = "对话"
    with col2:
        if st.button("📚 知识库管理", width='stretch'):
            st.session_state.current_page = "知识库"

    st.markdown("---")

    # 侧边栏配置
    with st.sidebar:
        st.header("⚙️ 配置")

        # 用户部门选择
        st.subheader("👤 用户信息")
        if st.session_state.user_dept is None:
            dept = st.selectbox(
                "选择部门",
                ["销售", "财务", "行政"],
                key="dept_selector",
                help="选择你所属的部门，用于权限控制"
            )

            if st.button("🔐 登录", key="login_btn"):
                st.session_state.user_dept = dept
                # 重新初始化 agent 带上部门信息
                st.session_state.agent = RAGQAAgent(
                    api_base=st.session_state.get("api_base", "http://localhost:8000"),
                    user_dept=dept
                )
                st.rerun()
        else:
            st.success(f"✅ 当前部门：**{st.session_state.user_dept}**")
            if st.button("🔄 切换部门", key="logout_btn"):
                st.session_state.user_dept = None
                # 重新初始化 agent 清除部门信息
                st.session_state.agent = RAGQAAgent(
                    api_base=st.session_state.get("api_base", "http://localhost:8000"),
                    user_dept=None
                )
                st.rerun()

        st.markdown("---")

        # API地址设置
        api_base = st.text_input(
            "API地址",
            value="http://localhost:8000",
            help="RAG后端API的基础地址"
        )

        if api_base != st.session_state.get("api_base", "http://localhost:8000"):
            st.session_state.api_base = api_base
            st.session_state.agent = RAGQAAgent(api_base=api_base)
            st.rerun()

        st.markdown("---")
        st.subheader("📤 上传文档")
        uploaded_file = st.file_uploader(
            "选择文件 (PDF, Markdown, TXT)",
            type=["pdf", "md", "markdown", "txt"],
            help="上传文档到知识库"
        )

        if uploaded_file:
            if st.button("⬆️ 上传", width='stretch'):
                try:
                    with st.spinner("上传中..."):
                        import requests
                        files = {"file": uploaded_file}
                        response = requests.post(
                            f"{st.session_state.api_base}/api/ingest/file",
                            files=files,
                            timeout=60
                        )
                        response.raise_for_status()
                    st.success(f"✅ {uploaded_file.name} 上传成功！")
                    st.session_state.current_page = "知识库"
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 上传失败: {str(e)}")

        st.markdown("---")

        # 清空对话历史
        if st.button("🗑️ 清空对话", width='stretch'):
            st.session_state.messages = []
            st.session_state.agent.reset_conversation()
            st.success("对话已清空")
            st.rerun()

        st.markdown("---")

        # 会话统计信息
        st.subheader("📊 会话统计")
        try:
            stats = st.session_state.agent.get_conversation_stats()
            col1, col2 = st.columns(2)
            with col1:
                st.metric("对话轮次", stats['turns'])
                st.metric("总消息数", stats['total_messages'])
            with col2:
                st.metric("用户消息", stats['user_messages'])
                st.metric("助手消息", stats['assistant_messages'])

            # 显示摘要信息
            if stats['has_summary']:
                with st.expander("📝 历史对话摘要", expanded=False):
                    st.info(f"摘要长度: {stats['summary_length']} 字符")
                    st.write(st.session_state.agent.conversation_summary)
                    st.caption("💡 为节省 Token，早期对话已被压缩为摘要")
            else:
                st.caption(f"💡 保留最近 {st.session_state.agent.max_recent_turns} 轮完整对话")
        except Exception as e:
            st.caption(f"⚠️ 无法获取统计: {str(e)}")

        st.markdown("---")
        st.markdown("""
        ### 使用指南
        1. 在下方输入框输入问题
        2. Agent会自动搜索相关文档并生成答案
        3. 支持多轮对话，自动管理上下文
        4. 使用"清空对话"按钮重新开始
        """)

        st.markdown("---")
        st.markdown("""
        ### 功能说明
        - **搜索文档**: 从知识库中搜索相关内容
        - **生成答案**: 基于检索结果用LLM生成回答
        - **智能记忆**: 自动压缩历史对话，保留关键上下文
        - **多轮对话**: 维护对话上下文，节省Token成本
        """)

    # 根据当前页面显示不同的内容
    if st.session_state.current_page == "对话":
        show_chat_page()
    else:
        show_knowledge_base_page(st.session_state.api_base)


def get_local_image_path(img_url: str) -> str:
    """
    根据外部URL获取本地图片路径
    ProcessOn CDN URL -> 本地文件
    """
    # 使用映射表查找
    image_mapping = st.session_state.get("image_mapping", {})
    if img_url in image_mapping:
        return image_mapping[img_url]

    # 如果已经是本地路径，直接返回
    if not img_url.startswith('http'):
        return img_url

    # 尝试从URL中提取ID并构造本地路径
    if 'processon.com' in img_url:
        file_id = img_url.split('/')[-1]
        return f"docs/images/{file_id}.png"

    return img_url




def get_local_image_path(img_url: str) -> str:
    """根据外部URL获取本地图片路径"""
    if not img_url:
        return ""
    
    # 如果已经是本地路径
    if not img_url.startswith('http'):
        return img_url if img_url.startswith('docs/') else f"docs/{img_url}"
    
    # ProcessOn CDN URL -> 本地文件
    if 'processon.com' in img_url and 'wps' in img_url:
        file_id = img_url.split('/')[-1]
        return f"docs/images/{file_id}.png"
    
    return img_url


def show_chat_page():
    """对话页面"""
    # 显示对话历史
    for message in st.session_state.messages:
        render_message(message["role"], message["content"])

    # 用户输入
    if user_input := st.chat_input("输入你的问题..."):
        # 显示用户消息
        render_message("user", user_input)
        st.session_state.messages.append({
            "role": "user",
            "content": user_input
        })

        # 生成回复
        try:
            with st.chat_message("assistant", avatar="🤖"):
                # 创建思考过程容器和结果容器
                thinking_placeholder = st.empty()
                result_placeholder = st.empty()

                with st.spinner("🤔 正在生成答案..."):
                    import requests
                    try:
                        # 构建请求参数
                        params = {"query": user_input, "top_k": 3}

                        # 传递用户部门信息
                        if st.session_state.user_dept:
                            params["user_dept"] = st.session_state.user_dept

                        qa_response = requests.post(
                            f"{st.session_state.api_base}/api/qa",
                            params=params,
                            timeout=30
                        )
                        qa_response.raise_for_status()
                        response_data = qa_response.json()

                        # 转换为兼容的格式
                        if response_data.get("status") == "success":
                            response_data = {
                                "status": "success",
                                "thoughts": [],
                                "answer": response_data.get("answer", ""),
                                "is_final": True,
                                "sources": response_data.get("sources", []),
                                "images": response_data.get("images", [])
                            }
                        else:
                            response_data = {
                                "status": "error",
                                "answer": "生成答案失败",
                                "is_final": True
                            }
                    except Exception as e:
                        response_data = {
                            "status": "error",
                            "answer": f"生成答案出错: {str(e)}",
                            "is_final": True
                        }

                # 类型检查：兼容字符串和字典返回
                if isinstance(response_data, str):
                    response_data = {
                        "status": "success",
                        "thoughts": [],
                        "answer": response_data,
                        "is_final": True
                    }

                if response_data.get("status") == "error":
                    st.error(f"❌ {response_data.get('answer')}")
                else:
                    # 显示思考过程（展开状态）
                    thoughts = response_data.get("thoughts", [])

                    if thoughts:
                        with thinking_placeholder.container():
                            with st.expander("🤔 Agent思考过程", expanded=True):
                                for thought in thoughts:
                                    step = thought.get("step", "")
                                    thought_type = thought.get("type", "")

                                    if thought_type == "thinking":
                                        st.markdown(f"**第{step}步 - 思考：**")
                                        st.write(thought.get("content", ""))

                                    elif thought_type == "tool_call":
                                        tool = thought.get("tool", "")
                                        input_data = thought.get("input", {})
                                        st.markdown(f"**第{step}步 - 🔧 调用工具 `{tool}`**")
                                        with st.expander("📋 查看参数", expanded=False):
                                            st.json(input_data)

                                    elif thought_type == "tool_result":
                                        tool = thought.get("tool", "")
                                        content = thought.get("content", "")
                                        st.markdown(f"**第{step}步 - 📊 工具结果 `{tool}`**")
                                        with st.expander("📋 查看结果", expanded=False):
                                            st.write(content)

                                st.divider()

                            # 思考完毕后自动折叠expander
                            st.session_state.thinking_collapsed = True

                    # 流式显示最终答案
                    answer = response_data.get("answer", "")

                    with result_placeholder.container():
                        st.markdown("### 💡 最终答案")

                        # 解析答案中的markdown图片并渲染
                        if answer:
                            import re
                            # 分割答案文本，提取markdown图片
                            parts = re.split(r'(!\[([^\]]*)\]\(([^)]+)\))', answer)

                            for i, part in enumerate(parts):
                                if i % 4 == 0:  # 普通文本
                                    if part:
                                        st.markdown(part)
                                elif i % 4 == 3:  # 图片URL部分
                                    if part:
                                        # 将相对路径转换为完整URL
                                        if part.startswith('/api/'):
                                            img_url = f"{st.session_state.api_base}{part}"
                                        elif not part.startswith('http'):
                                            img_url = f"{st.session_state.api_base}/api/images/{part.split('/')[-1]}"
                                        else:
                                            img_url = part
                                        st.image(img_url, width='stretch')

                        # 显示来源信息
                        sources = response_data.get("sources", [])
                        if sources:
                            st.divider()
                            st.markdown("### 📚 来源文档")
                            for i, source in enumerate(sources, 1):
                                with st.expander(f"📄 来源 {i}: {source.get('filename', '未知')}"):
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        st.write(f"**文件名**: {source.get('filename', '未知')}")
                                        st.write(f"**医院**: {source.get('hospital', '-')}")
                                    with col2:
                                        st.write(f"**类型**: {source.get('source_type', 'document')}")
                                        st.write(f"**相关性**: {source.get('score', 0.0):.2%}")

                                    # 显示源文本
                                    st.write("**内容摘要**:")

                                    # 解析并显示文本中的图片
                                    text = source.get('text', '')
                                    if text:
                                        # 按照[alt](url)的markdown链接格式分割文本
                                        import re
                                        parts = re.split(r'(\[([^\]]*)\]\(([^)]+)\))', text)

                                        for i, part in enumerate(parts):
                                            if i % 4 == 0:  # 普通文本
                                                if part:
                                                    st.markdown(part)
                                            elif i % 4 == 3:  # URL部分
                                                # 检查是否是图片URL
                                                if part and ('processon.com' in part or part.endswith(('.png', '.jpg', '.jpeg', '.gif'))):
                                                    # 这是图片，用API路由显示它
                                                    api_url = f"{st.session_state.api_base}/api/images/{part.split('/')[-1]}" if not part.startswith('http') else part
                                                    st.image(api_url, width='stretch')

                        # 显示相关图片
                                    images = source.get('images', [])
                                    if images:
                                        st.write(f"**相关图片** ({len(images)} 张):")
                                        img_cols = st.columns(min(3, len(images)))
                                        for idx, img in enumerate(images):
                                            with img_cols[idx % 3]:
                                                img_url = img.get('url', '')
                                                if img_url:
                                                    # 转换相对URL为完整URL
                                                    if img_url.startswith('/api/'):
                                                        full_img_url = f"{st.session_state.api_base}{img_url}"
                                                    else:
                                                        full_img_url = img_url
                                                    st.image(full_img_url, width='stretch')
                                                    if img.get('description'):
                                                        st.caption(img.get('description')[:100])


            # 保存到消息历史
            st.session_state.messages.append({
                "role": "assistant",
                "content": response_data.get("answer", "")
            })

        except Exception as e:
            st.error(f"❌ 出错了: {str(e)}")
            logger.error(f"Chat error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
