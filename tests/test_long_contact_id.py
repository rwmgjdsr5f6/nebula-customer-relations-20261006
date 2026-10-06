"""crm.py update-email / update-company 超长编号输入边界的回归测试。

编号去除首尾空白后只允许 ASCII 数字 0 至 9，数值范围仍为
1 至 9223372036854775807。本测试覆盖 Python 3.11 默认整数转换限制下的
超长十进制编号：

- 五千个 9、五千个 0、超出上限的编号均以退出码 2 结束，标准输出为空，
  标准错误恰好为一行 ``id: must be a positive integer``（带换行，无堆栈）；
- 五千个 0 后接 1 与编号 1 指向同一条记录，前导零再多也不拒绝；
- 编号与新值同时无效时只报告编号错误；
- 数据库尚不存在时不创建文件，父目录缺失时连目录也不创建；
- 范围内查无记录的编号（含上限值）仍返回单行 ``id: contact not found``。

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

ID_INVALID_LINE = "id: must be a positive integer"
ID_NOT_FOUND_LINE = "id: contact not found"

FIVE_THOUSAND_NINES = "9" * 5000
FIVE_THOUSAND_ZEROS = "0" * 5000
LEADING_ZEROS_ONE = "0" * 5000 + "1"
MAX_ID = "9223372036854775807"
OVER_MAX_ID = "9223372036854775808"

INVALID_EMAIL = "noatsign.example.test"
BLANK_COMPANY = "   "


class LongContactIdTestCase(unittest.TestCase):
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

    def update_email(self, db_path, contact_id, email):
        return self.run_crm(
            db_path, "update-email", "--id", str(contact_id), "--email", email
        )

    def update_company(self, db_path, contact_id, company):
        return self.run_crm(
            db_path, "update-company", "--id", str(contact_id), "--company", company
        )

    def assert_single_contact_object(self, result):
        """断言成功：退出码 0、标准错误为空、标准输出整体为单个联系人 JSON 对象。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(record, dict)
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertIsInstance(record["id"], int)
        return record

    def assert_list_success(self, db_path, company, expected_records):
        """断言 list 返回的记录（含顺序）与期望完全一致。"""
        result = self.list_company(db_path, company)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def assert_id_error(self, result, expected_line=ID_INVALID_LINE):
        """断言编号错误：退出码 2、标准输出为空、标准错误恰好一行（带换行）。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr.decode("utf-8"), expected_line + "\n")

    def seed_contacts(self):
        """在全新数据库依次新增星河科技林宁/许禾、远帆咨询周岚（邮箱各不相同）。"""
        lin = self.assert_single_contact_object(
            self.add_contact(
                self.db_path, "林宁", "linning@example.test", "星河科技"
            )
        )
        xu = self.assert_single_contact_object(
            self.add_contact(self.db_path, "许禾", "xuhe@example.test", "星河科技")
        )
        zhou = self.assert_single_contact_object(
            self.add_contact(
                self.db_path, "周岚", "zhoulan@example.test", "远帆咨询"
            )
        )
        self.assertEqual([lin["id"], xu["id"], zhou["id"]], [1, 2, 3])
        return lin, xu, zhou

    # ---- 五千个 0 后接 1：成功路径 ----

    def test_update_email_accepts_five_thousand_leading_zeros_then_one(self):
        lin, xu, zhou = self.seed_contacts()

        # 五千个 0 后接 1 与编号 1 指向同一条记录（林宁）
        result = self.update_email(self.db_path, LEADING_ZEROS_ONE, "new@example.test")
        updated_lin = self.assert_single_contact_object(result)
        # 输出仍为原编号、姓名、公司加新邮箱组成的单个联系人 JSON 对象
        self.assertEqual(
            updated_lin,
            {
                "id": lin["id"],
                "name": "林宁",
                "email": "new@example.test",
                "company": "星河科技",
            },
        )

        # 重新调用 list 可读到修改，其他两条记录不变
        self.assert_list_success(self.db_path, "星河科技", [updated_lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_company_accepts_five_thousand_leading_zeros_then_one(self):
        lin, xu, zhou = self.seed_contacts()

        # 相同编号形式把林宁改到远帆咨询，只改变该联系人的公司
        result = self.update_company(self.db_path, LEADING_ZEROS_ONE, "远帆咨询")
        updated_lin = self.assert_single_contact_object(result)
        self.assertEqual(
            updated_lin,
            {
                "id": lin["id"],
                "name": "林宁",
                "email": "linning@example.test",
                "company": "远帆咨询",
            },
        )

        # 星河科技只剩许禾；远帆咨询按编号升序为林宁、周岚，周岚不变
        self.assert_list_success(self.db_path, "星河科技", [xu])
        self.assert_list_success(self.db_path, "远帆咨询", [updated_lin, zhou])

    # ---- 超长 / 越界编号：两个入口都报编号错误且数据不变 ----

    def test_oversized_ids_are_rejected_by_both_entries(self):
        lin, xu, zhou = self.seed_contacts()

        for contact_id, label in (
            (FIVE_THOUSAND_NINES, "five-thousand nines"),
            (FIVE_THOUSAND_ZEROS, "five-thousand zeros"),
            (OVER_MAX_ID, "over max"),
            ("0" * 5000 + OVER_MAX_ID, "padded over max"),
        ):
            with self.subTest(entry="update-email", case=label):
                result = self.update_email(self.db_path, contact_id, "new@example.test")
                self.assert_id_error(result)
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

            with self.subTest(entry="update-company", case=label):
                result = self.update_company(self.db_path, contact_id, "远帆咨询")
                self.assert_id_error(result)
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_oversized_id_with_invalid_new_value_reports_only_id_error(self):
        lin, xu, zhou = self.seed_contacts()

        # 编号与新值同时无效时只报告编号错误
        result_email = self.update_email(
            self.db_path, FIVE_THOUSAND_NINES, INVALID_EMAIL
        )
        self.assert_id_error(result_email)

        result_company = self.update_company(
            self.db_path, FIVE_THOUSAND_NINES, BLANK_COMPANY
        )
        self.assert_id_error(result_company)

        # 联系人内容与数量保持不变
        self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_oversized_id_does_not_create_missing_database(self):
        for index, contact_id in enumerate(
            (FIVE_THOUSAND_NINES, FIVE_THOUSAND_ZEROS, OVER_MAX_ID)
        ):
            fresh_db = self.tmpdir / f"oversized-fresh-{index}.sqlite3"
            with self.subTest(contact_id=contact_id):
                self.assertFalse(fresh_db.exists())

                result_email = self.update_email(
                    fresh_db, contact_id, "new@example.test"
                )
                self.assert_id_error(result_email)
                result_company = self.update_company(
                    fresh_db, contact_id, "远帆咨询"
                )
                self.assert_id_error(result_company)

                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_oversized_id_with_missing_parent_creates_nothing(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        # 即使父目录缺失，编号错误也优先返回，不创建目录或文件
        result_email = self.update_email(
            fresh_db, FIVE_THOUSAND_NINES, "new@example.test"
        )
        self.assert_id_error(result_email)
        result_company = self.update_company(
            fresh_db, FIVE_THOUSAND_NINES, "远帆咨询"
        )
        self.assert_id_error(result_company)
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    # ---- 范围内但查无记录（含上限值）：contact not found ----

    def test_in_range_unknown_ids_report_not_found(self):
        lin, xu, zhou = self.seed_contacts()

        for unknown_id in (zhou["id"] + 1000, MAX_ID):
            with self.subTest(entry="update-email", contact_id=unknown_id):
                result = self.update_email(
                    self.db_path, unknown_id, "new@example.test"
                )
                self.assert_id_error(result, ID_NOT_FOUND_LINE)
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

            with self.subTest(entry="update-company", contact_id=unknown_id):
                result = self.update_company(self.db_path, unknown_id, "远帆咨询")
                self.assert_id_error(result, ID_NOT_FOUND_LINE)
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])


if __name__ == "__main__":
    unittest.main()
