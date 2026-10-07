"""crm.py delete 子命令（按编号删除单条联系人）的回归测试。

固定 delete 的公开命令行行为：

- 成功时退出码 0、标准错误为空，标准输出只有被删除联系人的单个 JSON
  对象，含 id/name/email/company 四个字段，编号为整数，中文与邮箱大小写
  与 add 结果保持原样；
- 编号首尾空白会被清理、允许前导零（如 " 001 " 指向编号 1 的林宁）；
- 删除后重新查询：被删联系人消失，同公司其余联系人与其它公司的联系人
  编号及字段不变；查询或再次删除同一编号均报 id: contact not found；
- 编号无效输出 id: must be a positive integer，合法但未保存的编号输出
  id: contact not found，父目录缺失输出 db: parent directory does not
  exist，三类错误均退出码 2、标准输出为空、标准错误恰为一行并以换行
  结束，不出现异常堆栈，已有记录不变；
- 数据库尚不存在时无效编号不创建文件；父目录存在且编号合法时，delete
  按现有语义创建空数据库再报告未找到，随后 list 返回空数组；父目录缺失
  时不创建目录或文件，编号也无效时优先报告编号错误。

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

# 空串、纯空白、0、负数、小数、字母、全角数字及超过 64 位有符号整数上限的编号
INVALID_IDS = [
    "",
    "   ",
    " \t ",
    "0",
    "-1",
    "1.5",
    "abc",
    "１",  # 全角数字 1（U+FF11），不属于 ASCII 数字
    "9223372036854775808",
]

# 合法但样例中未保存的编号
UNSAVED_IDS = ["99"]


class DeleteContactTestCase(unittest.TestCase):
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

    def delete_contact(self, db_path, contact_id):
        return self.run_crm(db_path, "delete", "--id", str(contact_id))

    def get_contact(self, db_path, contact_id):
        return self.run_crm(db_path, "get", "--id", str(contact_id))

    def list_company(self, db_path, company):
        return self.run_crm(db_path, "list", "--company", company)

    def assert_delete_success(self, result, expected):
        """断言 delete 成功并返回解析后的联系人字典。

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

    def assert_delete_rejected(self, result, expected_stderr_line):
        """断言 delete 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
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

        星河科技：林宁（Lin@example.test）、许禾（xu@example.test）；
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

        lin = add("林宁", "Lin@example.test", "星河科技")
        xu = add("许禾", "xu@example.test", "星河科技")
        zhou = add("周岚", "zhou@example.test", "远帆咨询")
        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])
        return lin, xu, zhou

    # ---- 删除成功：输出形态与内容 ----

    def test_delete_returns_single_object_matching_add_result(self):
        lin, _xu, _zhou = self.seed_sample_contacts()

        # 标准输出是单个联系人 JSON 对象，内容与林宁的新增结果完全一致
        result = self.delete_contact(self.db_path, lin["id"])
        record = self.assert_delete_success(result, lin)
        self.assertNotIsInstance(record, list)
        # 中文与邮箱大小写保持原样
        self.assertEqual(record["name"], "林宁")
        self.assertEqual(record["email"], "Lin@example.test")
        self.assertEqual(record["company"], "星河科技")

    def test_delete_padded_and_leading_zero_id_deletes_lin_ning(self):
        lin, _xu, _zhou = self.seed_sample_contacts()
        self.assertEqual(lin["id"], 1)

        # 首尾空白被清理、前导零被允许，" 001 " 删除编号 1 的林宁
        result = self.delete_contact(self.db_path, " 001 ")
        self.assert_delete_success(
            result,
            {
                "id": 1,
                "name": "林宁",
                "email": "Lin@example.test",
                "company": "星河科技",
            },
        )

    def test_delete_removes_only_target_and_keeps_others_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        self.assert_delete_success(self.delete_contact(self.db_path, " 001 "), lin)

        # 重新启动查询：星河科技只剩许禾，远帆咨询仍为周岚，编号和字段不变
        self.assert_list_success(self.db_path, "星河科技", [xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])
        get_xu = self.get_contact(self.db_path, xu["id"])
        self.assertEqual(get_xu.returncode, 0, get_xu.stderr.decode("utf-8"))
        self.assertEqual(json.loads(get_xu.stdout.decode("utf-8")), xu)
        get_zhou = self.get_contact(self.db_path, zhou["id"])
        self.assertEqual(get_zhou.returncode, 0, get_zhou.stderr.decode("utf-8"))
        self.assertEqual(json.loads(get_zhou.stdout.decode("utf-8")), zhou)

    def test_get_and_second_delete_of_deleted_id_report_not_found(self):
        lin, xu, zhou = self.seed_sample_contacts()

        self.assert_delete_success(self.delete_contact(self.db_path, " 001 "), lin)

        # 查询已删除的林宁返回 id: contact not found
        get_result = self.get_contact(self.db_path, lin["id"])
        self.assertEqual(get_result.returncode, 2)
        self.assertEqual(get_result.stdout, b"")
        self.assertEqual(
            get_result.stderr.decode("utf-8"), NOT_FOUND_LINE + "\n"
        )

        # 再次删除相同编号同样返回 id: contact not found
        self.assert_delete_rejected(
            self.delete_contact(self.db_path, lin["id"]), NOT_FOUND_LINE
        )

        # 剩余记录不变
        self.assert_list_success(self.db_path, "星河科技", [xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    # ---- 编号无效 ----

    def test_delete_invalid_ids_are_rejected(self):
        self.seed_sample_contacts()

        for raw_id in INVALID_IDS:
            with self.subTest(raw_id=raw_id):
                result = self.delete_contact(self.db_path, raw_id)
                self.assert_delete_rejected(result, ID_ERROR_LINE)

    def test_delete_invalid_ids_leave_records_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        for raw_id in INVALID_IDS:
            with self.subTest(raw_id=raw_id):
                self.assert_delete_rejected(
                    self.delete_contact(self.db_path, raw_id), ID_ERROR_LINE
                )
                # 拒绝后两家公司的记录内容和数量保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_delete_invalid_id_does_not_create_missing_database(self):
        for index, raw_id in enumerate(INVALID_IDS):
            fresh_db = self.tmpdir / f"delete-invalid-fresh-{index}.sqlite3"
            with self.subTest(raw_id=raw_id):
                self.assertFalse(fresh_db.exists())
                result = self.delete_contact(fresh_db, raw_id)
                self.assert_delete_rejected(result, ID_ERROR_LINE)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    # ---- 编号合法但记录不存在 ----

    def test_delete_unsaved_ids_report_not_found(self):
        self.seed_sample_contacts()

        for raw_id in UNSAVED_IDS:
            with self.subTest(raw_id=raw_id):
                result = self.delete_contact(self.db_path, raw_id)
                self.assert_delete_rejected(result, NOT_FOUND_LINE)

    def test_delete_unsaved_ids_leave_records_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        for raw_id in UNSAVED_IDS:
            with self.subTest(raw_id=raw_id):
                self.assert_delete_rejected(
                    self.delete_contact(self.db_path, raw_id), NOT_FOUND_LINE
                )
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_delete_valid_id_on_missing_database_creates_empty_database(self):
        fresh_db = self.tmpdir / "delete-unknown.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 父目录存在、编号合法：按现有语义创建空数据库再报告未找到
        result = self.delete_contact(fresh_db, "99")
        self.assert_delete_rejected(result, NOT_FOUND_LINE)
        self.assertTrue(fresh_db.exists())

        # 随后 list 返回空数组
        self.assert_list_success(fresh_db, "星河科技", [])

    # ---- 父目录缺失 ----

    def test_delete_missing_parent_directory_with_valid_id_creates_nothing(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result = self.delete_contact(fresh_db, "1")
        self.assert_delete_rejected(result, DB_ERROR_LINE)
        # 不创建目录或文件
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    def test_delete_missing_parent_directory_with_invalid_id_reports_id_error(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        # 编号也无效时优先报告编号错误，不创建目录或文件
        for raw_id in INVALID_IDS:
            with self.subTest(raw_id=raw_id):
                result = self.delete_contact(fresh_db, raw_id)
                self.assert_delete_rejected(result, ID_ERROR_LINE)
                self.assertFalse(missing_parent.exists())
                self.assertFalse(fresh_db.exists())


if __name__ == "__main__":
    unittest.main()
