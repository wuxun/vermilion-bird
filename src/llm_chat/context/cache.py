import json
import time
import hashlib
import logging
from typing import List, Dict, Any, Optional

from llm_chat.storage import Storage
from .types import CompressionLevel, ContextMessage, ContextCacheEntry

logger = logging.getLogger(__name__)


class ContextCache:
    """持久化上下文缓存，复用现有主数据库"""

    def __init__(self, storage: Optional[Storage] = None):
        self.storage = storage or Storage()

    def _generate_cache_key(
        self,
        conversation_id: str,
        compression_level: CompressionLevel,
        message_hash: str,
    ) -> str:
        """生成缓存键"""
        key_string = f"{conversation_id}:{compression_level.value}:{message_hash}"
        return hashlib.md5(key_string.encode()).hexdigest()

    def _compute_message_hash(self, messages: List[ContextMessage]) -> str:
        """计算消息列表的哈希值，用于缓存匹配"""
        # 只对消息的role和content计算哈希，忽略元数据和时间戳
        hash_content = json.dumps(
            [{"role": msg.role, "content": msg.content} for msg in messages],
            sort_keys=True,
        )
        return hashlib.sha256(hash_content.encode()).hexdigest()

    def get(
        self,
        conversation_id: str,
        compression_level: CompressionLevel,
        messages: Optional[List[ContextMessage]] = None,
        message_hash: Optional[str] = None,
    ) -> Optional[ContextCacheEntry]:
        """
        获取缓存条目
        :param conversation_id: 会话ID
        :param compression_level: 压缩级别
        :param messages: 消息列表，用于计算哈希（二选一：messages或message_hash）
        :param message_hash: 预计算的消息哈希（二选一：messages或message_hash）
        :return: 缓存条目，不存在返回None
        """
        if not message_hash and not messages:
            raise ValueError("必须提供messages或message_hash参数")

        if not message_hash:
            message_hash = self._compute_message_hash(messages)

        cache_key = self._generate_cache_key(
            conversation_id, compression_level, message_hash
        )

        with self.storage._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
            SELECT cache_key, conversation_id, compression_level, messages_json, 
                   token_count, created_at, last_accessed, access_count
            FROM context_cache 
            WHERE cache_key = ?
            """,
                (cache_key,),
            )

            row = cursor.fetchone()

            if row:
                # 更新访问时间和访问次数
                cursor.execute(
                    """
                UPDATE context_cache 
                SET last_accessed = ?, access_count = access_count + 1
                WHERE cache_key = ?
                """,
                    (time.time(), cache_key),
                )

                # 解析结果
                messages = [ContextMessage.from_dict(msg) for msg in json.loads(row[3])]
                entry = ContextCacheEntry(
                    cache_key=row[0],
                    conversation_id=row[1],
                    compression_level=CompressionLevel(row[2]),
                    messages=messages,
                    token_count=row[4],
                    created_at=row[5],
                    last_accessed=time.time(),
                    access_count=row[7] + 1,
                )
                return entry

        return None

    def put(
        self,
        conversation_id: str,
        compression_level: CompressionLevel,
        messages: List[ContextMessage],
        token_count: int,
        message_hash: Optional[str] = None,
    ) -> str:
        """
        存储缓存条目
        :param conversation_id: 会话ID
        :param compression_level: 压缩级别
        :param messages: 压缩后的消息列表
        :param token_count: token数量
        :param message_hash: 预计算的原始消息哈希（可选）
        :return: 缓存键
        """
        if not message_hash:
            message_hash = self._compute_message_hash(messages)

        cache_key = self._generate_cache_key(
            conversation_id, compression_level, message_hash
        )
        now = time.time()

        messages_json = json.dumps([msg.to_dict() for msg in messages])

        with self.storage._get_connection() as conn:
            cursor = conn.cursor()

            # 插入或替换缓存
            cursor.execute(
                """
            INSERT OR REPLACE INTO context_cache 
            (cache_key, conversation_id, compression_level, messages_json, token_count, 
             created_at, last_accessed, access_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
                (
                    cache_key,
                    conversation_id,
                    compression_level.value,
                    messages_json,
                    token_count,
                    now,
                    now,
                ),
            )

        logger.debug(
            f"已缓存上下文: {cache_key}, 级别: {compression_level.name}, token: {token_count}"
        )
        return cache_key

    def invalidate(
        self, conversation_id: Optional[str] = None, cache_key: Optional[str] = None
    ):
        """
        失效缓存
        :param conversation_id: 失效指定会话的所有缓存
        :param cache_key: 失效指定缓存键
        """
        with self.storage._get_connection() as conn:
            cursor = conn.cursor()

            if cache_key:
                cursor.execute(
                    "DELETE FROM context_cache WHERE cache_key = ?", (cache_key,)
                )
                logger.debug(f"已失效缓存: {cache_key}")
            elif conversation_id:
                cursor.execute(
                    "DELETE FROM context_cache WHERE conversation_id = ?",
                    (conversation_id,),
                )
                logger.debug(f"已失效会话缓存: {conversation_id}")

    def prune(self, max_age_days: int = 30, max_entries: int = 1000) -> int:
        """
        清理过期缓存
        :param max_age_days: 最大保留天数，超过的缓存将被清理
        :param max_entries: 最大缓存条目数，超过时清理最久未使用的
        :return: 清理的条目数
        """
        with self.storage._get_connection() as conn:
            cursor = conn.cursor()

            # 清理过期缓存
            cutoff_time = time.time() - (max_age_days * 86400)
            cursor.execute(
                "DELETE FROM context_cache WHERE last_accessed < ?", (cutoff_time,)
            )
            deleted = cursor.rowcount

            # 清理超出数量限制的缓存，按最后访问时间排序
            cursor.execute("SELECT COUNT(*) FROM context_cache")
            count = cursor.fetchone()[0]

            if count > max_entries:
                delete_count = count - max_entries
                cursor.execute(
                    """
                DELETE FROM context_cache 
                WHERE cache_key IN (
                    SELECT cache_key FROM context_cache 
                    ORDER BY last_accessed ASC 
                    LIMIT ?
                )
                """,
                    (delete_count,),
                )
                deleted += cursor.rowcount

        if deleted > 0:
            logger.info(f"已清理{deleted}条过期缓存")

        return deleted

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self.storage._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM context_cache")
            total_entries = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(token_count) FROM context_cache")
            total_tokens = cursor.fetchone()[0] or 0

            cursor.execute("SELECT AVG(access_count) FROM context_cache")
            avg_access_count = cursor.fetchone()[0] or 0

            cursor.execute("SELECT MIN(created_at), MAX(created_at) FROM context_cache")
            min_created, max_created = cursor.fetchone()

        return {
            "total_entries": total_entries,
            "total_cached_tokens": total_tokens,
            "average_access_count": round(avg_access_count, 2),
            "oldest_entry": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(min_created)
            )
            if min_created
            else None,
            "newest_entry": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(max_created)
            )
            if max_created
            else None,
        }

    def clear_all(self):
        """清空所有缓存"""
        with self.storage._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM context_cache")
        logger.warning("已清空所有上下文缓存")
