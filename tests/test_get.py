"""crm.py get 子命令的回归测试。

固定按编号查看单条联系人的公开行为：

- 成功时退出码 0、标准错误为空，标准输出恰为单个联系人 JSON 对象，
  只含 id、name、email、company 四个字段，编号为整数，
  中文与邮箱大小写保持新增时的原样；
- 编号首尾空白与前导零不影响查询，重复独立调用读到相同内容；
- 查询成功与查询不存在的编号都不改变两家公司的列表内容与数量；
- 无效编号（空串、纯空白、0、负数、小数、全角数字、超出上限）
  输出 ``id: must be a positive integer``；
- 合法但未保存的编号输出 ``id: contact not found``；
- 父目录缺失且编号合法时输出 ``db: parent directory does not exist``，
  编号也无效时只报告编号错误；
- 失败一律退出码 2、标准输出为空、标准错误恰为单行并以换行结束；
- 数据库尚不存在时无效编号不创建文件，合法编号按现有语义创建空数据库
  再报告未找到，随后 list 返回空数组。

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
DB_ERROR_LINE = "db: parent directory does not exist"

# 无效编号：空串、纯空白、0、负数、小数、全角数字、超出 64 位有符号整数上限
INVALID_IDS = [
    "",
    "   ",
    " \t ",
    "0",
    "000",
    "-1",
    "-9223372036854775808",
    "1.5",
    "１２３",
    "１",
    "9223372036854775808",
]

# 合法但样例中未保存的编号：普通未用编号与上限编号
UNKNOWN_IDS = ["99", "9223372036854775807"]


class GetTestCase(unittest.TestCase):
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

    def assert_get_success(self, result, expected):
        """断言查询成功：输出恰为单个联系人 JSON 对象且与期望逐字段一致。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        # 标准输出整体可解析为单个 JSON 对象（不是数组，无多余输出）
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(record, dict)
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertIsInstance(record["id"], int)
        self.assertEqual(record, expected)
        return record

    def assert_get_rejected(self, result, expected_stderr_line):
        """断言 get 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )

    def assert_list_success(self, db_path, company, expected_records):
        """断言 list 返回的记录（含顺序）与期望完全一致。"""
        result = self.list_company(db_path, company)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def seed_sample_contacts(self):
        """在全新数据库依次新增林宁、许禾（星河科技）与周岚（远帆咨询）。"""
        lin = self.assert_add_success(
            self.add_contact(
                self.db_path, "林宁", "Lin.Ning@example.test", "星河科技"
            ),
            {"name": "林宁", "email": "Lin.Ning@example.test", "company": "星河科技"},
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

    # ---- get 成功路径 ----

    def test_get_returns_each_seeded_contact_by_id(self):
        lin, xu, zhou = self.seed_sample_contacts()

        # 按 add 返回的编号逐条查询，结果与新增结果逐字段一致，
        # 中文姓名与邮箱大小写保持原样
        for added in (lin, xu, zhou):
            with self.subTest(contact_id=added["id"]):
                record = self.assert_get_success(
                    self.get_contact(self.db_path, added["id"]), added
                )
                self.assertEqual(record["id"], added["id"])

    def test_get_id_one_returns_lin_ning_not_company_mate_or_array(self):
        lin, _xu, _zhou = self.seed_sample_contacts()
        self.assertEqual(lin["id"], 1)

        # 全新样例数据库中 get --id 1 返回林宁，
        # 不是同公司的许禾，也不是数组
        record = self.assert_get_success(self.get_contact(self.db_path, "1"), lin)
        self.assertEqual(record["name"], "林宁")
        self.assertEqual(record["email"], "Lin.Ning@example.test")
        self.assertEqual(record["company"], "星河科技")

    def test_get_ignores_surrounding_whitespace_and_leading_zeros(self):
        lin, _xu, _zhou = self.seed_sample_contacts()

        for padded in (
            f"  {lin['id']}",
            f"{lin['id']}  ",
            f"\t{lin['id']}\t",
            f"00{lin['id']}",
            f"  00{lin['id']}  ",
        ):
            with self.subTest(contact_id=padded):
                self.assert_get_success(
                    self.get_contact(self.db_path, padded), lin
                )

    def test_get_repeated_independent_calls_read_same_content(self):
        lin, _xu, _zhou = self.seed_sample_contacts()

        first = self.assert_get_success(
            self.get_contact(self.db_path, lin["id"]), lin
        )
        # 再次独立调用读取相同内容
        second = self.assert_get_success(
            self.get_contact(self.db_path, lin["id"]), lin
        )
        self.assertEqual(first, second)

    def test_get_success_and_not_found_leave_lists_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        # 查询成功后两家公司的列表内容和数量保持不变
        self.assert_get_success(self.get_contact(self.db_path, lin["id"]), lin)
        self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

        # 查询不存在的编号后列表内容和数量仍保持不变
        self.assert_get_rejected(
            self.get_contact(self.db_path, "99"), NOT_FOUND_LINE
        )
        self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    # ---- get 错误路径：无效编号 ----

    def test_get_invalid_ids_are_rejected_and_leave_lists_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        for contact_id in INVALID_IDS:
            with self.subTest(contact_id=contact_id):
                result = self.get_contact(self.db_path, contact_id)
                self.assert_get_rejected(result, ID_ERROR_LINE)

                # 拒绝后两家公司的记录内容和数量保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_get_unknown_ids_report_not_found_and_leave_lists_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        for contact_id in UNKNOWN_IDS:
            with self.subTest(contact_id=contact_id):
                result = self.get_contact(self.db_path, contact_id)
                self.assert_get_rejected(result, NOT_FOUND_LINE)

                # 未找到后两家公司的记录内容和数量保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_get_invalid_id_does_not_create_missing_database(self):
        for index, contact_id in enumerate(INVALID_IDS):
            fresh_db = self.tmpdir / f"get-fresh-{index}.sqlite3"
            with self.subTest(contact_id=contact_id):
                self.assertFalse(fresh_db.exists())
                result = self.get_contact(fresh_db, contact_id)
                self.assert_get_rejected(result, ID_ERROR_LINE)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_get_unknown_id_creates_empty_database_then_reports_not_found(self):
        fresh_db = self.tmpdir / "get-unknown.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 父目录存在且编号合法：按现有语义创建空数据库再报告未找到
        result = self.get_contact(fresh_db, "1")
        self.assert_get_rejected(result, NOT_FOUND_LINE)
        self.assertTrue(fresh_db.exists())

        # 随后 list 返回空数组
        self.assert_list_success(fresh_db, "星河科技", [])

    # ---- get 错误路径：父目录缺失 ----

    def test_get_missing_parent_directory_is_rejected_without_being_created(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        # 父目录不存在且编号合法：报告父目录错误，不创建目录或文件
        result = self.get_contact(fresh_db, "1")
        self.assert_get_rejected(result, DB_ERROR_LINE)
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    def test_get_invalid_id_and_missing_parent_reports_id_error_only(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        # 编号也无效时只报告编号错误，且不创建目录或文件
        for contact_id in ("", "   ", "0", "-1", "1.5", "１２３",
                           "9223372036854775808"):
            with self.subTest(contact_id=contact_id):
                result = self.get_contact(fresh_db, contact_id)
                self.assert_get_rejected(result, ID_ERROR_LINE)
                self.assertFalse(missing_parent.exists())
                self.assertFalse(fresh_db.exists())


if __name__ == "__main__":
    unittest.main()
