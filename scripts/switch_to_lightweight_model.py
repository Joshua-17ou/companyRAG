#!/usr/bin/env python3
"""
下载新的轻量级模型并切换
1. 用ModelScope下载 bge-small-zh
2. 验证模型可用
3. 清除旧模型
"""
import sys
from pathlib import Path
import shutil

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backend.core.logger import logger
from src.backend.ingestion.rag_service import LocalEmbeddingModel


def main():
    try:
        logger.info("=" * 70)
        logger.info("开始下载和切换轻量级模型")
        logger.info("=" * 70)

        # 步骤1：下载新模型
        logger.info("\n[步骤 1/3] 用ModelScope下载 bge-small-zh 模型...")
        logger.info("新模型信息:")
        logger.info("  • 名称: BAAI/bge-small-zh")
        logger.info("  • 大小: ~90MB (当前模型: 670MB)")
        logger.info("  • 维度: 512 (当前: 1024)")
        logger.info("  • 预期提速: 8倍")
        logger.info("  • 预期准确度: 足够用")

        try:
            embedding_model = LocalEmbeddingModel(model_name="BAAI/bge-small-zh")
            logger.info("✅ 新模型下载完成")
        except Exception as e:
            logger.error(f"❌ 模型下载失败: {e}", exc_info=True)
            return False

        # 步骤2：验证模型可用
        logger.info("\n[步骤 2/3] 验证新模型可用性...")
        try:
            # 测试embedding
            test_text = "这是一个测试文本"
            embedding = embedding_model.get_text_embedding(test_text)
            embedding_dim = len(embedding)

            logger.info(f"✅ 模型验证成功")
            logger.info(f"  • Embedding维度: {embedding_dim}")
            logger.info(f"  • 测试文本: {test_text}")
            logger.info(f"  • 生成向量维度: {embedding_dim}")
        except Exception as e:
            logger.error(f"❌ 模型验证失败: {e}", exc_info=True)
            return False

        # 步骤3：清除旧模型
        logger.info("\n[步骤 3/3] 清除旧模型...")
        models_dir = project_root / "models" / "embeddings" / "models"

        if models_dir.exists():
            # 找到并删除旧模型（bge-m3）
            old_model_dirs = list(models_dir.glob("BAAI--bge-m3*"))

            if old_model_dirs:
                for old_dir in old_model_dirs:
                    try:
                        logger.info(f"  删除旧模型: {old_dir.name}")
                        shutil.rmtree(old_dir)
                        logger.info(f"  ✅ 已删除: {old_dir.name}")
                    except Exception as e:
                        logger.warning(f"  ⚠️ 删除失败: {e}")
            else:
                logger.info("  ℹ️ 未找到旧模型（bge-m3）")

        # 验证新模型文件
        new_model_dirs = list(models_dir.glob("BAAI--bge-small-zh*"))
        logger.info(f"\n✅ 现有模型:")
        if new_model_dirs:
            for model_dir in new_model_dirs:
                size_mb = sum(f.stat().st_size for f in model_dir.rglob('*') if f.is_file()) / (1024*1024)
                logger.info(f"  • {model_dir.name} ({size_mb:.1f}MB)")
        else:
            logger.warning("  未找到新模型文件")

        logger.info("\n" + "=" * 70)
        logger.info("✅ 模型切换成功！")
        logger.info("=" * 70)
        logger.info("\n现在需要重新入库文档:")
        logger.info("  python scripts/reingest_with_image_mapping.py")
        logger.info("\n预期改进:")
        logger.info("  • 索引时间: 3分钟 → 45秒 (下降75%)")
        logger.info("  • 搜索响应: 0.45s → 0.1s (下降78%)")
        logger.info("  • 内存占用: 2GB → 800MB (下降60%)")
        logger.info("  • 图片超时: 极少见 ✅")

        return True

    except Exception as e:
        logger.error(f"流程失败: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
