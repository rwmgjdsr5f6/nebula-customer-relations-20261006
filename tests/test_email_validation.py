"""crm.py add 与 update-email 邮箱校验规则的命令行回归测试。

围绕两个入口共用的轻量邮箱规则补齐回归：首尾空白在保存前清理，
清理后须恰好含一个 @、用户名与域名均非空、域名至少含一个点且
点分出的各段均非空、地址内部不含空白。

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

# 邮箱拒绝样例：空用户名、空域名、域名首/尾/中间空段、多个 @、
# 域名无点、空字符串，以及内部含空格或制表符的地址。
# 首尾空白会在清理时被去掉，因此这里的空白字符都位于地址内部。
INVALID_EMAILS = [
    "@example.test",
    "a@",
    "a@.example.test",
    "a@example.test.",
    "a@example..test",
    "a@@example.test",
    "a@exampletest",
    "",
    "a b@example.test",
    "a@exa mple.test",
    "a\tb@example.test",
]

# (输入值, 清理后应保存的值)：首尾空白去掉，大小写、加号等内部字符保留
PADDED_TAGGED_EMAIL = ("  User+tag@sub.Example.test  ", "User+tag@sub.Example.test")
# 用户名中的连续点号按现有规则允许
LOCAL_CONSECUTIVE_DOTS_EMAIL = "a..b@example.test"


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

    def assert_email_rejected(self, result):
        """断言邮箱被拒：退出码 2、标准输出为空、标准错误恰为单行邮箱错误。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr.decode("utf-8"), EMAIL_ERROR_LINE + "\n")

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

    def seed_contacts(self):
        """在新数据库中新增固定样例：星河科技林宁/许禾、远帆咨询周岚。

        三人各自使用不同的有效邮箱，编号严格递增，返回各自的新增结果。
        """
        lin = self.assert_single_contact_object(
            self.add_contact(self.db_path, "林宁", "linning@example.test", "星河科技")
        )
        self.assertEqual(
            lin,
            {
                "id": lin["id"],
                "name": "林宁",
                "email": "linning@example.test",
                "company": "星河科技",
            },
        )

        xu = self.assert_single_contact_object(
            self.add_contact(self.db_path, "许禾", "xuhe@example.test", "星河科技")
        )
        self.assertEqual(
            xu,
            {
                "id": xu["id"],
                "name": "许禾",
                "email": "xuhe@example.test",
                "company": "星河科技",
            },
        )

        zhou = self.assert_single_contact_object(
            self.add_contact(self.db_path, "周岚", "zhoulan@example.test", "远帆咨询")
        )
        self.assertEqual(
            zhou,
            {
                "id": zhou["id"],
                "name": "周岚",
                "email": "zhoulan@example.test",
                "company": "远帆咨询",
            },
        )

        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])
        return lin, xu, zhou

    # ---- add 成功场景 ----

    def test_add_accepts_padded_tagged_email_and_persists_cleaned_value(self):
        padded, cleaned = PADDED_TAGGED_EMAIL

        result = self.add_contact(self.db_path, "林宁", padded, "星河科技")
        record = self.assert_single_contact_object(result)
        # 保存值去掉首尾空白，保留大小写、加号及其他内部字符
        self.assertEqual(record["name"], "林宁")
        self.assertEqual(record["email"], cleaned)
        self.assertEqual(record["company"], "星河科技")

        # 重新发起 list 查询仍读到清理后的同一邮箱
        self.assert_list_success(self.db_path, "星河科技", [record])

    def test_add_accepts_consecutive_dots_in_local_part(self):
        email = LOCAL_CONSECUTIVE_DOTS_EMAIL

        result = self.add_contact(self.db_path, "许禾", email, "星河科技")
        record = self.assert_single_contact_object(result)
        self.assertEqual(record["name"], "许禾")
        self.assertEqual(record["email"], email)
        self.assertEqual(record["company"], "星河科技")

        # 成功新增的联系人在后续查询中保留相同邮箱
        self.assert_list_success(self.db_path, "星河科技", [record])

    # ---- update-email 成功场景（数据独立准备）----

    def test_update_email_accepts_padded_tagged_email_and_persists_cleaned_value(self):
        lin, xu, zhou = self.seed_contacts()
        padded, cleaned = PADDED_TAGGED_EMAIL

        result = self.update_email(self.db_path, lin["id"], padded)
        updated_lin = self.assert_single_contact_object(result)
        # 邮箱替换为清理后的值，编号、姓名、公司保持原值
        self.assertEqual(updated_lin, {**lin, "email": cleaned})

        # 重新发起 list 查询读到清理后的新邮箱；另两位联系人全部字段不变，
        # 两家公司的记录数量与编号升序顺序保持原样
        records = self.assert_list_success(
            self.db_path, "星河科技", [updated_lin, xu]
        )
        self.assertEqual([r["id"] for r in records], [lin["id"], xu["id"]])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_email_accepts_consecutive_dots_in_local_part(self):
        lin, xu, zhou = self.seed_contacts()
        email = LOCAL_CONSECUTIVE_DOTS_EMAIL

        result = self.update_email(self.db_path, lin["id"], email)
        updated_lin = self.assert_single_contact_object(result)
        self.assertEqual(updated_lin, {**lin, "email": email})

        records = self.assert_list_success(
            self.db_path, "星河科技", [updated_lin, xu]
        )
        self.assertEqual([r["id"] for r in records], [lin["id"], xu["id"]])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    # ---- add 拒绝场景：已存在的数据库 ----

    def test_add_rejects_invalid_emails_and_leaves_records_unchanged(self):
        lin, xu, zhou = self.seed_contacts()

        for email in INVALID_EMAILS:
            with self.subTest(email=email):
                # 姓名与公司均合法，失败只能归因于邮箱
                result = self.add_contact(self.db_path, "样本联系人", email, "星河科技")
                self.assert_email_rejected(result)

                # 两家公司的记录内容、数量和编号顺序都保持原样
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    # ---- update-email 拒绝场景：已存在的数据库（数据独立准备）----

    def test_update_email_rejects_invalid_emails_and_leaves_records_unchanged(self):
        lin, xu, zhou = self.seed_contacts()

        for email in INVALID_EMAILS:
            with self.subTest(email=email):
                # 编号合法且联系人存在，失败只能归因于邮箱
                result = self.update_email(self.db_path, lin["id"], email)
                self.assert_email_rejected(result)

                # 林宁本人及另两位联系人的全部字段、数量、编号顺序均不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    # ---- add 拒绝场景：数据库尚不存在（父目录已存在）----

    def test_add_rejected_email_does_not_create_missing_database(self):
        for index, email in enumerate(INVALID_EMAILS):
            fresh_db = self.tmpdir / f"add-fresh-{index}.sqlite3"
            with self.subTest(email=email):
                self.assertFalse(fresh_db.exists())
                result = self.add_contact(fresh_db, "样本联系人", email, "星河科技")
                self.assert_email_rejected(result)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    # ---- update-email 拒绝场景：数据库尚不存在（父目录已存在）----

    def test_update_email_rejected_email_does_not_create_missing_database(self):
        for index, email in enumerate(INVALID_EMAILS):
            fresh_db = self.tmpdir / f"update-fresh-{index}.sqlite3"
            with self.subTest(email=email):
                self.assertFalse(fresh_db.exists())
                # 编号合法，邮箱在连接数据库之前即被拒绝
                result = self.update_email(fresh_db, 1, email)
                self.assert_email_rejected(result)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])


if __name__ == "__main__":
    unittest.main()
