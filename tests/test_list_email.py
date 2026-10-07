"""crm.py list 子命令 --email 精确筛选及与 --name 联用的回归测试。

固定样例为两家公司四位联系人：星河科技按顺序新增林宁、林禾、许禾，
前两人邮箱均为 Lin@example.test，许禾为 xu@example.test；远帆咨询
的周岚也使用 Lin@example.test。覆盖：

- --email 在公司范围内做区分大小写的精确匹配，结果按编号升序；
- --email 与 --name 同时给出时两个条件同时生效；
- 公司与邮箱首尾空白在清理后仍命中，邮箱大小写不同则不命中；
- 成功输出整体为单个 JSON 数组，每条记录只含 id/name/email/company；
- 邮箱、公司、姓名输入错误的退出码、标准输出/错误文案与短路顺序；
- 成功与拒绝查询都不改变已有记录；邮箱校验失败不创建新数据库；
- 有效条件查询父目录已存在的新数据库时创建空库并返回 []。

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
COMPANY_ERROR_LINE = "company: must not be empty"
NAME_ERROR_LINE = "name: must not be empty"

SHARED_EMAIL = "Lin@example.test"

# list 拒绝的邮箱样例：空串、纯空白（清理后为空）、缺少 @
INVALID_EMAILS = ["", "   ", "\t \t", "noatsign.example.test"]


class ListEmailFilterTestCase(unittest.TestCase):
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

    def list_company_email(self, db_path, company, email):
        return self.run_crm(
            db_path, "list", "--company", company, "--email", email
        )

    def list_company_name_email(self, db_path, company, name, email):
        return self.run_crm(
            db_path,
            "list",
            "--company",
            company,
            "--name",
            name,
            "--email",
            email,
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
        """断言不带可选条件的 list 返回的记录（含顺序）与期望完全一致。"""
        result = self.run_crm(db_path, "list", "--company", company)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def assert_list_rejected(self, result, expected_stderr_line):
        """断言 list 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )

    def seed_email_filter_contacts(self):
        """两家公司四位联系人：星河科技林宁/林禾/许禾，远帆咨询周岚。

        林宁、林禾与周岚的邮箱均为 Lin@example.test，许禾为
        xu@example.test；编号严格递增，返回四人各自的新增结果。
        """
        lin_ning = self.assert_add_success(
            self.add_contact(self.db_path, "林宁", SHARED_EMAIL, "星河科技"),
            {"name": "林宁", "email": SHARED_EMAIL, "company": "星河科技"},
        )
        lin_he = self.assert_add_success(
            self.add_contact(self.db_path, "林禾", SHARED_EMAIL, "星河科技"),
            {"name": "林禾", "email": SHARED_EMAIL, "company": "星河科技"},
        )
        xu_he = self.assert_add_success(
            self.add_contact(self.db_path, "许禾", "xu@example.test", "星河科技"),
            {"name": "许禾", "email": "xu@example.test", "company": "星河科技"},
        )
        zhou_lan = self.assert_add_success(
            self.add_contact(self.db_path, "周岚", SHARED_EMAIL, "远帆咨询"),
            {"name": "周岚", "email": SHARED_EMAIL, "company": "远帆咨询"},
        )

        ids = [r["id"] for r in (lin_ning, lin_he, xu_he, zhou_lan)]
        self.assertEqual(ids, sorted(ids))
        return lin_ning, lin_he, xu_he, zhou_lan

    def assert_email_query(self, db_path, company, email, expected_records):
        """执行带 --email 的 list 并断言退出码、标准错误与结果（含顺序）。"""
        result = self.list_company_email(db_path, company, email)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    # ---- 邮箱精确筛选与姓名联用 ----

    def test_list_email_matches_exactly_within_company_sorted_by_id(self):
        lin_ning, lin_he, xu_he, zhou_lan = self.seed_email_filter_contacts()

        # 只返回星河科技中邮箱完全相等的林宁、林禾，按编号升序；
        # 许禾邮箱不同、周岚虽同邮箱但属远帆咨询，均不出现
        records = self.assert_email_query(
            self.db_path, "星河科技", SHARED_EMAIL, [lin_ning, lin_he]
        )
        self.assertEqual(
            [r["id"] for r in records], [lin_ning["id"], lin_he["id"]]
        )
        self.assertEqual([r["id"] for r in records], sorted(r["id"] for r in records))

        # 远帆咨询的同邮箱查询只命中周岚
        self.assert_email_query(self.db_path, "远帆咨询", SHARED_EMAIL, [zhou_lan])

        # 许禾的邮箱只能查到许禾本人
        self.assert_email_query(
            self.db_path, "星河科技", "xu@example.test", [xu_he]
        )

    def test_list_email_and_name_both_apply(self):
        lin_ning, _lin_he, _xu_he, _zhou_lan = self.seed_email_filter_contacts()

        # 同一邮箱下再用姓名子串收窄：--name 宁 只返回林宁
        result = self.list_company_name_email(
            self.db_path, "星河科技", "宁", SHARED_EMAIL
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), [lin_ning])

        # --name 许 与同邮箱条件联用：许禾邮箱不同，结果为空数组
        result = self.list_company_name_email(
            self.db_path, "星河科技", "许", SHARED_EMAIL
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), [])

    def test_list_without_email_returns_all_company_records(self):
        lin_ning, lin_he, xu_he, zhou_lan = self.seed_email_filter_contacts()

        # 省略 --email 时返回星河科技全部三人，按编号升序
        records = self.assert_list_success(
            self.db_path, "星河科技", [lin_ning, lin_he, xu_he]
        )
        self.assertEqual([r["id"] for r in records], sorted(r["id"] for r in records))
        self.assert_list_success(self.db_path, "远帆咨询", [zhou_lan])

    def test_list_email_trims_surrounding_whitespace_in_company_and_email(self):
        lin_ning, lin_he, _xu_he, _zhou_lan = self.seed_email_filter_contacts()

        for padded_company in ("  星河科技", "星河科技  ", "\t星河科技\t"):
            for padded_email in (
                "  Lin@example.test",
                "Lin@example.test  ",
                "\tLin@example.test\t",
            ):
                with self.subTest(company=padded_company, email=padded_email):
                    self.assert_email_query(
                        self.db_path,
                        padded_company,
                        padded_email,
                        [lin_ning, lin_he],
                    )

    def test_list_email_is_case_sensitive_exact_match(self):
        self.seed_email_filter_contacts()

        # 邮箱按精确相等匹配且区分大小写：小写形式不命中任何记录
        self.assert_email_query(self.db_path, "星河科技", "lin@example.test", [])
        self.assert_email_query(self.db_path, "远帆咨询", "lin@example.test", [])

        # 其他有效但未录入的邮箱同样返回空数组
        self.assert_email_query(self.db_path, "星河科技", "nobody@example.test", [])

    def test_list_email_success_output_is_single_json_array_with_exact_fields(self):
        lin_ning, lin_he, _xu_he, _zhou_lan = self.seed_email_filter_contacts()

        result = self.list_company_email(self.db_path, "星河科技", SHARED_EMAIL)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        # 标准输出整体可解析为单个 JSON 数组（无多余输出）
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertEqual(len(records), 2)
        # 每条记录只含 id、name、email、company，字段值与新增输出一致
        for record, added in zip(records, (lin_ning, lin_he)):
            self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
            self.assertEqual(record, added)

    # ---- 输入错误：退出码、输出与短路顺序 ----

    def test_list_invalid_email_is_rejected(self):
        self.seed_email_filter_contacts()

        for email in INVALID_EMAILS:
            with self.subTest(email=email):
                result = self.list_company_email(self.db_path, "星河科技", email)
                self.assert_list_rejected(result, EMAIL_ERROR_LINE)

    def test_list_empty_company_reports_company_error_only(self):
        self.seed_email_filter_contacts()

        # 公司为空时只报告 company 错误，即使姓名与邮箱也都无效
        for company, name, email in (
            ("", "   ", "noatsign.example.test"),
            ("   ", "", ""),
            ("\t\t", " \t ", "   "),
        ):
            with self.subTest(company=company, name=name, email=email):
                result = self.list_company_name_email(
                    self.db_path, company, name, email
                )
                self.assert_list_rejected(result, COMPANY_ERROR_LINE)

    def test_list_empty_name_reports_name_error_even_when_email_invalid(self):
        self.seed_email_filter_contacts()

        # 公司有效而姓名为空时只报告 name 错误，即使邮箱也无效
        for name, email in (
            ("", "noatsign.example.test"),
            ("   ", ""),
            (" \t ", "   "),
        ):
            with self.subTest(name=name, email=email):
                result = self.list_company_name_email(
                    self.db_path, "星河科技", name, email
                )
                self.assert_list_rejected(result, NAME_ERROR_LINE)

    # ---- 查询对数据的影响 ----

    def test_list_successful_and_rejected_queries_leave_records_unchanged(self):
        lin_ning, lin_he, xu_he, zhou_lan = self.seed_email_filter_contacts()

        accepted_queries = [
            ("星河科技", SHARED_EMAIL),
            ("星河科技", "xu@example.test"),
            ("星河科技", "nobody@example.test"),
            ("远帆咨询", SHARED_EMAIL),
        ]
        for company, email in accepted_queries:
            result = self.list_company_email(self.db_path, company, email)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))

        for email in INVALID_EMAILS:
            result = self.list_company_email(self.db_path, "星河科技", email)
            self.assert_list_rejected(result, EMAIL_ERROR_LINE)

        # 成功与拒绝查询后，两家公司的记录内容和数量都不变
        self.assert_list_success(
            self.db_path, "星河科技", [lin_ning, lin_he, xu_he]
        )
        self.assert_list_success(self.db_path, "远帆咨询", [zhou_lan])

    def test_list_invalid_email_does_not_create_missing_database(self):
        for index, email in enumerate(INVALID_EMAILS):
            fresh_db = self.tmpdir / f"list-email-fresh-{index}.sqlite3"
            with self.subTest(email=email):
                self.assertFalse(fresh_db.exists())
                result = self.list_company_email(fresh_db, "星河科技", email)
                self.assert_list_rejected(result, EMAIL_ERROR_LINE)
                # 邮箱校验失败发生在连接数据库之前，文件不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_list_valid_conditions_create_missing_database_and_return_empty(self):
        fresh_db = self.tmpdir / "list-email-empty.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 父目录已存在、条件全部有效：创建空库并返回空数组
        result = self.list_company_email(fresh_db, "星河科技", SHARED_EMAIL)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), [])
        self.assertTrue(fresh_db.exists())

        # 姓名与邮箱条件联用的有效查询同样创建空库并返回空数组
        named_db = self.tmpdir / "list-email-name-empty.sqlite3"
        self.assertFalse(named_db.exists())
        named_result = self.list_company_name_email(
            named_db, "星河科技", "宁", SHARED_EMAIL
        )
        self.assertEqual(named_result.returncode, 0, named_result.stderr.decode("utf-8"))
        self.assertEqual(named_result.stderr, b"")
        self.assertEqual(json.loads(named_result.stdout.decode("utf-8")), [])
        self.assertTrue(named_db.exists())


if __name__ == "__main__":
    unittest.main()
