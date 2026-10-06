"""crm.py update-email 与 update-company 超长编号边界的回归测试。

在 Python 3.11 默认的整数字符串转换位数限制下，由五千个 9 组成的编号
过去会触发未处理的 ValueError（退出码 1 与异常堆栈），而非约定的编号
错误。本文件固定两个入口在该输入边界上的行为：

- 编号去除首尾空白后只允许 ASCII 数字，数值范围 1 至 9223372036854775807；
- 五千个 9、五千个 0、超出上限的数字一律退出码 2、标准输出为空、
  标准错误恰为单行 ``id: must be a positive integer``（行尾带换行）；
- 五千个 0 后接 1 与编号 1 指向同一条记录，前导零数量不受限制；
- 编号与新值同时无效时只报告编号错误；
- 拒绝时不改变联系人内容与数量，数据库尚不存在时不创建文件，
  父目录缺失时也不创建目录。

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

# 五千个 9（超长且远超上限）、五千个 0（数值为 0）、超出上限的数字
OVERLONG_INVALID_IDS = [
    "9" * 5000,
    "0" * 5000,
    "9223372036854775808",
    "1" + "0" * 4999,
]

# 五千个 0 后接 1：数值仍为 1，前导零再多也合法
LONG_LEADING_ZERO_ID = "0" * 5000 + "1"


class UpdateIdBoundaryTestCase(unittest.TestCase):
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

    def assert_id_error(self, result):
        """断言编号被拒：退出码 2、标准输出为空、标准错误恰为单行编号错误。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        # 恰为一行、行尾带换行，且不含异常堆栈
        self.assertEqual(result.stderr.decode("utf-8"), ID_ERROR_LINE + "\n")

    def assert_single_contact_object(self, result, expected):
        """断言成功输出为单个联系人 JSON 对象且与期望逐字段一致。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(record, dict)
        self.assertEqual(record, expected)
        return record

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

        lin = add("林宁", "linning@example.test", "星河科技")
        xu = add("许禾", "xuhe@example.test", "星河科技")
        zhou = add("周岚", "zhoulan@example.test", "远帆咨询")
        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])
        return lin, xu, zhou

    # ---- update-email：超长非法编号 ----

    def test_update_email_rejects_overlong_ids_without_changing_records(self):
        lin, xu, zhou = self.seed_contacts()

        for contact_id in OVERLONG_INVALID_IDS:
            with self.subTest(contact_id_length=len(contact_id)):
                result = self.update_email(
                    self.db_path, contact_id, "new@example.test"
                )
                self.assert_id_error(result)

                # 拒绝后两家公司的记录内容和数量保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_email_reports_id_error_when_id_and_email_both_invalid(self):
        lin, xu, zhou = self.seed_contacts()

        # 五千个 9 与无效邮箱同时提交：只报告编号错误
        result = self.update_email(self.db_path, "9" * 5000, "noatsign.example.test")
        self.assert_id_error(result)

        self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_email_overlong_id_does_not_create_database(self):
        for index, contact_id in enumerate(OVERLONG_INVALID_IDS):
            fresh_db = self.tmpdir / f"email-fresh-{index}.sqlite3"
            with self.subTest(contact_id_length=len(contact_id)):
                self.assertFalse(fresh_db.exists())
                result = self.update_email(
                    fresh_db, contact_id, "new@example.test"
                )
                self.assert_id_error(result)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_update_email_overlong_id_with_missing_parent_creates_nothing(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result = self.update_email(fresh_db, "9" * 5000, "new@example.test")
        self.assert_id_error(result)
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    # ---- update-email：五千个 0 后接 1 仍指向编号 1 ----

    def test_update_email_long_leading_zero_id_updates_contact_one(self):
        lin, xu, zhou = self.seed_contacts()
        self.assertEqual(lin["id"], 1)

        result = self.update_email(
            self.db_path, LONG_LEADING_ZERO_ID, "  new@example.test  "
        )
        # 成功：退出码 0、标准错误为空，输出为原编号、姓名、公司与新邮箱
        updated_lin = self.assert_single_contact_object(
            result,
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

    def test_update_email_padded_long_leading_zero_id_strips_whitespace(self):
        lin, _xu, _zhou = self.seed_contacts()

        # 首尾空白与五千个前导零同时存在时仍解析为编号 1
        result = self.update_email(
            self.db_path, f"  {LONG_LEADING_ZERO_ID}\t", "new@example.test"
        )
        self.assert_single_contact_object(
            result, {**lin, "email": "new@example.test"}
        )

    # ---- update-company：超长非法编号 ----

    def test_update_company_rejects_overlong_ids_without_changing_records(self):
        lin, xu, zhou = self.seed_contacts()

        for contact_id in OVERLONG_INVALID_IDS:
            with self.subTest(contact_id_length=len(contact_id)):
                result = self.update_company(self.db_path, contact_id, "远帆咨询")
                self.assert_id_error(result)

                # 拒绝后两家公司的记录内容和数量保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_company_reports_id_error_when_id_and_company_both_invalid(self):
        lin, xu, zhou = self.seed_contacts()

        # 五千个 9 与空白公司同时提交：只报告编号错误
        result = self.update_company(self.db_path, "9" * 5000, "   ")
        self.assert_id_error(result)

        self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_company_overlong_id_does_not_create_database(self):
        for index, contact_id in enumerate(OVERLONG_INVALID_IDS):
            fresh_db = self.tmpdir / f"company-fresh-{index}.sqlite3"
            with self.subTest(contact_id_length=len(contact_id)):
                self.assertFalse(fresh_db.exists())
                result = self.update_company(fresh_db, contact_id, "远帆咨询")
                self.assert_id_error(result)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_update_company_overlong_id_with_missing_parent_creates_nothing(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result = self.update_company(fresh_db, "0" * 5000, "远帆咨询")
        self.assert_id_error(result)
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    # ---- update-company：五千个 0 后接 1 仍指向编号 1 ----

    def test_update_company_long_leading_zero_id_moves_contact_one(self):
        lin, xu, zhou = self.seed_contacts()
        self.assertEqual(lin["id"], 1)

        result = self.update_company(
            self.db_path, f"  {LONG_LEADING_ZERO_ID}  ", "  远帆咨询  "
        )
        # 只改变公司：编号、姓名与邮箱保持原值
        updated_lin = self.assert_single_contact_object(
            result,
            {
                "id": lin["id"],
                "name": "林宁",
                "email": "linning@example.test",
                "company": "远帆咨询",
            },
        )

        # 星河科技只剩许禾；远帆咨询按编号升序为林宁、周岚
        self.assert_list_success(self.db_path, "星河科技", [xu])
        records_yf = self.assert_list_success(
            self.db_path, "远帆咨询", [updated_lin, zhou]
        )
        self.assertEqual(
            [r["id"] for r in records_yf], [lin["id"], zhou["id"]]
        )


if __name__ == "__main__":
    unittest.main()
