"""SQLite 元数据存储 - 数据库初始化与 schema 迁移管理。

职责：
- 数据库文件路径管理（data/app.db，绿色版）
- schema 版本管理（schema_version 表）
- 幂等初始化（已存在则跳过）
- 事务包裹迁移，保证安全
- 外键约束开启

注意：
- T3.1 仅实现 schema 初始化，CRUD 方法在 T3.2 实现
- 同步实现，在 Worker 线程中调用
- 使用 Python 标准库 sqlite3，不引入 ORM
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.logger import get_logger
from src.core.paths import ensure_user_dirs, get_db_path, get_resource_dir

__all__ = ["MetadataStore"]

_logger = get_logger(__name__)

# 当前最新 schema 版本
_CURRENT_SCHEMA_VERSION = 5


def _get_migrations_dir() -> Path:
    """获取迁移 SQL 文件目录。

    优先使用资源目录（打包模式），回退到项目根（dev 模式）。
    """
    res_dir = get_resource_dir() / "migrations"
    if res_dir.exists():
        return res_dir
    # dev 模式回退：src/../migrations
    return Path(__file__).resolve().parent.parent.parent / "migrations"


class MetadataStore:
    """SQLite 元数据存储管理器。

    典型用法：
        store = MetadataStore()
        store.init_db()  # 幂等，可重复调用
        version = store.get_schema_version()
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """初始化存储。

        Args:
            db_path: 自定义数据库路径（测试用），None 时使用默认路径
        """
        self._db_path = db_path or get_db_path()

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ---- 初始化与迁移 ----

    def init_db(self) -> None:
        """初始化数据库，执行未完成的迁移。

        幂等操作：
        - 数据库不存在 → 创建并执行所有迁移
        - 数据库已存在且版本最新 → 跳过
        - 部分迁移 → 从当前版本继续

        迁移在事务中执行，失败回滚。
        """
        ensure_user_dirs()

        conn = self._connect()
        try:
            # 开启外键约束
            conn.execute("PRAGMA foreign_keys = ON")

            current = self._get_version(conn)

            if current >= _CURRENT_SCHEMA_VERSION:
                _logger.debug(
                    "数据库 schema 已是最新 (version=%d)", current
                )
                return

            _logger.info(
                "开始数据库迁移: version %d -> %d",
                current,
                _CURRENT_SCHEMA_VERSION,
            )

            # 从当前版本 + 1 开始迁移
            for version in range(current + 1, _CURRENT_SCHEMA_VERSION + 1):
                self._apply_migration(conn, version)

            final_version = self._get_version(conn)
            _logger.info("数据库迁移完成，当前版本: %d", final_version)
            conn.commit()
        except Exception:
            conn.rollback()
            _logger.exception("数据库迁移失败")
            raise
        finally:
            conn.close()

    def get_schema_version(self) -> int:
        """获取当前 schema 版本号。

        Returns:
            版本号；数据库未初始化时返回 0
        """
        conn = self._connect()
        try:
            return self._get_version(conn)
        finally:
            conn.close()

    # ---- 连接管理 ----

    def _connect(self) -> sqlite3.Connection:
        """创建数据库连接。"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ---- 内部方法 ----

    def _get_version(self, conn: sqlite3.Connection) -> int:
        """查询当前 schema 版本。

        如果 schema_version 表不存在（全新数据库），返回 0。
        """
        try:
            cursor = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row["version"] if row else 0
        except sqlite3.OperationalError:
            # 表不存在 → 全新库
            return 0

    def _apply_migration(self, conn: sqlite3.Connection, version: int) -> None:
        """执行指定版本的迁移 SQL。

        Args:
            conn: 数据库连接
            version: 目标版本号（从 1 开始）

        Raises:
            FileNotFoundError: 迁移文件不存在
            sqlite3.Error: SQL 执行失败
        """
        # 查找匹配 {version:03d}_*.sql 的文件
        prefix = f"{version:03d}_"
        candidates = list(_get_migrations_dir().glob(f"{prefix}*.sql"))
        if not candidates:
            raise FileNotFoundError(
                f"迁移文件不存在: {prefix}*.sql"
            )
        migration_file = candidates[0]

        sql = migration_file.read_text(encoding="utf-8")
        _logger.info("执行迁移: version %d (%s)", version, migration_file.name)

        try:
            conn.executescript(sql)
        except sqlite3.OperationalError as e:
            # 兼容已存在列的情况（如迁移被中断后重入）
            if "duplicate column name" in str(e).lower():
                _logger.warning("迁移 %d 目标列已存在，跳过: %s", version, e)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                    (version,),
                )
                return
            raise
