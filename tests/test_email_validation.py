"""crm.py 邮箱校验规则的回归测试。

add 与 update-email 两个入口共用同一套轻量邮箱规则：
恰好一个 @、用户名与域名均非空、域名至少含一个点且点分各段非空、
地址内部没有空白；首尾空白在保存前清理，大小写、加号及用户名内部
的点等字符原样保留。

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

EMAIL_ERROR_LINE = "email: invalid email address"

# (原始输入, 清理后应保存的邮箱)：首尾空白被去掉，内部字符原样保留
ACCEPTED_EMAIL_CASES = [
    # 前后带空格，保留大小写与加号
    ("  User+tag@sub.Example.test  ", "User+tag@sub.Example.test"),
    # 用户名内部的点按现有规则接受
    ("a..b@example.test", "a..b@example.test"),
]

# 应被拒绝的邮箱样例（提交时其他参数均合法）
REJECTED_EMAILS = [
    "@example.test",  # 用户名为空
    "a@",  # 域名为空
    "a@.example.test",  # 域名首段为空
    "a@example.test.",  # 域名末段为空
    "a@example..test",  # 域名中间空段
    "a@@example.test",  # 含两个 @
    "a@exampletest",  # 域名没有点
    "",  # 空字符串
    "a b@example.test",  # 用户名含内部空格
    "a\tb@example.test",  # 用户名含制表符
    "a@exa mple.test",  # 域名含内部空格
]


class EmailValidationTestCase(unittest.TestCase):
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

    def update_email(self, db_path, contact_id, email):
        return self.run_crm(
            db_path, "update-email", "--id", str(contact_id), "--email", email
        )

    def list_company(self, db_path, company):
        return self.run_crm(db_path, "list", "--company", company)

    def assert_contact_success(self, result, expected):
        """断言命令成功：退出码 0、标准错误为空、标准输出为单个联系人 JSON 对象。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertIsInstance(record["id"], int)
        self.assertEqual(record, {**expected, "id": record["id"]})
        return record

    def assert_email_rejected(self, result):
        """断言邮箱被拒绝：退出码 2、标准输出为空、标准错误恰为单行邮箱错误。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), EMAIL_ERROR_LINE + "\n"
        )

    def assert_list_success(self, db_path, company, expected_records):
        """断言 list 返回的记录（含顺序）与期望完全一致。"""
        result = self.list_company(db_path, company)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def seed_company_contacts(self, db_path):
        """在指定数据库中新增固定样例：星河科技 林宁/许禾、远帆咨询 周岚。"""
        lin = self.assert_contact_success(
            self.add_contact(db_path, "林宁", "lin.ning@example.test", "星河科技"),
            {"name": "林宁", "email": "lin.ning@example.test", "company": "星河科技"},
        )
        xu = self.assert_contact_success(
            self.add_contact(db_path, "许禾", "xu.he@example.test", "星河科技"),
            {"name": "许禾", "email": "xu.he@example.test", "company": "星河科技"},
        )
        zhou = self.assert_contact_success(
            self.add_contact(db_path, "周岚", "zhou.lan@example.test", "远帆咨询"),
            {"name": "周岚", "email": "zhou.lan@example.test", "company": "远帆咨询"},
        )
        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])
        return lin, xu, zhou

    # ---- 有效邮箱：清理首尾空白、保留内部字符 ----

    def test_add_trims_surrounding_whitespace_and_preserves_inner_characters(self):
        for index, (raw_email, cleaned_email) in enumerate(ACCEPTED_EMAIL_CASES):
            # 每个样例使用独立数据库，互不构成前提
            db_path = self.tmpdir / f"add-accept-{index}.sqlite3"
            with self.subTest(raw_email=raw_email):
                result = self.add_contact(db_path, "林宁", raw_email, "星河科技")
                record = self.assert_contact_success(
                    result,
                    {"name": "林宁", "email": cleaned_email, "company": "星河科技"},
                )
                # 大小写、加号与用户名内部的点原样保留
                self.assertEqual(record["email"], cleaned_email)

                # 后续独立 list 查询读到同一邮箱
                self.assert_list_success(db_path, "星河科技", [record])

    def test_update_email_trims_whitespace_and_preserves_other_records(self):
        for index, (raw_email, cleaned_email) in enumerate(ACCEPTED_EMAIL_CASES):
            # 每个样例独立准备数据，互不构成前提
            db_path = self.tmpdir / f"update-accept-{index}.sqlite3"
            lin, xu, zhou = self.seed_company_contacts(db_path)
            with self.subTest(raw_email=raw_email):
                result = self.update_email(db_path, lin["id"], raw_email)
                updated_lin = self.assert_contact_success(
                    result, {**lin, "email": cleaned_email}
                )
                # 编号、姓名、公司保持原值，仅邮箱更新为清理后的新值
                self.assertEqual(updated_lin["id"], lin["id"])
                self.assertEqual(updated_lin["name"], lin["name"])
                self.assertEqual(updated_lin["company"], lin["company"])
                self.assertEqual(updated_lin["email"], cleaned_email)

                # 重新 list：林宁读到清理后的新邮箱，许禾与周岚全部字段不变
                records = self.assert_list_success(
                    db_path, "星河科技", [updated_lin, xu]
                )
                self.assertEqual(
                    [r["id"] for r in records], sorted(r["id"] for r in records)
                )
                self.assert_list_success(db_path, "远帆咨询", [zhou])

    # ---- 无效邮箱：统一拒绝且不影响已有数据 ----

    def test_add_rejects_invalid_emails_and_keeps_existing_records(self):
        lin, xu, zhou = self.seed_company_contacts(self.db_path)

        for raw_email in REJECTED_EMAILS:
            with self.subTest(raw_email=raw_email):
                result = self.add_contact(
                    self.db_path, "新联系人", raw_email, "星河科技"
                )
                self.assert_email_rejected(result)

                # 两家公司的记录内容、数量与编号顺序保持原样
                records = self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assertEqual([r["id"] for r in records], [lin["id"], xu["id"]])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_email_rejects_invalid_emails_and_keeps_existing_records(self):
        lin, xu, zhou = self.seed_company_contacts(self.db_path)

        for raw_email in REJECTED_EMAILS:
            with self.subTest(raw_email=raw_email):
                result = self.update_email(self.db_path, lin["id"], raw_email)
                self.assert_email_rejected(result)

                # 两家公司的记录内容、数量与编号顺序保持原样
                records = self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assertEqual([r["id"] for r in records], [lin["id"], xu["id"]])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    # ---- 无效邮箱：不会创建尚不存在的数据库 ----

    def test_add_rejected_email_does_not_create_missing_database(self):
        for index, raw_email in enumerate(REJECTED_EMAILS):
            fresh_db = self.tmpdir / f"add-reject-{index}.sqlite3"
            with self.subTest(raw_email=raw_email):
                self.assertFalse(fresh_db.exists())
                result = self.add_contact(fresh_db, "林宁", raw_email, "星河科技")
                self.assert_email_rejected(result)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_update_email_rejected_email_does_not_create_missing_database(self):
        for index, raw_email in enumerate(REJECTED_EMAILS):
            fresh_db = self.tmpdir / f"update-reject-{index}.sqlite3"
            with self.subTest(raw_email=raw_email):
                self.assertFalse(fresh_db.exists())
                result = self.update_email(fresh_db, "1", raw_email)
                self.assert_email_rejected(result)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])


if __name__ == "__main__":
    unittest.main()
