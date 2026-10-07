"""crm.py company-summary 子命令（按公司汇总联系人数量）的回归测试。

固定 company-summary 的公开命令行行为：

- 成功时退出码 0、标准错误为空，标准输出整体只有一个 JSON 数组；每项仅含
  company 与整数 contact_count 两个字段，按完整公司名精确、区分大小写归组，
  按公司名 Unicode 码点升序排列，且只包含至少有一条联系人记录的公司；
- 同姓名或同邮箱的不同联系人记录分别计数，不做任何去重；汇总不修改数据，
  用 list 对照查询前后的完整联系人记录应完全一致；
- 每次汇总都启动全新的 crm.py 子进程，再次查询同一数据库得到相同结果；
- 已存在但为空的数据库返回 []；父目录存在而数据库文件不存在时自动创建
  可复用的空库并返回 []，再次查询仍为空；
- 父目录不存在时退出码 2、标准输出为空，标准错误恰为
  db: parent directory does not exist 加行尾换行，目录与数据库均不被创建。

add、list、delete 在本模块仅用于准备样例和对照验证。仅使用 Python 3 标准库
unittest，通过子进程执行 crm.py，所有样例数据都放在各自独立的临时数据库中，
测试结束后自动清理，不读取已有客户库、不依赖网络或第三方包，重复执行结果一致。
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

COMPANY_XINGHE = "星河科技"
COMPANY_YUANFAN = "远帆咨询"

DB_ERROR_LINE = "db: parent directory does not exist"


class CompanySummaryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmpdir = Path(self._tmpdir.name)
        self.db_path = self.tmpdir / "contacts.sqlite3"

    def run_crm(self, db_path, *cli_args):
        """运行 crm.py 子进程并返回完整结果。每次调用都是独立的新进程。"""
        return subprocess.run(
            [sys.executable, str(CRM_SCRIPT), "--db", str(db_path), *cli_args],
            capture_output=True,
        )

    def add_contact(self, db_path, name, email, company):
        return self.run_crm(
            db_path, "add", "--name", name, "--email", email, "--company", company
        )

    def company_summary(self, db_path):
        return self.run_crm(db_path, "company-summary")

    def list_all(self, db_path):
        """省略 --company 的 list：跨全部公司按编号升序返回完整联系人记录。"""
        return self.run_crm(db_path, "list")

    def delete_contact(self, db_path, contact_id):
        return self.run_crm(db_path, "delete", "--id", str(contact_id))

    def assert_add_success(self, result, expected):
        """断言新增成功并返回解析后的联系人字典。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertIsInstance(record["id"], int)
        self.assertEqual(record["name"], expected["name"])
        self.assertEqual(record["email"], expected["email"])
        self.assertEqual(record["company"], expected["company"])
        return record

    def assert_summary_rejected(self, result, expected_stderr_line):
        """断言汇总被拒绝：退出码 2、无标准输出、标准错误恰为单行。

        标准错误中不允许出现异常堆栈。
        """
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        stderr_text = result.stderr.decode("utf-8")
        self.assertEqual(stderr_text, expected_stderr_line + "\n")
        self.assertNotIn("Traceback", stderr_text)

    def summary_records(self, db_path):
        """执行汇总并断言输出形态后，返回解析后的 JSON 数组。

        成功时退出码 0、标准错误为空，标准输出整体可解析为单个 JSON 数组；
        每项只含 company 与 contact_count，且 contact_count 为整数。
        比较基于解析后的结构，不依赖 JSON 缩进或对象键的排列。
        """
        result = self.company_summary(db_path)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        for record in records:
            self.assertEqual(set(record.keys()), {"company", "contact_count"})
            self.assertIsInstance(record["company"], str)
            self.assertIsInstance(record["contact_count"], int)
        return records

    def assert_summary_success(self, db_path, expected_pairs):
        """断言汇总结果（含顺序）与期望的 (公司名, 人数) 序列完全一致。"""
        records = self.summary_records(db_path)
        self.assertEqual(
            [(r["company"], r["contact_count"]) for r in records],
            expected_pairs,
        )
        return records

    def assert_list_all_success(self, db_path, expected_records):
        """断言跨公司 list 返回的完整记录（含顺序）与期望完全一致。"""
        result = self.list_all(db_path)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def assert_codepoint_order(self, records):
        """断言公司名严格按 Unicode 码点升序排列。"""
        companies = [r["company"] for r in records]
        self.assertEqual(
            companies,
            sorted(companies, key=lambda name: [ord(ch) for ch in name]),
        )

    # ---- 主样例：归组、排序、重复计数、删除后零人数项消失、只读对照 ----

    def test_summary_main_sample_grouping_order_duplicates_and_deletion(self):
        # 新增顺序刻意与排序结果相反：先远帆咨询的周岚，
        # 再星河科技的林宁和许禾
        zhou = self.assert_add_success(
            self.add_contact(self.db_path, "周岚", "zhou@example.test", "远帆咨询"),
            {"name": "周岚", "email": "zhou@example.test", "company": "远帆咨询"},
        )
        lin = self.assert_add_success(
            self.add_contact(self.db_path, "林宁", "lin@example.test", "星河科技"),
            {"name": "林宁", "email": "lin@example.test", "company": "星河科技"},
        )
        xu = self.assert_add_success(
            self.add_contact(self.db_path, "许禾", "xu@example.test", "星河科技"),
            {"name": "许禾", "email": "xu@example.test", "company": "星河科技"},
        )
        self.assertLess(zhou["id"], lin["id"])
        self.assertLess(lin["id"], xu["id"])

        # 汇总前的完整联系人记录：按编号升序共三条
        self.assert_list_all_success(self.db_path, [zhou, lin, xu])

        # 排序只看公司名码点（星 U+661F 在远 U+8FDC 之前），与新增顺序无关：
        # 星河科技 2 人在前，远帆咨询 1 人在后
        records = self.assert_summary_success(
            self.db_path,
            [(COMPANY_XINGHE, 2), (COMPANY_YUANFAN, 1)],
        )
        self.assert_codepoint_order(records)

        # 每次汇总都是新进程；再次查询同一数据库结果相同，
        # 且汇总未修改任何联系人记录
        again = self.summary_records(self.db_path)
        self.assertEqual(again, records)
        self.assert_list_all_success(self.db_path, [zhou, lin, xu])

        # 再新增一条与林宁同姓名、同邮箱、同公司的记录：
        # 两条记录分别计数，星河科技变为 3 人
        lin_duplicate = self.assert_add_success(
            self.add_contact(self.db_path, "林宁", "lin@example.test", "星河科技"),
            {"name": "林宁", "email": "lin@example.test", "company": "星河科技"},
        )
        self.assertNotEqual(lin_duplicate["id"], lin["id"])

        self.assert_list_all_success(self.db_path, [zhou, lin, xu, lin_duplicate])
        records = self.assert_summary_success(
            self.db_path,
            [(COMPANY_XINGHE, 3), (COMPANY_YUANFAN, 1)],
        )
        self.assert_codepoint_order(records)
        self.assertEqual(self.summary_records(self.db_path), records)

        # 删除编号取自新增结果：删除周岚后远帆咨询不再以 0 人出现，
        # 只剩星河科技 3 人
        delete_result = self.delete_contact(self.db_path, zhou["id"])
        self.assertEqual(delete_result.returncode, 0, delete_result.stderr.decode("utf-8"))
        self.assertEqual(delete_result.stderr, b"")

        records = self.assert_summary_success(self.db_path, [(COMPANY_XINGHE, 3)])
        self.assert_codepoint_order(records)

        # 删除后的完整联系人记录与汇总口径一致：林宁、许禾及同名同邮箱副本
        self.assert_list_all_success(self.db_path, [lin, xu, lin_duplicate])
        # 再次启动进程查询，汇总结果保持不变
        self.assertEqual(
            [(r["company"], r["contact_count"]) for r in self.summary_records(self.db_path)],
            [(COMPANY_XINGHE, 3)],
        )

    # ---- 区分大小写：Acme 与 acme 是两个分组，大写 A 排在前 ----

    def test_summary_groups_case_sensitively(self):
        alice = self.assert_add_success(
            self.add_contact(self.db_path, "Alice", "alice@example.test", "Acme"),
            {"name": "Alice", "email": "alice@example.test", "company": "Acme"},
        )
        bob = self.assert_add_success(
            self.add_contact(self.db_path, "Bob", "bob@example.test", "acme"),
            {"name": "Bob", "email": "bob@example.test", "company": "acme"},
        )

        # A（U+0041）在 a（U+0061）之前：Acme 与 acme 各成一组且各 1 人
        records = self.assert_summary_success(
            self.db_path, [("Acme", 1), ("acme", 1)]
        )
        self.assert_codepoint_order(records)

        # 汇总不修改数据
        self.assert_list_all_success(self.db_path, [alice, bob])
        self.assertEqual(self.summary_records(self.db_path), records)

    # ---- 空数据库 ----

    def test_summary_on_existing_empty_database_returns_empty_array(self):
        self.assertFalse(self.db_path.exists())

        # 先用既有 list 行为在文件层面建好空数据库（含 contacts 表、零条记录）
        create_result = self.list_all(self.db_path)
        self.assertEqual(create_result.returncode, 0, create_result.stderr.decode("utf-8"))
        self.assertEqual(create_result.stderr, b"")
        self.assertEqual(json.loads(create_result.stdout.decode("utf-8")), [])
        self.assertTrue(self.db_path.exists())

        # 已存在的空数据库：汇总输出单个空 JSON 数组
        records = self.summary_records(self.db_path)
        self.assertEqual(records, [])
        # 再查一次仍为空
        self.assertEqual(self.summary_records(self.db_path), [])

    def test_summary_creates_missing_database_and_returns_empty_array(self):
        self.assertFalse(self.db_path.exists())

        # 父目录存在、数据库文件尚不存在：汇总成功创建可复用的空库并返回 []
        result = self.company_summary(self.db_path)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), [])
        self.assertTrue(self.db_path.exists())

        # 再次启动命令查询同一数据库仍为空，原始输出一致
        again = self.company_summary(self.db_path)
        self.assertEqual(again.returncode, 0, again.stderr.decode("utf-8"))
        self.assertEqual(again.stderr, b"")
        self.assertEqual(json.loads(again.stdout.decode("utf-8")), [])
        self.assertEqual(again.stdout, result.stdout)

        # 新建的库可直接复用：新增一条联系人后汇总能读到它
        contact = self.assert_add_success(
            self.add_contact(self.db_path, "林宁", "lin@example.test", "星河科技"),
            {"name": "林宁", "email": "lin@example.test", "company": "星河科技"},
        )
        self.assert_summary_success(self.db_path, [(COMPANY_XINGHE, 1)])
        self.assert_list_all_success(self.db_path, [contact])

    # ---- 父目录不存在 ----

    def test_summary_missing_parent_directory_is_rejected_without_being_created(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

        result = self.company_summary(fresh_db)
        self.assert_summary_rejected(result, DB_ERROR_LINE)
        # 目录和数据库文件（含任何 SQLite 伴随文件）都不被创建
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())
        self.assertEqual(list(self.tmpdir.glob("no-such-parent*")), [])

        # 失败后重试仍是同样的拒绝结果
        again = self.company_summary(fresh_db)
        self.assert_summary_rejected(again, DB_ERROR_LINE)
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())


if __name__ == "__main__":
    unittest.main()
