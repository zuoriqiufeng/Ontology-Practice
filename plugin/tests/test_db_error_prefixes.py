"""test_db_error_prefixes.py — Phase 1/2: 错误码前缀映射与 unknown 化单测

覆盖:
  - DB_ERROR_PREFIXES 数据完整性 (值 ∈ 已知 DB 标识, 前缀大写归一)
  - _resolve_db_type 最长前缀优先匹配
  - 无证据时返回 None (unknown), 不再默认 oracle
"""

import unittest

from plugin.constants import DB_ALIASES, DB_ERROR_PREFIXES, KNOWN_DBS, is_db_match
from plugin.tools import _resolve_db_type


class TestDBErrorPrefixes(unittest.TestCase):
    def test_prefix_values_resolve_to_known_dbs(self):
        """前缀映射值必须能经 is_db_match 归一到 KNOWN_DBS（与 lint db-coverage 同一判据）"""
        for prefix, db in DB_ERROR_PREFIXES.items():
            self.assertTrue(
                any(is_db_match(db, k) for k in KNOWN_DBS),
                f"前缀 {prefix} 的值 {db} 无法归一到 KNOWN_DBS")

    def test_prefix_uppercase_normalized(self):
        """所有前缀键应为大写（匹配前 code_upper.upper()）"""
        for prefix in DB_ERROR_PREFIXES:
            self.assertEqual(prefix, prefix.upper(), f"前缀 {prefix} 应为大写")


class TestResolveDbType(unittest.TestCase):
    def test_known_prefixes(self):
        self.assertEqual(_resolve_db_type("ORA-01234"), "oracle")
        self.assertEqual(_resolve_db_type("PG-12345"), "postgresql")
        self.assertEqual(_resolve_db_type("DB2  SQLxxxx"), "db2")
        self.assertEqual(_resolve_db_type("MSSQL: error 123"), "sqlserver")
        self.assertEqual(_resolve_db_type("MySQL error 1064"), "mysql")
        self.assertEqual(_resolve_db_type("YAS-02024"), "yashandb")

    def test_case_insensitive(self):
        """前缀匹配大小写不敏感（修复历史死代码: 原 'MySQL' 键对大写串永不命中）"""
        self.assertEqual(_resolve_db_type("mysql error 1064"), "mysql")
        self.assertEqual(_resolve_db_type("ora-00001"), "oracle")

    def test_no_evidence_returns_none(self):
        """无证据 → None（unknown），不再默认 oracle"""
        self.assertIsNone(_resolve_db_type("-4002"))
        self.assertIsNone(_resolve_db_type(None))
        self.assertIsNone(_resolve_db_type(""))

    def test_explicit_fallback(self):
        self.assertEqual(_resolve_db_type("-4002", fallback="generic"), "generic")

    def test_ob_no_independent_prefix(self):
        """OceanBase 无独立前缀：ORACLE 兼容码归 oracle，由显式参数覆盖 OB 场景"""
        self.assertEqual(_resolve_db_type("ORA-03113"), "oracle")


if __name__ == "__main__":
    unittest.main()
