"""crm.py update-company 子命令行为的回归测试。

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

# (update-company 子命令的 --id 与 --company 参数, 期望的标准错误)
INVALID_UPDATE_COMPANY_CASES = [
    # 编号为空白
    (("   ", "远帆咨询"), "id: must be a positive integer"),
    # 编号为 0
    (("0", "远帆咨询"), "id: must be a positive integer"),
    # 编号为小数
    (("1.5", "远帆咨询"), "id: must be a positive integer"),
    # 编号超出 64 位有符号整数上限
    (("9223372036854775808", "远帆咨询"), "id: must be a positive integer"),
    # 合法编号配合空白公司
    (("1", "   "), "company: must not be empty"),
    (("1", " \t "), "company: must not be empty"),
    # 编号与公司同时无效时只报告编号错误
    (("1.5", "   "), "id: must be a positive integer"),
    (("0", ""), "id: must be a positive integer"),
]


class UpdateCompanyTestCase(unittest.TestCase):
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

    def update_company(self, db_path, contact_id, company):
        return self.run_crm(
            db_path, "update-company", "--id", str(contact_id), "--company", company
        )

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

    def assert_update_success(self, result, expected):
        """断言更新成功并返回解析后的联系人字典。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        # 标准输出整体可解析为单个联系人 JSON 对象，只含原有四个字段
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertEqual(record, expected)
        return record

    def assert_update_rejected(self, result, expected_stderr_line):
        """断言 update-company 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )

    def seed_update_company_contacts(self):
        """新增 update-company 固定样例：林宁/许禾（星河科技）、周岚（远帆咨询）。"""
        lin = self.assert_add_success(
            self.add_contact(self.db_path, "林宁", "lin@example.test", "星河科技"),
            {"name": "林宁", "email": "lin@example.test", "company": "星河科技"},
        )
        xu = self.assert_add_success(
            self.add_contact(self.db_path, "许禾", "xu@example.test", "星河科技"),
            {"name": "许禾", "email": "xu@example.test", "company": "星河科技"},
        )
        zhou = self.assert_add_success(
            self.add_contact(self.db_path, "周岚", "zhou@example.test", "远帆咨询"),
            {"name": "周岚", "email": "zhou@example.test", "company": "远帆咨询"},
        )
        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])
        return lin, xu, zhou

    def test_update_company_success_moves_contact_and_persists(self):
        lin, xu, zhou = self.seed_update_company_contacts()

        # 编号与公司输入均带首尾空白，编号还带前导零
        result = self.update_company(
            self.db_path, f"  00{lin['id']}  ", "  远帆咨询  "
        )
        updated_lin = self.assert_update_success(
            result,
            {
                "id": lin["id"],
                "name": "林宁",
                "email": "lin@example.test",
                "company": "远帆咨询",
            },
        )
        # 只有 company 改变，编号、姓名和邮箱保持不变
        self.assertEqual(updated_lin["id"], lin["id"])
        self.assertEqual(updated_lin["name"], lin["name"])
        self.assertEqual(updated_lin["email"], lin["email"])
        self.assertEqual(updated_lin["company"], "远帆咨询")

        # 独立命令按公司查询：星河科技只剩许禾
        records_xh = self.assert_list_success(self.db_path, "星河科技", [xu])
        self.assertEqual(len(records_xh), 1)

        # 远帆咨询按编号升序返回林宁、周岚，字段与新增/更新结果一致
        records_yf = self.assert_list_success(
            self.db_path, "远帆咨询", [updated_lin, zhou]
        )
        self.assertEqual(
            [r["id"] for r in records_yf], sorted(r["id"] for r in records_yf)
        )

    def test_update_company_same_value_again_still_succeeds_without_new_records(self):
        lin, xu, zhou = self.seed_update_company_contacts()

        first = self.update_company(self.db_path, lin["id"], "远帆咨询")
        updated_lin = self.assert_update_success(
            first, {**lin, "company": "远帆咨询"}
        )

        # 再次提交相同公司仍按成功处理
        second = self.update_company(self.db_path, lin["id"], "远帆咨询")
        self.assert_update_success(second, updated_lin)

        # 不增加记录，联系人总数保持三条，所有记录内容保持不变
        records_xh = self.assert_list_success(self.db_path, "星河科技", [xu])
        records_yf = self.assert_list_success(
            self.db_path, "远帆咨询", [updated_lin, zhou]
        )
        self.assertEqual(len(records_xh) + len(records_yf), 3)

    def test_update_company_invalid_inputs_leave_records_unchanged(self):
        lin, xu, zhou = self.seed_update_company_contacts()

        for (contact_id, company), expected_stderr in INVALID_UPDATE_COMPANY_CASES:
            with self.subTest(contact_id=contact_id, company=company):
                result = self.update_company(self.db_path, contact_id, company)
                self.assert_update_rejected(result, expected_stderr)

                # 拒绝后两家公司的记录逐字段不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_company_invalid_input_does_not_create_missing_database(self):
        for index, ((contact_id, company), expected_stderr) in enumerate(
            INVALID_UPDATE_COMPANY_CASES
        ):
            fresh_db = self.tmpdir / f"update-company-fresh-{index}.sqlite3"
            with self.subTest(contact_id=contact_id, company=company):
                self.assertFalse(fresh_db.exists())
                result = self.update_company(fresh_db, contact_id, company)
                self.assert_update_rejected(result, expected_stderr)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_update_company_unknown_id_reports_not_found_and_keeps_records(self):
        lin, xu, zhou = self.seed_update_company_contacts()

        for unknown_id in (zhou["id"] + 1000, 9223372036854775807):
            with self.subTest(contact_id=unknown_id):
                result = self.update_company(self.db_path, unknown_id, "远帆咨询")
                self.assert_update_rejected(result, "id: contact not found")

                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_company_unknown_id_creates_empty_database(self):
        fresh_db = self.tmpdir / "update-company-unknown.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 合法输入但编号不存在：创建空数据库并返回未找到
        result = self.update_company(fresh_db, "1", "远帆咨询")
        self.assert_update_rejected(result, "id: contact not found")
        self.assertTrue(fresh_db.exists())

        # 随后查询得到空数组
        self.assert_list_success(fresh_db, "星河科技", [])

    def test_update_company_missing_parent_directory_is_rejected_without_being_created(
        self,
    ):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result = self.update_company(fresh_db, "1", "远帆咨询")
        self.assert_update_rejected(result, "db: parent directory does not exist")
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())


if __name__ == "__main__":
    unittest.main()
