"""crm.py 命令行行为的回归测试。

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

# (add 子命令参数, 期望的标准错误)
INVALID_ADD_CASES = [
    (
        ["add", "--name", "   ", "--email", "ok@example.test", "--company", "有效公司"],
        "name: must not be empty",
    ),
    (
        ["add", "--name", "有效姓名", "--email", "ok@example.test", "--company", " \t "],
        "company: must not be empty",
    ),
    # 缺少 @
    (
        ["add", "--name", "有效姓名", "--email", "noatsign.example.test", "--company", "有效公司"],
        "email: invalid email address",
    ),
    # 包含两个 @
    (
        ["add", "--name", "有效姓名", "--email", "a@@example.test", "--company", "有效公司"],
        "email: invalid email address",
    ),
    # 域名没有点
    (
        ["add", "--name", "有效姓名", "--email", "a@exampletest", "--company", "有效公司"],
        "email: invalid email address",
    ),
    # 域名含空段
    (
        ["add", "--name", "有效姓名", "--email", "a@example..test", "--company", "有效公司"],
        "email: invalid email address",
    ),
    # 邮箱内部含空白
    (
        ["add", "--name", "有效姓名", "--email", "a b@example.test", "--company", "有效公司"],
        "email: invalid email address",
    ),
]


class CRMTestCase(unittest.TestCase):
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

    def list_company(self, db_path, company):
        return self.run_crm(db_path, "list", "--company", company)

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

    def assert_list_success(self, db_path, company, expected_records):
        """断言 list 返回的记录（含顺序）与期望完全一致。"""
        result = self.list_company(db_path, company)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def seed_sample_contacts(self):
        """在同一个新数据库中依次新增三名联系人，返回各自的新增结果。"""
        result_lin = self.add_contact(
            self.db_path,
            "  林宁  ",
            "  Lin.Ning@example.test  ",
            "  星河科技  ",
        )
        lin = self.assert_add_success(
            result_lin,
            {"name": "林宁", "email": "Lin.Ning@example.test", "company": "星河科技"},
        )

        result_xu = self.add_contact(
            self.db_path, "许禾", "xuhe@example.test", "星河科技"
        )
        xu = self.assert_add_success(
            result_xu,
            {"name": "许禾", "email": "xuhe@example.test", "company": "星河科技"},
        )

        result_zhou = self.add_contact(
            self.db_path, "周岚", "zhoulan@example.test", "远帆咨询"
        )
        zhou = self.assert_add_success(
            result_zhou,
            {"name": "周岚", "email": "zhoulan@example.test", "company": "远帆咨询"},
        )

        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])
        return lin, xu, zhou

    def test_valid_adds_persist_and_list_filters_by_company(self):
        lin, xu, zhou = self.seed_sample_contacts()

        # 星河科技只能查到林宁和许禾，按 id 升序，字段与新增结果一致
        self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        # 远帆咨询只能查到周岚
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def assert_rejected(self, result, expected_stderr):
        """断言命令被拒绝：退出码 2、无标准输出、标准错误精确匹配。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr.decode("utf-8").strip(), expected_stderr)

    def test_invalid_inputs_on_existing_db_leave_records_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        for cli_args, expected_stderr in INVALID_ADD_CASES:
            with self.subTest(cli_args=cli_args):
                result = self.run_crm(self.db_path, *cli_args)
                self.assert_rejected(result, expected_stderr)

                # 拒绝后两家公司的记录内容和数量保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_invalid_inputs_do_not_create_missing_database(self):
        for index, (cli_args, expected_stderr) in enumerate(INVALID_ADD_CASES):
            fresh_db = self.tmpdir / f"fresh-{index}.sqlite3"
            with self.subTest(cli_args=cli_args):
                self.assertFalse(fresh_db.exists())
                result = self.run_crm(fresh_db, *cli_args)
                self.assert_rejected(result, expected_stderr)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_missing_parent_directory_is_rejected_without_being_created(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result = self.add_contact(
            fresh_db, "林宁", "Lin.Ning@example.test", "星河科技"
        )
        self.assert_rejected(result, "db: parent directory does not exist")
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    # ---- list 子命令的筛选行为回归测试 ----

    def assert_list_rejected(self, result, expected_stderr_line):
        """断言 list 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )

    def test_list_returns_seeded_records_sorted_by_id(self):
        lin, xu, zhou = self.seed_sample_contacts()

        # 星河科技只返回林宁和许禾，按 id 升序，字段与新增结果一致
        records = self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        self.assertEqual([r["id"] for r in records], sorted(r["id"] for r in records))
        for record, added in zip(records, (lin, xu)):
            self.assertEqual(record, added)

        # 远帆咨询只返回周岚
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_list_ignores_surrounding_whitespace_in_company(self):
        lin, xu, _zhou = self.seed_sample_contacts()

        for padded in ("  星河科技", "星河科技  ", "\t星河科技\t", " \t星河科技 \t"):
            with self.subTest(company=padded):
                self.assert_list_success(self.db_path, padded, [lin, xu])

    def test_list_rejects_substring_and_internal_whitespace_matches(self):
        self.seed_sample_contacts()

        for company in ("星河", "星河 科技", "未录入公司"):
            with self.subTest(company=company):
                self.assert_list_success(self.db_path, company, [])

    def test_list_success_output_is_single_json_array(self):
        self.seed_sample_contacts()

        result = self.list_company(self.db_path, "星河科技")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        # 标准输出整体可解析为单个 JSON 数组（无多余输出）
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertEqual(len(records), 2)

    def test_list_creates_missing_database_and_returns_empty_array(self):
        self.assertFalse(self.db_path.exists())

        result = self.list_company(self.db_path, "星河科技")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), [])
        # 有效 list 会创建数据库文件
        self.assertTrue(self.db_path.exists())

        # 再次通过独立命令查询仍返回空数组，不产生联系人
        again = self.list_company(self.db_path, "星河科技")
        self.assertEqual(again.returncode, 0, again.stderr.decode("utf-8"))
        self.assertEqual(again.stderr, b"")
        self.assertEqual(json.loads(again.stdout.decode("utf-8")), [])

    def test_list_empty_or_blank_company_is_rejected(self):
        self.seed_sample_contacts()

        for company in ("", "   ", "\t\t", " \t "):
            with self.subTest(company=company):
                result = self.list_company(self.db_path, company)
                self.assert_list_rejected(result, "company: must not be empty")

    def test_list_invalid_company_does_not_create_missing_database(self):
        for index, company in enumerate(("", "   ", "\t\t", " \t ")):
            fresh_db = self.tmpdir / f"list-fresh-{index}.sqlite3"
            with self.subTest(company=company):
                self.assertFalse(fresh_db.exists())
                result = self.list_company(fresh_db, company)
                self.assert_list_rejected(result, "company: must not be empty")
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_list_invalid_company_leaves_existing_records_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        for company in ("", "   ", "\t\t", " \t "):
            with self.subTest(company=company):
                result = self.list_company(self.db_path, company)
                self.assert_list_rejected(result, "company: must not be empty")

                # 拒绝后两家公司的记录内容和数量保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_list_missing_parent_directory_is_rejected_without_being_created(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result = self.list_company(fresh_db, "星河科技")
        self.assert_list_rejected(result, "db: parent directory does not exist")
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    def test_list_invalid_company_and_missing_parent_reports_company_error(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result = self.list_company(fresh_db, "   ")
        self.assert_list_rejected(result, "company: must not be empty")
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())


if __name__ == "__main__":
    unittest.main()
