"""crm.py list 子命令 --email 精确筛选及与 --name 联用的回归测试。

固定样例为两家公司四位联系人：
- 星河科技：林宁、林禾（邮箱均为 Lin@example.test）、许禾（xu@example.test）
- 远帆咨询：周岚（同为 Lin@example.test，用于核对公司条件隔离）

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

# 空串、纯空白或缺少 @ 的邮箱都应在校验阶段被拒绝
INVALID_LIST_EMAILS = ["", "   ", "\t\t", " \t ", "noatsign.example.test"]


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

    def list_contacts(self, db_path, company, email=None, name=None):
        cli_args = ["list", "--company", company]
        if email is not None:
            cli_args.extend(["--email", email])
        if name is not None:
            cli_args.extend(["--name", name])
        return self.run_crm(db_path, *cli_args)

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

    def assert_list_rejected(self, result, expected_stderr_line):
        """断言 list 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )

    def assert_list_success(self, db_path, company, expected_records, email=None,
                            name=None):
        """断言 list 返回的记录（含顺序）与期望完全一致，并返回解析结果。"""
        result = self.list_contacts(db_path, company, email=email, name=name)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        # 标准输出整体可解析为单个 JSON 数组（无多余输出）
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertEqual(records, expected_records)
        return records

    def seed_contacts(self):
        """按验收顺序新增两位 Lin@example.test 联系人等四位联系人。

        星河科技依次新增林宁、林禾、许禾；远帆咨询新增周岚。
        林宁、林禾、周岚邮箱相同，用于区分公司与姓名条件的作用。
        """
        lin_ning = self.assert_add_success(
            self.add_contact(self.db_path, "林宁", "Lin@example.test", "星河科技"),
            {"name": "林宁", "email": "Lin@example.test", "company": "星河科技"},
        )
        lin_he = self.assert_add_success(
            self.add_contact(self.db_path, "林禾", "Lin@example.test", "星河科技"),
            {"name": "林禾", "email": "Lin@example.test", "company": "星河科技"},
        )
        xu_he = self.assert_add_success(
            self.add_contact(self.db_path, "许禾", "xu@example.test", "星河科技"),
            {"name": "许禾", "email": "xu@example.test", "company": "星河科技"},
        )
        zhou_lan = self.assert_add_success(
            self.add_contact(self.db_path, "周岚", "Lin@example.test", "远帆咨询"),
            {"name": "周岚", "email": "Lin@example.test", "company": "远帆咨询"},
        )

        ids = [r["id"] for r in (lin_ning, lin_he, xu_he, zhou_lan)]
        self.assertEqual(ids, sorted(ids))
        return lin_ning, lin_he, xu_he, zhou_lan

    # ---- 成功筛选行为 ----

    def test_list_email_filters_exactly_within_company_sorted_by_id(self):
        lin_ning, lin_he, xu_he, zhou_lan = self.seed_contacts()

        # 只返回星河科技中邮箱完全相同的林宁和林禾，按编号升序；
        # 许禾邮箱不同、远帆咨询的周岚邮箱相同但公司不同，均不返回
        records = self.assert_list_success(
            self.db_path, "星河科技", [lin_ning, lin_he], email="Lin@example.test"
        )
        self.assertEqual([r["id"] for r in records], [lin_ning["id"], lin_he["id"]])

        # 每条记录仅含四个字段，字段值与新增输出逐字一致
        for record, added in zip(records, (lin_ning, lin_he)):
            self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
            self.assertEqual(record, added)

        # 远帆咨询下同一邮箱只返回周岚
        self.assert_list_success(
            self.db_path, "远帆咨询", [zhou_lan], email="Lin@example.test"
        )

        # 许禾的邮箱只命中许禾本人
        self.assert_list_success(
            self.db_path, "星河科技", [xu_he], email="xu@example.test"
        )

    def test_list_email_and_name_combined(self):
        lin_ning, lin_he, _xu_he, _zhou_lan = self.seed_contacts()

        # 邮箱相同的两人中，--name 宁 只命中林宁
        records = self.assert_list_success(
            self.db_path,
            "星河科技",
            [lin_ning],
            email="Lin@example.test",
            name="宁",
        )
        self.assertEqual(records, [lin_ning])

        # --name 禾 命中邮箱相同的林禾（许禾邮箱不同，被邮箱条件排除）
        self.assert_list_success(
            self.db_path,
            "星河科技",
            [lin_he],
            email="Lin@example.test",
            name="禾",
        )

        # --name 许 在邮箱精确条件下无命中：许禾的邮箱不是 Lin@example.test
        self.assert_list_success(
            self.db_path,
            "星河科技",
            [],
            email="Lin@example.test",
            name="许",
        )

    def test_list_without_email_returns_all_company_records(self):
        lin_ning, lin_he, xu_he, zhou_lan = self.seed_contacts()

        # 省略 --email 返回星河科技三人，按编号升序
        records = self.assert_list_success(
            self.db_path, "星河科技", [lin_ning, lin_he, xu_he]
        )
        self.assertEqual(
            [r["id"] for r in records],
            [lin_ning["id"], lin_he["id"], xu_he["id"]],
        )
        # 远帆咨询仍只有周岚
        self.assert_list_success(self.db_path, "远帆咨询", [zhou_lan])

    def test_list_email_is_case_sensitive_exact_match(self):
        self.seed_contacts()

        # 大小写不同的邮箱不命中；相似但不完整的地址同样不命中
        for email in ("lin@example.test", "LIN@EXAMPLE.TEST", "Lin@example.tes"):
            with self.subTest(email=email):
                self.assert_list_success(
                    self.db_path, "星河科技", [], email=email
                )

    def test_list_company_and_email_ignore_surrounding_whitespace(self):
        lin_ning, lin_he, _xu_he, _zhou_lan = self.seed_contacts()

        for padded_company in ("  星河科技", "星河科技  ", "\t星河科技\t", " \t星河科技 \t"):
            for padded_email in (
                "  Lin@example.test",
                "Lin@example.test  ",
                "\tLin@example.test\t",
                " \tLin@example.test \t",
            ):
                with self.subTest(company=padded_company, email=padded_email):
                    self.assert_list_success(
                        self.db_path,
                        padded_company,
                        [lin_ning, lin_he],
                        email=padded_email,
                    )

        # 公司与邮箱都带空白、同时再传 --name 宁 时仍只返回林宁
        self.assert_list_success(
            self.db_path,
            "  星河科技  ",
            [lin_ning],
            email="  Lin@example.test  ",
            name="  宁  ",
        )

    def test_list_email_success_output_is_single_json_array(self):
        self.seed_contacts()

        result = self.list_contacts(
            self.db_path, "星河科技", email="Lin@example.test"
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")

        # 标准输出去除首尾空白后整体仍是单个 JSON 数组
        payload = result.stdout.decode("utf-8")
        records = json.loads(payload)
        self.assertIsInstance(records, list)
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})

    def test_list_valid_conditions_create_missing_database_and_return_empty(self):
        fresh_db = self.tmpdir / "fresh-list.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 父目录已存在、条件全部合法：创建空库并返回空数组
        result = self.list_contacts(
            fresh_db, "星河科技", email="Lin@example.test", name="宁"
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), [])
        self.assertTrue(fresh_db.exists())

        # 再次用公开命令查询仍为空数组，不产生联系人
        again = self.list_contacts(
            fresh_db, "星河科技", email="Lin@example.test"
        )
        self.assertEqual(again.returncode, 0, again.stderr.decode("utf-8"))
        self.assertEqual(again.stderr, b"")
        self.assertEqual(json.loads(again.stdout.decode("utf-8")), [])

    # ---- 输入拒绝行为 ----

    def test_list_invalid_email_is_rejected(self):
        self.seed_contacts()

        for email in INVALID_LIST_EMAILS:
            with self.subTest(email=email):
                result = self.list_contacts(self.db_path, "星河科技", email=email)
                self.assert_list_rejected(result, EMAIL_ERROR_LINE)

    def test_list_empty_company_reports_company_error_even_with_invalid_email(self):
        self.seed_contacts()

        for company in ("", "   ", "\t\t", " \t "):
            for email in ("", "   ", "noatsign.example.test"):
                with self.subTest(company=company, email=email):
                    result = self.list_contacts(self.db_path, company, email=email)
                    self.assert_list_rejected(result, COMPANY_ERROR_LINE)

    def test_list_empty_name_reports_name_error_even_with_invalid_email(self):
        self.seed_contacts()

        # 公司合法、姓名为空：只报告姓名错误，即使邮箱也无效
        for name in ("", "   ", "\t\t", " \t "):
            for email in ("", "   ", "noatsign.example.test"):
                with self.subTest(name=name, email=email):
                    result = self.list_contacts(
                        self.db_path,
                        "星河科技",
                        email=email,
                        name=name,
                    )
                    self.assert_list_rejected(result, NAME_ERROR_LINE)

    # ---- 查询对数据的影响 ----

    def test_list_queries_leave_existing_records_unchanged(self):
        lin_ning, lin_he, xu_he, zhou_lan = self.seed_contacts()

        # 成功查询（命中与未命中）后记录内容和数量不变
        successful_queries = [
            ("星河科技", "Lin@example.test", None),
            ("星河科技", "Lin@example.test", "宁"),
            ("星河科技", "Lin@example.test", "许"),
            ("星河科技", "lin@example.test", None),
            ("远帆咨询", "Lin@example.test", None),
        ]
        for company, email, name in successful_queries:
            with self.subTest(company=company, email=email, name=name):
                self.list_contacts(self.db_path, company, email=email, name=name)
                self.assert_list_success(
                    self.db_path, "星河科技", [lin_ning, lin_he, xu_he]
                )
                self.assert_list_success(self.db_path, "远帆咨询", [zhou_lan])

        # 被拒绝的查询（邮箱无效、公司为空、姓名为空）后同样不变
        rejected_queries = [
            ("星河科技", "", None),
            ("星河科技", "noatsign.example.test", None),
            ("星河科技", "Lin@example.test", "   "),
            ("   ", "noatsign.example.test", None),
        ]
        for company, email, name in rejected_queries:
            with self.subTest(company=company, email=email, name=name):
                result = self.list_contacts(
                    self.db_path, company, email=email, name=name
                )
                self.assertEqual(result.returncode, 2)
                self.assert_list_success(
                    self.db_path, "星河科技", [lin_ning, lin_he, xu_he]
                )
                self.assert_list_success(self.db_path, "远帆咨询", [zhou_lan])

    def test_list_invalid_email_does_not_create_missing_database(self):
        for index, email in enumerate(INVALID_LIST_EMAILS):
            fresh_db = self.tmpdir / f"list-email-fresh-{index}.sqlite3"
            with self.subTest(email=email):
                self.assertFalse(fresh_db.exists())
                result = self.list_contacts(fresh_db, "星河科技", email=email)
                self.assert_list_rejected(result, EMAIL_ERROR_LINE)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])


if __name__ == "__main__":
    unittest.main()
