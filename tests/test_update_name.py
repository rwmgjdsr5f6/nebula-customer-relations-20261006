"""crm.py update-name 子命令行为的回归测试。

仅使用 Python 3 标准库 unittest，通过子进程执行 crm.py，
所有样例数据都放在独立的临时目录中，测试结束后自动清理。
在项目根目录运行：python -m unittest discover -s tests

本次只覆盖 update-name 入口；add 与 list 仅用于准备数据与复查结果。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CRM_SCRIPT = PROJECT_ROOT / "crm.py"

# (update-name 子命令的 --id 与 --name 参数, 期望的标准错误)
INVALID_UPDATE_NAME_CASES = [
    # 编号为 0 且姓名为空白：编号先校验，只报告编号错误
    (("0", "   "), "id: must be a positive integer"),
    (("0", ""), "id: must be a positive integer"),
    # 合法编号配合空串或纯空白姓名
    (("1", ""), "name: must not be empty"),
    (("1", "   "), "name: must not be empty"),
    (("1", " \t "), "name: must not be empty"),
]


class UpdateNameTestCase(unittest.TestCase):
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

    def list_company_name(self, db_path, company, name):
        return self.run_crm(
            db_path, "list", "--company", company, "--name", name
        )

    def update_name(self, db_path, contact_id, name):
        return self.run_crm(
            db_path, "update-name", "--id", str(contact_id), "--name", name
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

    def assert_list_name_success(self, db_path, company, name, expected_records):
        """断言带 --name 的 list 返回的记录（含顺序）与期望完全一致。"""
        result = self.list_company_name(db_path, company, name)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def seed_update_name_contacts(self):
        """新增 update-name 固定样例：林宁/许禾（星河科技）、周岚（远帆咨询）。"""
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
        # 全新数据库中编号依次为 1、2、3
        self.assertEqual((lin["id"], xu["id"], zhou["id"]), (1, 2, 3))
        return lin, xu, zhou

    def assert_update_rejected(self, result, expected_stderr_line):
        """断言 update-name 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )

    def test_update_name_success_preserves_internal_spaces_and_is_queryable(self):
        lin, xu, zhou = self.seed_update_name_contacts()

        # 编号与姓名均带首尾空白，编号还带前导零
        result = self.update_name(self.db_path, " 001 ", "  林 安  ")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")

        # 标准输出恰为单个完整联系人 JSON 对象（一行），无多余内容
        expected = {
            "id": 1,
            "name": "林 安",
            "email": "lin@example.test",
            "company": "星河科技",
        }
        payload = result.stdout.decode("utf-8")
        self.assertEqual(payload, json.dumps(expected, ensure_ascii=False) + "\n")
        updated_lin = json.loads(payload)
        self.assertEqual(set(updated_lin.keys()), {"id", "name", "email", "company"})
        self.assertEqual(updated_lin, expected)
        # 姓名首尾空白被清除、内部空格保留；编号、邮箱和公司不变
        self.assertEqual(updated_lin["name"], "林 安")
        self.assertEqual(updated_lin["id"], lin["id"])
        self.assertEqual(updated_lin["email"], lin["email"])
        self.assertEqual(updated_lin["company"], lin["company"])

        # 在独立进程中查询同一数据库：星河科技仍按编号升序返回两人
        records_xh = self.assert_list_success(
            self.db_path, "星河科技", [updated_lin, xu]
        )
        self.assertEqual([record["id"] for record in records_xh], [1, 2])
        # 远帆咨询的记录不变
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

        # 星河科技按新姓名筛选能找到编号 1
        self.assert_list_name_success(
            self.db_path, "星河科技", "林 安", [updated_lin]
        )
        # 按旧姓名林宁筛选得到空数组
        self.assert_list_name_success(self.db_path, "星河科技", "林宁", [])

    def test_update_name_same_value_again_still_succeeds_without_new_records(self):
        lin, xu, zhou = self.seed_update_name_contacts()

        first = self.update_name(self.db_path, " 001 ", "  林 安  ")
        updated_lin = {
            "id": 1,
            "name": "林 安",
            "email": "lin@example.test",
            "company": "星河科技",
        }
        self.assertEqual(first.returncode, 0, first.stderr.decode("utf-8"))
        self.assertEqual(json.loads(first.stdout.decode("utf-8")), updated_lin)

        # 再次提交相同姓名仍按成功处理
        second = self.update_name(self.db_path, 1, "林 安")
        self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8"))
        self.assertEqual(second.stderr, b"")
        self.assertEqual(json.loads(second.stdout.decode("utf-8")), updated_lin)

        # 不增加记录：星河科技仍是两人、远帆咨询仍是一人，内容保持不变
        self.assert_list_success(self.db_path, "星河科技", [updated_lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_name_invalid_inputs_leave_records_unchanged(self):
        lin, xu, zhou = self.seed_update_name_contacts()

        for (contact_id, name), expected_stderr in INVALID_UPDATE_NAME_CASES:
            with self.subTest(contact_id=contact_id, name=name):
                result = self.update_name(self.db_path, contact_id, name)
                self.assert_update_rejected(result, expected_stderr)

                # 拒绝后两家公司的记录逐字段不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_name_unknown_id_reports_not_found_and_keeps_records(self):
        lin, xu, zhou = self.seed_update_name_contacts()

        # 编号 99 配合法姓名：联系人不存在
        result = self.update_name(self.db_path, "99", "林 安")
        self.assert_update_rejected(result, "id: contact not found")

        # 已有联系人逐字段不变
        self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_name_invalid_input_does_not_create_missing_database(self):
        for index, ((contact_id, name), expected_stderr) in enumerate(
            INVALID_UPDATE_NAME_CASES
        ):
            fresh_db = self.tmpdir / f"update-name-fresh-{index}.sqlite3"
            with self.subTest(contact_id=contact_id, name=name):
                self.assertFalse(fresh_db.exists())
                result = self.update_name(fresh_db, contact_id, name)
                self.assert_update_rejected(result, expected_stderr)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_update_name_unknown_id_creates_empty_database(self):
        fresh_db = self.tmpdir / "update-name-unknown.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 合法输入但编号不存在：创建空数据库并返回未找到
        result = self.update_name(fresh_db, "99", "林 安")
        self.assert_update_rejected(result, "id: contact not found")
        self.assertTrue(fresh_db.exists())

        # 随后查询得到空数组
        self.assert_list_success(fresh_db, "星河科技", [])

    def test_update_name_missing_parent_directory_is_rejected(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        # 输入合法但父目录缺失：只报告 db 错误，不创建目录或文件
        result = self.update_name(fresh_db, "1", "林 安")
        self.assert_update_rejected(result, "db: parent directory does not exist")
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())


if __name__ == "__main__":
    unittest.main()
