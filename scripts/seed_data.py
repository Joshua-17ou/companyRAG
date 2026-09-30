"""
测试数据生成脚本
生成用户、部门、项目、权限关系的测试数据
"""
import asyncio
import json
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, insert

from src.backend.core.config import settings
from src.backend.db.models import User, Project, project_members, UserPermissionCache
from src.backend.core.logger import logger

async def generate_test_data():
    """生成测试数据"""

    # 使用asyncpg驱动
    database_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")

    # 创建数据库连接
    engine = create_async_engine(
        database_url,
        echo=False,
        future=True
    )

    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    async with AsyncSessionLocal() as session:
        # 创建用户
        users_data = [
            # 销售部
            {"name": "zhangsan", "email": "zhangsan@example.com", "department": "sales", "role": "specialist", "max_security_level": 2},
            {"name": "lisi", "email": "lisi@example.com", "department": "sales", "role": "director", "max_security_level": 3},
            {"name": "wangwu", "email": "wangwu@example.com", "department": "sales", "role": "manager", "max_security_level": 2},

            # 财务部
            {"name": "zhaoliu", "email": "zhaoliu@example.com", "department": "finance", "role": "specialist", "max_security_level": 3},
            {"name": "sunqi", "email": "sunqi@example.com", "department": "finance", "role": "director", "max_security_level": 4},
            {"name": "zhouba", "email": "zhouba@example.com", "department": "finance", "role": "accountant", "max_security_level": 3},

            # 行政部
            {"name": "wujiu", "email": "wujiu@example.com", "department": "admin", "role": "specialist", "max_security_level": 2},
            {"name": "zhengshi", "email": "zhengshi@example.com", "department": "admin", "role": "supervisor", "max_security_level": 2},

            # CEO
            {"name": "ceo", "email": "ceo@example.com", "department": "management", "role": "ceo", "max_security_level": 4},

            # Project Manager
            {"name": "pm", "email": "pm@example.com", "department": "project", "role": "pm", "max_security_level": 3},
        ]

        users = []
        user_ids = {}
        for user_data in users_data:
            user = User(**user_data, status="active")
            session.add(user)
            users.append(user)
            logger.info(f"Create user: {user_data['name']}")

        await session.flush()

        # Save user IDs
        for user in users:
            user_ids[user.email] = user.id

        # Create projects
        projects_data = [
            {
                "name": "Q3 Project",
                "description": "Cross-department project",
                "start_date": datetime.now(),
                "end_date": datetime.now() + timedelta(days=90),
                "status": "active"
            },
            {
                "name": "Finance System Upgrade",
                "description": "Finance department project",
                "start_date": datetime.now(),
                "end_date": datetime.now() + timedelta(days=60),
                "status": "active"
            },
            {
                "name": "HR Benefits Project",
                "description": "Cross-department HR project",
                "start_date": datetime.now(),
                "end_date": datetime.now() + timedelta(days=30),
                "status": "active"
            },
            {
                "name": "Knowledge Base System",
                "description": "Company-wide knowledge system",
                "start_date": datetime.now(),
                "end_date": datetime.now() + timedelta(days=120),
                "status": "active"
            },
        ]

        projects = []
        project_ids = {}
        for i, proj_data in enumerate(projects_data):
            project = Project(**proj_data)
            session.add(project)
            projects.append(project)
            logger.info(f"Create project: {proj_data['name']}")

        await session.flush()

        # Save project IDs
        for i, project in enumerate(projects):
            project_ids[i] = project.id

        # Set project members
        project_member_data = [
            # Project 1
            (project_ids[0], user_ids["lisi@example.com"]),
            (project_ids[0], user_ids["sunqi@example.com"]),
            (project_ids[0], user_ids["pm@example.com"]),

            # Project 2
            (project_ids[1], user_ids["sunqi@example.com"]),
            (project_ids[1], user_ids["zhouba@example.com"]),

            # Project 3
            (project_ids[2], user_ids["wujiu@example.com"]),
            (project_ids[2], user_ids["sunqi@example.com"]),
            (project_ids[2], user_ids["lisi@example.com"]),
        ]

        # Add project 4 members (all users)
        for user_id in user_ids.values():
            project_member_data.append((project_ids[3], user_id))

        # Batch insert project members
        if project_member_data:
            await session.execute(
                insert(project_members).values([
                    {"project_id": pm[0], "user_id": pm[1]} for pm in project_member_data
                ])
            )

        logger.info("Project members created")

        # Create permission cache records
        for user in users:
            stmt = select(project_members).where(
                project_members.c.user_id == user.id
            )
            result = await session.execute(stmt)
            rows = result.fetchall()
            user_projects = [str(row[0]) for row in rows]

            cache = UserPermissionCache(
                user_id=user.id,
                departments=json.dumps([user.department]),
                roles=json.dumps([user.role]),
                projects=json.dumps(user_projects),
                max_security_level=user.max_security_level
            )
            session.add(cache)
            logger.info(f"Create permission cache: {user.email}")

        await session.commit()
        logger.info("Test data generation completed")
        logger.info(f"  - Users: {len(users)}")
        logger.info(f"  - Projects: {len(projects)}")
        logger.info(f"  - Project members: {len(project_member_data)}")

async def main():
    """Main function"""
    try:
        await generate_test_data()
    except Exception as e:
        logger.error(f"Failed to generate test data: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
