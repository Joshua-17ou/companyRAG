"""
医院级别的搜索结果过滤和排序
支持医院名称识别、结果过滤和分组
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Dict, Optional

if TYPE_CHECKING:
    from llama_index.core.schema import TextNode

from src.backend.core.logger import logger
from src.backend.ingestion.hospital_mapping import (
    normalize_hospital_name,
    get_hospital_info,
    HOSPITAL_MAPPING
)


class HospitalFilter:
    """医院级别的搜索结果过滤器"""

    @staticmethod
    def filter_by_hospital(
        nodes: List[TextNode],
        target_hospital: str,
        strict: bool = False
    ) -> List[TextNode]:
        """
        按医院过滤搜索结果

        Args:
            nodes: 搜索结果节点列表
            target_hospital: 目标医院名称（规范化的标准名）
            strict: 过滤模式
                True: 严格过滤，只返回目标医院的结果
                      如果没有目标医院的结果，返回空列表
                False: 软过滤，优先返回目标医院，其他医院降序
                      如果没有目标医院的结果，返回所有结果

        Returns:
            过滤后的节点列表
        """
        if not target_hospital or not nodes:
            return nodes

        # 规范化目标医院名
        normalized_hospital = normalize_hospital_name(target_hospital)
        if not normalized_hospital:
            logger.warning(f"Unknown hospital name: {target_hospital}")
            return nodes

        logger.info(f"Filtering results by hospital: {normalized_hospital}")

        # 分离出目标医院和其他医院的结果
        hospital_matched = []
        hospital_unmatched = []

        for node in nodes:
            node_hospital = normalize_hospital_name(node.metadata.get("hospital"))

            if node_hospital == normalized_hospital:
                hospital_matched.append(node)
            else:
                hospital_unmatched.append(node)

        logger.info(
            f"Hospital filter result: "
            f"{len(hospital_matched)} matched, "
            f"{len(hospital_unmatched)} unmatched"
        )

        # 根据过滤模式返回结果
        if strict:
            # 严格模式：只返回目标医院的结果
            if hospital_matched:
                logger.info(f"Strict mode: returning {len(hospital_matched)} results for '{normalized_hospital}'")
                return hospital_matched
            else:
                logger.warning(
                    f"Strict mode: no results found for hospital '{normalized_hospital}', "
                    f"returning empty list"
                )
                return []
        else:
            # 软过滤模式：优先返回目标医院，其他医院降序
            if hospital_matched:
                logger.info(f"Soft mode: returning {len(hospital_matched)} matched + {len(hospital_unmatched)} fallback results")
                return hospital_matched + hospital_unmatched
            else:
                logger.warning(
                    f"Soft mode: no results for '{normalized_hospital}', "
                    f"falling back to all {len(hospital_unmatched)} results"
                )
                return hospital_unmatched

    @staticmethod
    def group_by_hospital(nodes: List[TextNode]) -> Dict[str, List[TextNode]]:
        """
        按医院分组搜索结果

        Args:
            nodes: 搜索结果节点列表

        Returns:
            {医院名: [node, node, ...], ...}
        """
        groups = {}
        for node in nodes:
            hospital = node.metadata.get("hospital", "未分类")
            if hospital not in groups:
                groups[hospital] = []
            groups[hospital].append(node)

        return groups

    @staticmethod
    def get_hospital_summary(nodes: List[TextNode]) -> Dict:
        """
        获取搜索结果中医院的统计信息

        Returns:
            {
                "total": 总结果数,
                "hospitals": {
                    "医院名": {
                        "count": 结果数,
                        "info": 医院详情
                    },
                    ...
                }
            }
        """
        groups = HospitalFilter.group_by_hospital(nodes)

        result = {
            "total": len(nodes),
            "hospitals": {}
        }

        for hospital_name, hospital_nodes in groups.items():
            hospital_info = get_hospital_info(hospital_name)
            result["hospitals"][hospital_name] = {
                "count": len(hospital_nodes),
                "info": hospital_info
            }

        return result

    @staticmethod
    def filter_and_log(
        nodes: List[TextNode],
        target_hospital: str,
        strict: bool = False,
        verbose: bool = True
    ) -> List[TextNode]:
        """
        过滤结果并记录详细信息

        Args:
            nodes: 搜索结果
            target_hospital: 目标医院
            strict: 是否严格过滤
            verbose: 是否输出详细日志

        Returns:
            过滤后的结果
        """
        if verbose:
            summary_before = HospitalFilter.get_hospital_summary(nodes)
            logger.info(f"Before filtering - Total: {summary_before['total']} results")
            for hospital, stats in summary_before["hospitals"].items():
                logger.info(f"  - {hospital}: {stats['count']} results")

        filtered_nodes = HospitalFilter.filter_by_hospital(
            nodes,
            target_hospital,
            strict=strict
        )

        if verbose:
            summary_after = HospitalFilter.get_hospital_summary(filtered_nodes)
            logger.info(f"After filtering - Total: {summary_after['total']} results")
            for hospital, stats in summary_after["hospitals"].items():
                logger.info(f"  - {hospital}: {stats['count']} results")

        return filtered_nodes
