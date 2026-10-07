"""crm.py get 子命令超长编号边界的回归测试。

五千位编号样例此前只在更新命令的测试中出现，本文件把同一输入边界固定到
get（按编号查看联系人）入口上，覆盖其既有的输入与输出语义：

- 五千个 ASCII 0 后接 1 与普通编号 1 指向同一条记录，两次独立进程调用
  返回完全相同的单个 JSON 对象；首尾再加空格或制表符仍成功；
- 成功时退出码 0、标准错误为空，标准输出只含 id/name/email/company
  四个字段，字段值与 add 新增结果逐项一致；
- 查询后按公司列出的记录保持原值，并按编号升序；
- 五千个 9、五千个 0 均为无效编号：退出码 2、标准输出为空，标准错误
  恰为单行 id: must be a positive integer（行尾带换行），无异常堆栈；
- 无效编号不改动已有记录；父目录存在但数据库文件尚不存在时不创建数据库
  或任何 SQLite 伴随文件；父目录缺失时仍只报告编号错误，也不创建目录；
- 对照：五千个 0 后接 99 是合法超长编号，在父目录存在的新数据库路径上
  按现有语义创建空库，再仅报告 id: contact not found，随后 list 返回 []。

仅使用 Python 3 标准库 unittest，通过子进程执行 crm.py，
所有样例数据都放在独立的临时 SQLite 数据库中，测试结束后自动清理，
重复执行不依赖任何遗留文件。
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

# 五千个 9（超长且远超 64 位有符号整数上限）、五千个 0（数值为 0）
OVERLONG_INVALID_IDS = ["9" * 5000, "0" * 5000]

# 五千个 0 后接 1：数值仍为 1，前导零再多也合法
LONG_LEADING_ZERO_ONE = "0" * 5000 + "1"

# 五千个 0 后接 99：合法的超长编号写法，指向不存在的编号 99
LONG_LEADING_ZERO_99 = "0" * 5000 + "99"


class GetIdBoundaryTestCase(unittest.TestCase):
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
        self.assertIsInstance(record["id"], int)
        self.assertEqual(record, expected)
        return record

    def assert_id_error(self, result):
        """断言编号被拒：退出码 2、无标准输出、标准错误恰为单行编号错误。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        # 恰为一行、行尾带换行；精确相等也保证不出现异常堆栈
        self.assertEqual(result.stderr.decode("utf-8"), ID_ERROR_LINE + "\n")

    def assert_not_found_error(self, result):
        """断言记录不存在：退出码 2、无标准输出、标准错误恰为单行未找到。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr.decode("utf-8"), NOT_FOUND_LINE + "\n")

    def assert_list_success(self, db_path, company, expected_records):
        """断言 list 返回的记录（含顺序）与期望完全一致。"""
        result = self.list_company(db_path, company)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def seed_contacts(self):
        """在全新数据库按顺序新增林宁、许禾（星河科技）与周岚（远帆咨询）。"""
        def add(name, email, company):
            result = self.add_contact(self.db_path, name, email, company)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(result.stderr, b"")
            record = json.loads(result.stdout.decode("utf-8"))
            self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
            self.assertIsInstance(record["id"], int)
            return record

        lin = add("林宁", "lin@example.test", "星河科技")
        xu = add("许禾", "xu@example.test", "星河科技")
        zhou = add("周岚", "zhou@example.test", "远帆咨询")
        self.assertEqual(lin["id"], 1)
        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])
        return lin, xu, zhou

    # ---- 合法超长编号：五千个 0 后接 1 ----

    def test_get_five_thousand_leading_zeros_returns_same_as_id_one(self):
        lin, _xu, _zhou = self.seed_contacts()

        # 两次查询由独立命令进程完成：普通编号 1 与五千个 0 后接 1
        plain = self.get_contact(self.db_path, "1")
        padded = self.get_contact(self.db_path, LONG_LEADING_ZERO_ONE)

        self.assert_get_success(plain, lin)
        self.assert_get_success(padded, lin)
        # 超长编号与普通编号返回完全相同的单个 JSON 对象
        self.assertEqual(plain.stdout, padded.stdout)

    def test_get_long_leading_zero_id_succeeds_with_surrounding_whitespace(self):
        lin, _xu, _zhou = self.seed_contacts()

        # 首尾空格或制表符（含混合形式）被清理后仍解析为编号 1
        for raw_id in (
            f"  {LONG_LEADING_ZERO_ONE}  ",
            f"\t{LONG_LEADING_ZERO_ONE}\t",
            f" \t {LONG_LEADING_ZERO_ONE} \t ",
        ):
            with self.subTest(padding=raw_id[:6]):
                result = self.get_contact(self.db_path, raw_id)
                self.assert_get_success(result, lin)

    def test_get_long_id_queries_leave_company_lists_unchanged_and_ordered(self):
        lin, xu, zhou = self.seed_contacts()

        self.assert_get_success(
            self.get_contact(self.db_path, LONG_LEADING_ZERO_ONE), lin
        )

        # 三条记录保持原值；公司内部按编号升序
        xinghe = self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        yuanfan = self.assert_list_success(self.db_path, "远帆咨询", [zhou])
        self.assertEqual(
            [record["id"] for record in [*xinghe, *yuanfan]],
            [lin["id"], xu["id"], zhou["id"]],
        )

    # ---- 无效超长编号：五千个 9、五千个 0 ----

    def test_get_overlong_invalid_ids_report_single_id_error_line(self):
        self.seed_contacts()

        for raw_id in OVERLONG_INVALID_IDS:
            with self.subTest(digit=raw_id[0]):
                result = self.get_contact(self.db_path, raw_id)
                # 退出码 2、标准输出为空、标准错误仅一行且无异常堆栈
                self.assert_id_error(result)

    def test_get_overlong_invalid_ids_leave_records_unchanged(self):
        lin, xu, zhou = self.seed_contacts()

        for raw_id in OVERLONG_INVALID_IDS:
            with self.subTest(digit=raw_id[0]):
                self.assert_id_error(self.get_contact(self.db_path, raw_id))
                # 拒绝后两家公司的记录内容、数量与顺序保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_get_overlong_invalid_ids_do_not_create_missing_database(self):
        # 不准备任何数据：父目录存在但数据库文件尚不存在
        for index, raw_id in enumerate(OVERLONG_INVALID_IDS):
            fresh_db = self.tmpdir / f"get-overlong-fresh-{index}.sqlite3"
            with self.subTest(digit=raw_id[0]):
                self.assertFalse(fresh_db.exists())
                result = self.get_contact(fresh_db, raw_id)
                self.assert_id_error(result)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_get_overlong_invalid_ids_with_missing_parent_create_nothing(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        for raw_id in OVERLONG_INVALID_IDS:
            with self.subTest(digit=raw_id[0]):
                # 编号先于数据库路径被校验：只报告编号错误
                result = self.get_contact(fresh_db, raw_id)
                self.assert_id_error(result)
                # 不创建缺失的父目录，也不创建任何文件
                self.assertFalse(missing_parent.exists())
                self.assertFalse(fresh_db.exists())

    # ---- 合法超长编号的对照：五千个 0 后接 99 ----

    def test_get_long_leading_zero_99_on_fresh_db_creates_empty_and_not_found(self):
        fresh_db = self.tmpdir / "get-overlong-99.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 父目录存在、编号合法：按现有语义创建空数据库再报告未找到
        result = self.get_contact(fresh_db, LONG_LEADING_ZERO_99)
        self.assert_not_found_error(result)
        self.assertTrue(fresh_db.exists())

        # 随后按公司列出结果为空数组
        self.assert_list_success(fresh_db, "星河科技", [])


if __name__ == "__main__":
    unittest.main()
