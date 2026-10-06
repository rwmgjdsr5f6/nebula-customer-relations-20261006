"""crm.py 命令行行为的回归测试。

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

# (add 子命令参数, 期望的标准错误)
INVALID_ADD_CASES = [
    (
        ["add", "--name", "   ", "--email", "ok@example.test", "--company", "有效公司"],
        "name: must not be empty",
    ),
    (
        ["add", "--name", "有效姓名", "--email", "ok@example.test", "--company", " \t "],
        "company: must not be empty",
    ),
    # 缺少 @
    (
        ["add", "--name", "有效姓名", "--email", "noatsign.example.test", "--company", "有效公司"],
        "email: invalid email address",
    ),
    # 包含两个 @
    (
        ["add", "--name", "有效姓名", "--email", "a@@example.test", "--company", "有效公司"],
        "email: invalid email address",
    ),
    # 域名没有点
    (
        ["add", "--name", "有效姓名", "--email", "a@exampletest", "--company", "有效公司"],
        "email: invalid email address",
    ),
    # 域名含空段
    (
        ["add", "--name", "有效姓名", "--email", "a@example..test", "--company", "有效公司"],
        "email: invalid email address",
    ),
    # 邮箱内部含空白
    (
        ["add", "--name", "有效姓名", "--email", "a b@example.test", "--company", "有效公司"],
        "email: invalid email address",
    ),
]

# (update-email 子命令的 --id 与 --email 参数, 期望的标准错误)
INVALID_UPDATE_EMAIL_CASES = [
    # 编号为空白
    (("   ", "ok@example.test"), "id: must be a positive integer"),
    # 编号为 0
    (("0", "ok@example.test"), "id: must be a positive integer"),
    # 编号为负数
    (("-1", "ok@example.test"), "id: must be a positive integer"),
    # 编号为小数
    (("1.5", "ok@example.test"), "id: must be a positive integer"),
    # 编号超出 64 位有符号整数上限
    (("9223372036854775808", "ok@example.test"), "id: must be a positive integer"),
    # 邮箱缺少 @
    (("1", "noatsign.example.test"), "email: invalid email address"),
    # 邮箱含内部空白
    (("1", "a b@example.test"), "email: invalid email address"),
    # 编号与邮箱同时无效时只报告编号错误
    (("1.5", "noatsign.example.test"), "id: must be a positive integer"),
]


class CRMTestCase(unittest.TestCase):
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

    def seed_sample_contacts(self):
        """在同一个新数据库中依次新增三名联系人，返回各自的新增结果。"""
        result_lin = self.add_contact(
            self.db_path,
            "  林宁  ",
            "  Lin.Ning@example.test  ",
            "  星河科技  ",
        )
        lin = self.assert_add_success(
            result_lin,
            {"name": "林宁", "email": "Lin.Ning@example.test", "company": "星河科技"},
        )

        result_xu = self.add_contact(
            self.db_path, "许禾", "xuhe@example.test", "星河科技"
        )
        xu = self.assert_add_success(
            result_xu,
            {"name": "许禾", "email": "xuhe@example.test", "company": "星河科技"},
        )

        result_zhou = self.add_contact(
            self.db_path, "周岚", "zhoulan@example.test", "远帆咨询"
        )
        zhou = self.assert_add_success(
            result_zhou,
            {"name": "周岚", "email": "zhoulan@example.test", "company": "远帆咨询"},
        )

        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])
        return lin, xu, zhou

    def test_valid_adds_persist_and_list_filters_by_company(self):
        lin, xu, zhou = self.seed_sample_contacts()

        # 星河科技只能查到林宁和许禾，按 id 升序，字段与新增结果一致
        self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        # 远帆咨询只能查到周岚
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def assert_rejected(self, result, expected_stderr):
        """断言命令被拒绝：退出码 2、无标准输出、标准错误精确匹配。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr.decode("utf-8").strip(), expected_stderr)

    def test_invalid_inputs_on_existing_db_leave_records_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        for cli_args, expected_stderr in INVALID_ADD_CASES:
            with self.subTest(cli_args=cli_args):
                result = self.run_crm(self.db_path, *cli_args)
                self.assert_rejected(result, expected_stderr)

                # 拒绝后两家公司的记录内容和数量保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_invalid_inputs_do_not_create_missing_database(self):
        for index, (cli_args, expected_stderr) in enumerate(INVALID_ADD_CASES):
            fresh_db = self.tmpdir / f"fresh-{index}.sqlite3"
            with self.subTest(cli_args=cli_args):
                self.assertFalse(fresh_db.exists())
                result = self.run_crm(fresh_db, *cli_args)
                self.assert_rejected(result, expected_stderr)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_missing_parent_directory_is_rejected_without_being_created(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result = self.add_contact(
            fresh_db, "林宁", "Lin.Ning@example.test", "星河科技"
        )
        self.assert_rejected(result, "db: parent directory does not exist")
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    # ---- list 子命令的筛选行为回归测试 ----

    def assert_list_rejected(self, result, expected_stderr_line):
        """断言 list 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )

    def test_list_returns_seeded_records_sorted_by_id(self):
        lin, xu, zhou = self.seed_sample_contacts()

        # 星河科技只返回林宁和许禾，按 id 升序，字段与新增结果一致
        records = self.assert_list_success(self.db_path, "星河科技", [lin, xu])
        self.assertEqual([r["id"] for r in records], sorted(r["id"] for r in records))
        for record, added in zip(records, (lin, xu)):
            self.assertEqual(record, added)

        # 远帆咨询只返回周岚
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_list_ignores_surrounding_whitespace_in_company(self):
        lin, xu, _zhou = self.seed_sample_contacts()

        for padded in ("  星河科技", "星河科技  ", "\t星河科技\t", " \t星河科技 \t"):
            with self.subTest(company=padded):
                self.assert_list_success(self.db_path, padded, [lin, xu])

    def test_list_rejects_substring_and_internal_whitespace_matches(self):
        self.seed_sample_contacts()

        for company in ("星河", "星河 科技", "未录入公司"):
            with self.subTest(company=company):
                self.assert_list_success(self.db_path, company, [])

    def test_list_success_output_is_single_json_array(self):
        self.seed_sample_contacts()

        result = self.list_company(self.db_path, "星河科技")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        # 标准输出整体可解析为单个 JSON 数组（无多余输出）
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertEqual(len(records), 2)

    def test_list_creates_missing_database_and_returns_empty_array(self):
        self.assertFalse(self.db_path.exists())

        result = self.list_company(self.db_path, "星河科技")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), [])
        # 有效 list 会创建数据库文件
        self.assertTrue(self.db_path.exists())

        # 再次通过独立命令查询仍返回空数组，不产生联系人
        again = self.list_company(self.db_path, "星河科技")
        self.assertEqual(again.returncode, 0, again.stderr.decode("utf-8"))
        self.assertEqual(again.stderr, b"")
        self.assertEqual(json.loads(again.stdout.decode("utf-8")), [])

    def test_list_empty_or_blank_company_is_rejected(self):
        self.seed_sample_contacts()

        for company in ("", "   ", "\t\t", " \t "):
            with self.subTest(company=company):
                result = self.list_company(self.db_path, company)
                self.assert_list_rejected(result, "company: must not be empty")

    def test_list_invalid_company_does_not_create_missing_database(self):
        for index, company in enumerate(("", "   ", "\t\t", " \t ")):
            fresh_db = self.tmpdir / f"list-fresh-{index}.sqlite3"
            with self.subTest(company=company):
                self.assertFalse(fresh_db.exists())
                result = self.list_company(fresh_db, company)
                self.assert_list_rejected(result, "company: must not be empty")
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_list_invalid_company_leaves_existing_records_unchanged(self):
        lin, xu, zhou = self.seed_sample_contacts()

        for company in ("", "   ", "\t\t", " \t "):
            with self.subTest(company=company):
                result = self.list_company(self.db_path, company)
                self.assert_list_rejected(result, "company: must not be empty")

                # 拒绝后两家公司的记录内容和数量保持不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_list_missing_parent_directory_is_rejected_without_being_created(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result = self.list_company(fresh_db, "星河科技")
        self.assert_list_rejected(result, "db: parent directory does not exist")
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    def test_list_invalid_company_and_missing_parent_reports_company_error(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"

        result = self.list_company(fresh_db, "   ")
        self.assert_list_rejected(result, "company: must not be empty")
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())

    # ---- list --name 姓名子串筛选的回归测试 ----

    def seed_name_filter_contacts(self):
        """按固定顺序新增五名联系人，返回各自的新增结果字典。"""
        zhoulin = self.assert_add_success(
            self.add_contact(self.db_path, "周林", "c1@example.test", "星河科技"),
            {"name": "周林", "email": "c1@example.test", "company": "星河科技"},
        )
        linning = self.assert_add_success(
            self.add_contact(self.db_path, "林宁", "c2@example.test", "星河科技"),
            {"name": "林宁", "email": "c2@example.test", "company": "星河科技"},
        )
        lin_literal = self.assert_add_success(
            self.add_contact(self.db_path, "Lin_%", "c3@example.test", "星河科技"),
            {"name": "Lin_%", "email": "c3@example.test", "company": "星河科技"},
        )
        other_linning = self.assert_add_success(
            self.add_contact(self.db_path, "林宁", "c4@example.test", "远帆咨询"),
            {"name": "林宁", "email": "c4@example.test", "company": "远帆咨询"},
        )
        other_linab = self.assert_add_success(
            self.add_contact(self.db_path, "linAB", "c5@example.test", "远帆咨询"),
            {"name": "linAB", "email": "c5@example.test", "company": "远帆咨询"},
        )
        self.assertLess(zhoulin["id"], linning["id"])
        self.assertLess(linning["id"], lin_literal["id"])
        self.assertLess(lin_literal["id"], other_linning["id"])
        self.assertLess(other_linning["id"], other_linab["id"])
        return zhoulin, linning, lin_literal, other_linning, other_linab

    def list_name(self, db_path, company, name):
        """以独立子进程执行 list --company --name（--db 仍在子命令之前）。"""
        return self.run_crm(
            db_path, "list", "--company", company, "--name", name
        )

    def assert_name_list_success(self, company, name, expected_records):
        """断言带 --name 的 list 成功且返回记录（含顺序）与期望完全一致。"""
        result = self.list_name(self.db_path, company, name)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        for record in records:
            self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
            self.assertIsInstance(record["id"], int)
        self.assertEqual(records, expected_records)
        return records

    def test_list_name_substring_returns_matches_sorted_by_id_within_company(self):
        zhoulin, linning, _lin_literal, other_linning, _other_linab = (
            self.seed_name_filter_contacts()
        )

        # “林”只命中星河科技的周林和林宁，按 add 返回编号升序
        records = self.assert_name_list_success("星河科技", "林", [zhoulin, linning])
        self.assertEqual(
            [r["id"] for r in records], [zhoulin["id"], linning["id"]]
        )
        # 不包含远帆咨询的同名记录
        self.assertNotIn(other_linning["id"], [r["id"] for r in records])
        self.assertTrue(all(r["company"] == "星河科技" for r in records))

        # 远帆咨询的“林”只命中远帆的林宁，两家公司互不串扰
        self.assert_name_list_success("远帆咨询", "林", [other_linning])
        # 未录入公司即使给出姓名也返回空数组
        self.assert_name_list_success("未录入公司", "林", [])

    def test_list_name_ignores_surrounding_whitespace_in_company_and_name(self):
        zhoulin, linning, _lin_literal, _other_linning, _other_linab = (
            self.seed_name_filter_contacts()
        )

        # 公司名和姓名条件首尾带空格或制表符时，结果与不带空白时相同
        for company, name in (
            ("  星河科技  ", "  林  "),
            ("\t星河科技\t", "\t林\t"),
            (" \t星河科技 \t", " \t林 \t"),
            ("  星河科技", "林  "),
            ("星河科技  ", "  林"),
        ):
            with self.subTest(company=company, name=name):
                self.assert_name_list_success(company, name, [zhoulin, linning])

    def test_list_without_name_returns_all_records_of_company(self):
        zhoulin, linning, lin_literal, other_linning, other_linab = (
            self.seed_name_filter_contacts()
        )

        # 省略 --name 时返回星河科技全部三条，仍按编号升序
        self.assert_list_success(
            self.db_path, "星河科技", [zhoulin, linning, lin_literal]
        )
        # 远帆咨询的两条不受影响
        self.assert_list_success(
            self.db_path, "远帆咨询", [other_linning, other_linab]
        )

    def test_list_name_substring_is_case_sensitive(self):
        _zhoulin, _linning, lin_literal, _other_linning, other_linab = (
            self.seed_name_filter_contacts()
        )

        # Lin 只命中实际含该子串的 Lin_%；小写 lin 在星河科技无命中
        self.assert_name_list_success("星河科技", "Lin", [lin_literal])
        self.assert_name_list_success("星河科技", "lin", [])
        # 远帆咨询内小写 lin 命中 linAB，大写 Lin 无命中
        self.assert_name_list_success("远帆咨询", "lin", [other_linab])
        self.assert_name_list_success("远帆咨询", "Lin", [])

    def test_list_name_percent_and_underscore_are_literal_substrings(self):
        _zhoulin, _linning, lin_literal, _other_linning, _other_linab = (
            self.seed_name_filter_contacts()
        )

        # % 与 _ 保持字面子串语义：只命中实际含该字符的 Lin_%，
        # 不会像通配符那样命中全部记录
        for symbol in ("%", "_", "Lin_%"):
            with self.subTest(symbol=symbol):
                self.assert_name_list_success("星河科技", symbol, [lin_literal])
                self.assert_name_list_success("远帆咨询", symbol, [])

    def test_list_name_without_match_returns_empty_array(self):
        self.seed_name_filter_contacts()

        for name in ("无此姓名", "X9", "周林宁"):
            with self.subTest(name=name):
                self.assert_name_list_success("星河科技", name, [])

    def test_list_name_success_output_is_a_single_json_array(self):
        zhoulin, linning, _lin_literal, _other_linning, _other_linab = (
            self.seed_name_filter_contacts()
        )

        result = self.list_name(self.db_path, "星河科技", "林")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")

        text = result.stdout.decode("utf-8")
        # 标准输出整体只包含一个 JSON 数组，print 追加恰好一个换行
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(text.count("\n"), 1)
        records = json.loads(text)
        self.assertIsInstance(records, list)
        self.assertEqual(records, [zhoulin, linning])
        # 每条记录只含四个字段，字段值与新增结果一致
        for record in records:
            self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
            self.assertIsInstance(record["id"], int)

    def test_list_empty_or_blank_name_is_rejected(self):
        self.seed_name_filter_contacts()

        for name in ("", "   ", "\t\t", " \t "):
            with self.subTest(name=name):
                result = self.list_name(self.db_path, "星河科技", name)
                self.assert_list_rejected(result, "name: must not be empty")

    def test_list_empty_company_and_name_reports_only_company_error(self):
        self.seed_name_filter_contacts()

        # 公司和姓名同时为空时，只报告 company 错误，退出码与输出通道规则不变
        for company, name in (
            ("", ""),
            ("   ", "  "),
            ("\t\t", " \t "),
        ):
            with self.subTest(company=company, name=name):
                result = self.list_name(self.db_path, company, name)
                self.assert_list_rejected(result, "company: must not be empty")

    def test_list_invalid_name_leaves_existing_records_unchanged(self):
        zhoulin, linning, lin_literal, other_linning, other_linab = (
            self.seed_name_filter_contacts()
        )

        # 姓名无效、公司有效：只报告姓名错误
        for name in ("", "   ", "\t\t", " \t "):
            with self.subTest(name=name):
                result = self.list_name(self.db_path, "星河科技", name)
                self.assert_list_rejected(result, "name: must not be empty")

                # 拒绝查询后两家公司记录的数量和字段均不变
                self.assert_list_success(
                    self.db_path, "星河科技", [zhoulin, linning, lin_literal]
                )
                self.assert_list_success(
                    self.db_path, "远帆咨询", [other_linning, other_linab]
                )

        # 公司与姓名同时无效：只报告公司错误，记录同样不变
        result = self.list_name(self.db_path, "  ", "\t")
        self.assert_list_rejected(result, "company: must not be empty")
        self.assert_list_success(
            self.db_path, "星河科技", [zhoulin, linning, lin_literal]
        )
        self.assert_list_success(
            self.db_path, "远帆咨询", [other_linning, other_linab]
        )

    def test_list_invalid_name_does_not_create_missing_database(self):
        for index, name in enumerate(("", "   ", "\t\t", " \t ")):
            fresh_db = self.tmpdir / f"list-name-fresh-{index}.sqlite3"
            with self.subTest(name=name):
                # 父目录已存在，但数据库文件尚不存在
                self.assertTrue(self.tmpdir.is_dir())
                self.assertFalse(fresh_db.exists())
                result = self.list_name(fresh_db, "星河科技", name)
                self.assert_list_rejected(result, "name: must not be empty")
                # 拒绝后数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    # ---- update-email 子命令的回归测试 ----

    def update_email(self, db_path, contact_id, email):
        return self.run_crm(
            db_path, "update-email", "--id", str(contact_id), "--email", email
        )

    def seed_update_email_contacts(self):
        """新增 update-email 固定样例：林宁/许禾（星河科技）、周岚（远帆咨询）。"""
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
        self.assertLess(lin["id"], xu["id"])
        self.assertLess(xu["id"], zhou["id"])
        return lin, xu, zhou

    def assert_update_success(self, result, expected):
        """断言更新成功并返回解析后的联系人字典。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        # 标准输出整体可解析为单个联系人 JSON 对象，只含原有四个字段
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertEqual(record, expected)
        return record

    def assert_update_rejected(self, result, expected_stderr_line):
        """断言 update-email 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )

    def test_update_email_success_persists_and_preserves_other_records(self):
        lin, xu, zhou = self.seed_update_email_contacts()

        # 编号与邮箱输入均带首尾空白，编号还带前导零
        result = self.update_email(
            self.db_path, f"  00{lin['id']}  ", "  Lin.New@Example.test  "
        )
        updated_lin = self.assert_update_success(
            result,
            {
                "id": lin["id"],
                "name": "林宁",
                "email": "Lin.New@Example.test",
                "company": "星河科技",
            },
        )
        # 邮箱去除首尾空白并保留大小写，编号、姓名和公司不变
        self.assertEqual(updated_lin["email"], "Lin.New@Example.test")
        self.assertEqual(updated_lin["id"], lin["id"])
        self.assertEqual(updated_lin["name"], lin["name"])
        self.assertEqual(updated_lin["company"], lin["company"])

        # 独立命令按公司查询读到新邮箱，列表保持编号升序，其他记录不变
        records = self.assert_list_success(self.db_path, "星河科技", [updated_lin, xu])
        self.assertEqual([r["id"] for r in records], sorted(r["id"] for r in records))
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])
        # 记录总数不变
        self.assertEqual(len(records), 2)

    def test_update_email_same_value_again_still_succeeds_without_new_records(self):
        lin, xu, zhou = self.seed_update_email_contacts()

        first = self.update_email(self.db_path, lin["id"], "Lin.New@Example.test")
        updated_lin = self.assert_update_success(
            first, {**lin, "email": "Lin.New@Example.test"}
        )

        # 再次提交相同邮箱仍按成功处理
        second = self.update_email(self.db_path, lin["id"], "Lin.New@Example.test")
        self.assert_update_success(second, updated_lin)

        # 不增加记录，所有记录内容保持不变
        self.assert_list_success(self.db_path, "星河科技", [updated_lin, xu])
        self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_email_invalid_inputs_leave_records_unchanged(self):
        lin, xu, zhou = self.seed_update_email_contacts()

        for (contact_id, email), expected_stderr in INVALID_UPDATE_EMAIL_CASES:
            with self.subTest(contact_id=contact_id, email=email):
                result = self.update_email(self.db_path, contact_id, email)
                self.assert_update_rejected(result, expected_stderr)

                # 拒绝后两家公司的记录逐字段不变
                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_email_unknown_id_reports_not_found_and_keeps_records(self):
        lin, xu, zhou = self.seed_update_email_contacts()

        for unknown_id in (zhou["id"] + 1000, 9223372036854775807):
            with self.subTest(contact_id=unknown_id):
                result = self.update_email(
                    self.db_path, unknown_id, "ok@example.test"
                )
                self.assert_update_rejected(result, "id: contact not found")

                self.assert_list_success(self.db_path, "星河科技", [lin, xu])
                self.assert_list_success(self.db_path, "远帆咨询", [zhou])

    def test_update_email_invalid_input_does_not_create_missing_database(self):
        for index, ((contact_id, email), expected_stderr) in enumerate(
            INVALID_UPDATE_EMAIL_CASES
        ):
            fresh_db = self.tmpdir / f"update-fresh-{index}.sqlite3"
            with self.subTest(contact_id=contact_id, email=email):
                self.assertFalse(fresh_db.exists())
                result = self.update_email(fresh_db, contact_id, email)
                self.assert_update_rejected(result, expected_stderr)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    def test_update_email_unknown_id_creates_empty_database(self):
        fresh_db = self.tmpdir / "update-unknown.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 合法输入但编号不存在：创建空数据库并返回未找到
        result = self.update_email(fresh_db, "1", "ok@example.test")
        self.assert_update_rejected(result, "id: contact not found")
        self.assertTrue(fresh_db.exists())

        # 随后查询得到空数组
        self.assert_list_success(fresh_db, "星河科技", [])


if __name__ == "__main__":
    unittest.main()
