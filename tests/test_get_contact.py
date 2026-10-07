"""crm.py get 子命令（按编号查看单条联系人）的回归测试。

固定 get 的公开命令行行为：

- 成功时退出码 0、标准错误为空，标准输出只有一个联系人 JSON 对象，
  含 id/name/email/company 四个字段，编号为整数，其余内容与 add 结果一致，
  中文与邮箱大小写保持原样；
- 编号首尾空白会被清理、允许前导零，清理后指向同一条记录；
- 全新样例数据库中 get --id 1 返回林宁，而不是同公司其他联系人或数组；
- 编号无效输出 id: must be a positive integer，记录不存在输出
  id: contact not found，父目录缺失输出 db: parent directory does not exist，
  三类错误均退出码 2、标准输出为空、标准错误恰为一行并以换行结束；
- 数据库尚不存在时无效编号不创建文件；父目录存在且编号合法时，
  get 按现有语义创建空数据库再报告未找到，随后 list 返回空数组。

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

# 空串、纯空白、0、负数、小数、全角数字及超过 64 位有符号整数上限的编号
INVALID_IDS = [
    "",
    "   ",
    " \t ",
    "0",
    "-1",
    "1.5",
    "１",  # 全角数字 1（U+FF11），不属于 ASCII 数字
    "9223372036854775808",
]

# 合法但样例中未保存的编号（含 64 位有符号整数上限）
UNSAVED_IDS = ["99", "9223372036854775807"]


class GetContactTestCase(unittest.TestCase):
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

        退出码 0、标准错误为空，标准输出整体是单个联系人 JSON 对象
        （不是数组），只含 id/name/email/company 四个字段且逐字段与期望一致。
        """
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
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
        """通过 add 入口在全新数据库依次准备固定样例。

        星河科技：林宁（Lin.Ning@example.test）、许禾（xu@example.test）；
        远帆咨询：周岚（zhou@example.test）。返回三条新增结果。
        """
        def add(name, email, company):
            result = self.add_contact(self.db_path, name, email, company)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertEqual(result.stderr, b"")
            record = json.loads(result.stdout.decode("utf-8"))
            self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
            self.assertIsInstance(record["id"], int)
            return record

        lin = add("林宁", "Lin.Ning@example.test", "星河科技")
        xu = add("许禾", "xu@example.test", "星河科技")
        zhou = add("周岚", "zhou@example.test", "远帆咨询")
        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])
        return lin, xu, zhou

    # ---- 查询成功：输出形态与内容 ----

    def test_get_returns_single_object_matching_add_result(self):
        lin, xu, zhou = self.seed_sample_contacts()

        for added in (lin, xu, zhou):
            with self.subTest(contact_id=added["id"]):
                result = self.get_contact(self.db_path, added["id"])
                # 标准输出是单个联系人 JSON 对象，内容与新增结果完全一致
                record = self.assert_get_success(result, added)
                self.assertNotIsInstance(record, list)
                # 中文与邮箱大小写保持原样
                self.assertEqual(record["name"], added["name"])
                self.assertEqual(record["email"], added["email"])

    def test_get_id_one_on_fresh_sample_db_returns_lin_ning(self):
        lin, _xu, _zhou = self.seed_sample_contacts()
        self.assertEqual(lin["id"], 1)

        # 全新样例数据库中编号 1 是林宁，而不是同公司的许禾或数组
        result = self.get_contact(self.db_path, 1)
        self.assert_get_success(
            result,
            {
                "id": 1,
                "name": "林宁",
                "email": "Lin.Ning@example.test",
                "company": "星河科技",
            },
        )

    def test_get_padded_and_leading_zero_ids_return_same_record(self):
        lin, _xu, _zhou = self.seed_sample_contacts()

        for raw_id in ("  1  ", "\t1\t", " \t01\t ", "0001", "  000001  "):
            with self.subTest(raw_id=raw_id):
                result = self.get_contact(self.db_path, raw_id)
                # 首尾空白被清理、前导零被允许，仍查询编号 1 的林宁
                self.assert_get_success(result, lin)

    def test_get_repeated_independent_calls_return_same_content(self):
        lin, _xu, _zhou = self.seed_sample_contacts()

        first = self.get_contact(self.db_path, lin["id"])
        second = self.get_contact(self.db_path, f"  {lin['id']:010d}  ")
        # 两次独立进程调用读到的内容完全相同
        self.assertEqual(first.returncode, 0, first.stderr.decode("utf-8"))
        self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8"))
        self.assertEqual(first.stdout, second.stdout)
        self.assert_get_success(first, lin)
        self.assert_get_success(second, lin)

    def test_get_success_and_not_found_leave_company_lists_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        # 查询成功不改变两家公司的列表内容及数量
        self.assert_get_success(self.get_contact(self.db_path, lin["id"]), lin)
        self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

        # 查询不存在的编号后两家公司的列表内容及数量仍保持不变
        self.assert_get_rejected(
            self.get_contact(self.db_path, "99"), NOT_FOUND_LINE
        )
        self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    # ---- 编号无效 ----

    def test_get_invalid_ids_are_rejected(self):
        self.seed_sample_contacts()

        for raw_id in INVALID_IDS:
            with self.subTest(raw_id=raw_id):
                result = self.get_contact(self.db_path, raw_id)
                self.assert_get_rejected(result, ID_ERROR_LINE)

    def test_get_invalid_ids_leave_records_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        for raw_id in INVALID_IDS:
            with self.subTest(raw_id=raw_id):
                self.assert_get_rejected(
                    self.get_contact(self.db_path, raw_id), ID_ERROR_LINE
                )
                # 拒绝后两家公司的记录内容和数量保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_get_invalid_id_does_not_create_missing_database(self):
        for index, raw_id in enumerate(INVALID_IDS):
            fresh_db = self.tmpdir / f"get-invalid-fresh-{index}.sqlite3"
            with self.subTest(raw_id=raw_id):
                self.assertFalse(fresh_db.exists())
                result = self.get_contact(fresh_db, raw_id)
                self.assert_get_rejected(result, ID_ERROR_LINE)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    # ---- 编号合法但记录不存在 ----

    def test_get_unsaved_ids_report_not_found(self):
        self.seed_sample_contacts()

        for raw_id in UNSAVED_IDS:
            with self.subTest(raw_id=raw_id):
                result = self.get_contact(self.db_path, raw_id)
                self.assert_get_rejected(result, NOT_FOUND_LINE)

    def test_get_unsaved_ids_leave_records_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        for raw_id in UNSAVED_IDS:
            with self.subTest(raw_id=raw_id):
                self.assert_get_rejected(
                    self.get_contact(self.db_path, raw_id), NOT_FOUND_LINE
                )
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_get_valid_id_on_missing_database_creates_empty_database(self):
        fresh_db = self.tmpdir / "get-unknown.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 父目录存在、编号合法：按现有语义创建空数据库再报告未找到
        result = self.get_contact(fresh_db, "99")
        self.assert_get_rejected(result, NOT_FOUND_LINE)
        self.assertTrue(fresh_db.exists())

        # 随后 list 返回空数组
        self.assert_list_success(fresh_db, "星河科技", [])
        self.assert_list_success(fresh_db, "远帆咨询", [])

    # ---- 父目录缺失 ----

    def test_get_missing_parent_directory_with_valid_id_creates_nothing(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result = self.get_contact(fresh_db, "1")
        self.assert_get_rejected(result, DB_ERROR_LINE)
        # 不创建目录或文件
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    def test_get_missing_parent_directory_with_invalid_id_reports_id_error(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        # 编号也无效时只报告编号错误，不创建目录或文件
        for raw_id in ("", "   ", "0", "-1", "1.5", "１", "9223372036854775808"):
            with self.subTest(raw_id=raw_id):
                result = self.get_contact(fresh_db, raw_id)
                self.assert_get_rejected(result, ID_ERROR_LINE)
                self.assertFalse(missing_parent.exists())
                self.assertFalse(fresh_db.exists())


if __name__ == "__main__":
    unittest.main()
