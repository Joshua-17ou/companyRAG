"""
权限过滤引擎
本地权限过滤实现（基于缓存+规则引擎）
"""
from typing import Dict, List, Optional
from src.backend.core.logger import logger

class PermissionFilterEngine:
    """权限过滤引擎"""

    # 权限规则优先级
    RULE_PRIORITY = {
        "own_dept": 1,
        "dept_whitelist": 2,
        "role_whitelist": 2,
        "project_member": 2,
        "user_whitelist": 3,
        "explicit_grant": 4
    }

    @staticmethod
    def check_permission_rules(
        user_perms: Dict,
        chunk_payload: Dict
    ) -> tuple[bool, Optional[str]]:
        """
        检查用户是否有权访问该chunk
        返回: (是否有权, 匹配的规则名称)

        权限规则（最宽松原则）：
        1. 切片归属部门 == 用户部门
        2. 用户部门 ∈ 切片.visible_to_depts
        3. 用户角色 ∈ 切片.visible_to_roles
        4. 用户ID ∈ 切片.visible_to_users
        5. 用户参与的项目 ∩ 切片.project_ids ≠ ∅
        6. 文档被显式授权给该用户（在应用层处理）
        """

        # 必须满足：密级过滤
        chunk_security_level = chunk_payload.get("security_level", 1)
        user_max_level = user_perms.get("max_security_level", 1)

        if chunk_security_level > user_max_level:
            return False, "security_level_denied"

        user_dept = user_perms.get("department")
        user_roles = user_perms.get("roles", [])
        user_projects = user_perms.get("projects", [])

        # 规则1：归属本部门
        chunk_owner_dept = chunk_payload.get("owner_dept")
        if chunk_owner_dept and chunk_owner_dept == user_dept:
            return True, "own_dept"

        # 规则2：部门白名单
        visible_to_depts = chunk_payload.get("visible_to_depts", [])
        if user_dept in visible_to_depts:
            return True, "dept_whitelist"

        # 规则3：角色白名单
        visible_to_roles = chunk_payload.get("visible_to_roles", [])
        for role in user_roles:
            if role in visible_to_roles:
                return True, "role_whitelist"

        # 规则5：项目匹配
        chunk_project_ids = chunk_payload.get("project_ids", [])
        for project_id in user_projects:
            if project_id in chunk_project_ids:
                return True, "project_member"

        # 规则4：用户白名单
        user_id = user_perms.get("user_id")
        visible_to_users = chunk_payload.get("visible_to_users", [])
        if str(user_id) in [str(uid) for uid in visible_to_users]:
            return True, "user_whitelist"

        # 规则6：显式授权（在应用层数据库查询处理）
        # 这里不处理，由调用者在doc_visible_to_users表中检查

        return False, None

    @staticmethod
    def filter_chunks_by_permission(
        user_perms: Dict,
        chunks: List[Dict],
        top_k: int = 5
    ) -> tuple[List[Dict], Dict]:
        """
        按权限过滤chunks
        返回: (过滤后的chunks, 统计信息)
        """
        filtered_chunks = []
        denied_count = 0
        deny_reasons = {}

        for chunk in chunks:
            has_permission, rule_name = PermissionFilterEngine.check_permission_rules(
                user_perms,
                chunk.get("payload", {})
            )

            if has_permission:
                filtered_chunks.append(chunk)
                if len(filtered_chunks) >= top_k:
                    break
            else:
                denied_count += 1
                reason = rule_name or "unknown"
                deny_reasons[reason] = deny_reasons.get(reason, 0) + 1

        stats = {
            "total_input": len(chunks),
            "total_output": len(filtered_chunks),
            "denied_count": denied_count,
            "deny_reasons": deny_reasons
        }

        return filtered_chunks, stats

    @staticmethod
    def validate_permission_context(user_perms: Dict) -> bool:
        """
        验证用户权限上下文的完整性
        """
        required_keys = ["user_id", "department", "roles", "max_security_level"]
        for key in required_keys:
            if key not in user_perms or user_perms[key] is None:
                logger.warning(f"权限上下文缺少必要字段: {key}")
                return False

        if not isinstance(user_perms["roles"], (list, tuple)):
            logger.warning("roles字段必须是list或tuple")
            return False

        if not isinstance(user_perms["projects"], (list, tuple)):
            logger.warning("projects字段必须是list或tuple")
            return False

        return True
