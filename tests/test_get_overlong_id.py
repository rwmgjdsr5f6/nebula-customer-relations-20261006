"""crm.py get 子命令超长编号的回归测试。

在 Python 3.11 默认的整数字符串转换位数限制下，超长编号过去可能触发
未处理的 ValueError（退出码 1 与异常堆栈）。本文件固定 get 查询入口在
五千位编号输入上的公开命令行行为：

- 五千个 0 后接 1 与编号 1 指向同一条记录，返回完全相同的单个 JSON
  对象，首尾再加空格或制表符仍然成功，前导零数量不受限制；
- 五千个 9、五千个 0 一律退出码 2、标准输出为空、标准错误恰为单行
  ``id: must be a positive integer``（行尾带换行），不出现异常堆栈；
- 无效编号被拒绝时不改变已有记录，数据库尚不存在时不创建数据库文件
  或 SQLite 伴随文件，父目录缺失时只报告编号错误且不创建目录；
- 五千个 0 后接 99 这类合法超长编号在父目录存在的新路径上按现有语义
  创建空数据库，再仅报告 ``id: contact not found``，随后 list 返回空数组。

仅使用 Python 3 标准库 unittest，通过子进程执行 crm.py，
所有样例数据都放在独立的临时目录中，测试结束后自动清理。
在项目根目录运行：python -m unittest discover -s tests
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CRM_SCRIPT = PROJECT_ROOT / "crm.py"

ID_ERROR_LINE = "id: must be a positive integer"
NOT_FOUND_LINE = "id: contact not found"

# 五千个 0 后接 1：数值仍为 1，前导零再多也合法
LONG_LEADING_ZERO_ID = "0" * 5000 + "1"

# 五千个 9（远超上限）与五千个 0（数值为 0）：均为无效编号
OVERLONG_INVALID_IDS = ["9" * 5000, "0" * 5000]

# 合法但样例中未保存的超长编号：五千个 0 后接 99
LONG_UNKNOWN_ID = "0" * 5000 + "99"


class GetOverlongIdTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmpdir = Path(self._tmpdir.name)
        self.db_path = self.tmpdir / "contacts.sqlite3"

    def run_crm(self, db_path, *cli_args):
        """运行 crm.py 子进程并返回完整结果。"""
        return subprocess.run(
            [sys.executable, str(CRM_SCRIPT), "--db", str(db_path), *cli_args],
            capture_output=True,
        )

    def add_contact(self, db_path, name, email, company):
        return self.run_crm(
            db_path, "add", "--name", name, "--email", email, "--company", company
        )

    def get_contact(self, db_path, contact_id):
        return self.run_crm(db_path, "get", "--id", str(contact_id))

    def list_company(self, db_path, company):
        return self.run_crm(db_path, "list", "--company", company)

    def assert_get_success(self, result, expected):
        """断言 get 成功并返回解析后的联系人字典。

        退出码 0、标准错误为空，标准输出整体是单个联系人 JSON 对象，
        只含 id/name/email/company 四个字段且逐字段与期望一致。
        """
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(record, dict)
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertEqual(record, expected)
        return record

    def assert_get_rejected(self, result, expected_stderr_line):
        """断言 get 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        # 恰为一行、行尾带换行，且不含异常堆栈
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )
        self.assertNotIn(b"Traceback", result.stderr)

    def assert_list_success(self, db_path, company, expected_records):
        """断言 list 返回的记录（含顺序）与期望完全一致。"""
        result = self.list_company(db_path, company)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def seed_contacts(self):
        """在全新数据库依次新增林宁、许禾（星河科技）与周岚（远帆咨询）。"""
        def add(name, email, company):
            result = self.add_contact(self.db_path, name, email, company)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(result.stderr, b"")
            record = json.loads(result.stdout.decode("utf-8"))
            self.assertEqual(
                set(record.keys()), {"id", "name", "email", "company"}
            )
            return record

        lin = add("林宁", "lin@example.test", "星河科技")
        xu = add("许禾", "xu@example.test", "星河科技")
        zhou = add("周岚", "zhou@example.test", "远帆咨询")
        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])
        return lin, xu, zhou

    # ---- 五千个 0 后接 1 仍指向编号 1 ----

    def test_get_long_leading_zero_id_returns_same_object_as_plain_id(self):
        lin, _xu, _zhou = self.seed_contacts()
        self.assertEqual(lin["id"], 1)

        plain = self.get_contact(self.db_path, "1")
        overlong = self.get_contact(self.db_path, LONG_LEADING_ZERO_ID)

        # 两个独立进程调用均成功，且输出完全相同的单个 JSON 对象
        self.assert_get_success(plain, lin)
        record = self.assert_get_success(overlong, lin)
        self.assertEqual(plain.stdout, overlong.stdout)
        # 字段值与新增结果逐项一致
        self.assertEqual(record["id"], 1)
        self.assertEqual(record["name"], "林宁")
        self.assertEqual(record["email"], "lin@example.test")
        self.assertEqual(record["company"], "星河科技")

    def test_get_padded_long_leading_zero_id_strips_whitespace(self):
        lin, _xu, _zhou = self.seed_contacts()

        # 五千个前导零之外再加首尾空格或制表符仍解析为编号 1
        for raw_id in (
            f"  {LONG_LEADING_ZERO_ID}  ",
            f"\t{LONG_LEADING_ZERO_ID}\t",
            f" \t{LONG_LEADING_ZERO_ID}\t ",
        ):
            with self.subTest(raw_id_prefix=raw_id[:4]):
                result = self.get_contact(self.db_path, raw_id)
                self.assert_get_success(result, lin)

    def test_get_overlong_queries_leave_company_lists_unchanged(self):
        lin, xu, zhou = self.seed_contacts()

        # 多次超长编号查询后，按公司列出的三条记录保持原值及编号升序
        self.assert_get_success(
            self.get_contact(self.db_path, LONG_LEADING_ZERO_ID), lin
        )
        self.assert_get_success(
            self.get_contact(self.db_path, f"  {LONG_LEADING_ZERO_ID}\t"), lin
        )
        records_xh = self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])
        self.assertEqual(
            [r["id"] for r in records_xh], [lin["id"], xu["id"]]
        )

    # ---- 超长无效编号 ----

    def test_get_overlong_invalid_ids_are_rejected_without_traceback(self):
        self.seed_contacts()

        for raw_id in OVERLONG_INVALID_IDS:
            with self.subTest(id_length=len(raw_id), id_head=raw_id[0]):
                result = self.get_contact(self.db_path, raw_id)
                self.assert_get_rejected(result, ID_ERROR_LINE)

    def test_get_overlong_invalid_ids_leave_records_unchanged(self):
        lin, xu, zhou = self.seed_contacts()

        for raw_id in OVERLONG_INVALID_IDS:
            with self.subTest(id_length=len(raw_id), id_head=raw_id[0]):
                self.assert_get_rejected(
                    self.get_contact(self.db_path, raw_id), ID_ERROR_LINE
                )
                # 拒绝后两家公司的记录内容和数量保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_get_overlong_invalid_ids_do_not_create_missing_database(self):
        for index, raw_id in enumerate(OVERLONG_INVALID_IDS):
            fresh_db = self.tmpdir / f"get-overlong-fresh-{index}.sqlite3"
            with self.subTest(id_length=len(raw_id), id_head=raw_id[0]):
                self.assertFalse(fresh_db.exists())
                result = self.get_contact(fresh_db, raw_id)
                self.assert_get_rejected(result, ID_ERROR_LINE)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_get_overlong_invalid_ids_with_missing_parent_create_nothing(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        # 父目录缺失时仍只报告编号错误，不创建目录或文件
        for raw_id in OVERLONG_INVALID_IDS:
            with self.subTest(id_length=len(raw_id), id_head=raw_id[0]):
                result = self.get_contact(fresh_db, raw_id)
                self.assert_get_rejected(result, ID_ERROR_LINE)
                self.assertFalse(missing_parent.exists())
                self.assertFalse(fresh_db.exists())

    # ---- 合法超长编号但未保存：创建空库后报告未找到 ----

    def test_get_long_unknown_id_creates_empty_database_then_not_found(self):
        fresh_db = self.tmpdir / "get-overlong-unknown.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 父目录存在、编号合法：按现有语义创建空数据库再报告未找到
        result = self.get_contact(fresh_db, LONG_UNKNOWN_ID)
        self.assert_get_rejected(result, NOT_FOUND_LINE)
        self.assertTrue(fresh_db.exists())

        # 随后 list 返回空数组
        self.assert_list_success(fresh_db, "星河科技", [])


if __name__ == "__main__":
    unittest.main()
