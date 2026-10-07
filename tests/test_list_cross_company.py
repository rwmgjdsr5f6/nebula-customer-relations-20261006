"""crm.py list 子命令省略 --company 时跨公司查询的回归测试。

固定样例在全新数据库中按以下顺序新增（编号以新增返回结果为准）：
- 星河科技：林宁（lin@example.test）
- 远帆咨询：林宁（lin@example.test，与前者同名同邮箱）
- 星河科技：许禾（xu@example.test）

本文件只验证既有行为：list 省略 --company 时跨全部公司查询，
显式传入空白公司仍按 company: must not be empty 拒绝，二者不等价。

仅使用 Python 3 标准库 unittest，通过子进程执行 crm.py，
每次查询都是独立进程，样例数据放在独立临时目录中，结束后自动清理；
重复执行结果一致，不依赖网络或第三方库。
在项目根目录运行：python -m unittest discover -s tests
"""

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CRM_SCRIPT = PROJECT_ROOT / "crm.py"

COMPANY_XINGHE = "星河科技"
COMPANY_YUANFAN = "远帆咨询"

COMPANY_ERROR_LINE = "company: must not be empty"
NAME_ERROR_LINE = "name: must not be empty"
EMAIL_ERROR_LINE = "email: invalid email address"

# 空白姓名与空白公司的各种形态
BLANK_VALUES = ["", "   ", "\t\t", " \t "]

# 省略 --company 时仍属非法的邮箱取值
INVALID_EMAILS = [
    "",
    "   ",
    "\t\t",
    " \t ",
    "noatsign.example.test",
    "a b@example.test",
]

# 用于区分“省略公司”与“显式空白公司”的失败用例：
# (list 子命令额外参数, 期望的标准错误行)
OMITTED_COMPANY_FAILURE_CASES = [
    # 显式传入空白公司：即使同时省略其他条件，也仍是公司错误
    (["--company", ""], COMPANY_ERROR_LINE),
    (["--company", "   "], COMPANY_ERROR_LINE),
    (["--company", "\t\t"], COMPANY_ERROR_LINE),
    (["--company", " \t "], COMPANY_ERROR_LINE),
    # 显式空白公司与空白姓名、非法邮箱叠加时，公司错误优先
    (["--company", "   ", "--name", "   "], COMPANY_ERROR_LINE),
    (["--company", "", "--email", "noatsign.example.test"], COMPANY_ERROR_LINE),
    # 省略公司、只传空白姓名：姓名错误
    (["--name", ""], NAME_ERROR_LINE),
    (["--name", "   "], NAME_ERROR_LINE),
    (["--name", "\t\t"], NAME_ERROR_LINE),
    (["--name", " \t "], NAME_ERROR_LINE),
    # 省略公司、只传非法邮箱：邮箱错误
    (["--email", ""], EMAIL_ERROR_LINE),
    (["--email", "   "], EMAIL_ERROR_LINE),
    (["--email", "\t\t"], EMAIL_ERROR_LINE),
    (["--email", " \t "], EMAIL_ERROR_LINE),
    (["--email", "noatsign.example.test"], EMAIL_ERROR_LINE),
    (["--email", "a b@example.test"], EMAIL_ERROR_LINE),
]


class ListCrossCompanyTestCase(unittest.TestCase):
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

    def list_contacts(self, db_path, extra_args=None, fmt=None):
        """执行 list。extra_args 中的每个参数原样传入，省略 --company 即不传。"""
        cli_args = ["list"]
        if extra_args:
            cli_args.extend(extra_args)
        if fmt is not None:
            cli_args.extend(["--format", fmt])
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

    def assert_json_records(self, result, expected_records):
        """断言成功的 JSON list：退出码 0、无标准错误、记录（含顺序）完全一致。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        # 标准输出整体可解析为单个 JSON 数组（无多余输出）
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertEqual(records, expected_records)
        return records

    def seed_cross_company_contacts(self):
        """按验收顺序在全新数据库新增三人，返回各自的新增结果。"""
        lin_xinghe = self.assert_add_success(
            self.add_contact(
                self.db_path, "林宁", "lin@example.test", COMPANY_XINGHE
            ),
            {
                "name": "林宁",
                "email": "lin@example.test",
                "company": COMPANY_XINGHE,
            },
        )
        lin_yuanfan = self.assert_add_success(
            self.add_contact(
                self.db_path, "林宁", "lin@example.test", COMPANY_YUANFAN
            ),
            {
                "name": "林宁",
                "email": "lin@example.test",
                "company": COMPANY_YUANFAN,
            },
        )
        xu_he = self.assert_add_success(
            self.add_contact(
                self.db_path, "许禾", "xu@example.test", COMPANY_XINGHE
            ),
            {
                "name": "许禾",
                "email": "xu@example.test",
                "company": COMPANY_XINGHE,
            },
        )

        # 编号严格按新增顺序升序
        ids = [lin_xinghe["id"], lin_yuanfan["id"], xu_he["id"]]
        self.assertEqual(ids, sorted(ids))
        # 同名同邮箱的两人编号不同、公司不同，均被保留
        self.assertNotEqual(lin_xinghe["id"], lin_yuanfan["id"])
        self.assertEqual(lin_xinghe["name"], lin_yuanfan["name"])
        self.assertEqual(lin_xinghe["email"], lin_yuanfan["email"])
        return lin_xinghe, lin_yuanfan, xu_he

    # ---- 无条件跨公司查询 ----

    def test_unconditional_list_returns_all_companies_sorted_by_id(self):
        lin_xinghe, lin_yuanfan, xu_he = self.seed_cross_company_contacts()

        # 省略 --company（以及全部筛选条件）：跨公司返回三条完整记录
        result = self.list_contacts(self.db_path)
        records = self.assert_json_records(
            result, [lin_xinghe, lin_yuanfan, xu_he]
        )

        # 按 add 返回的 id 升序排列
        self.assertEqual(
            [r["id"] for r in records],
            [lin_xinghe["id"], lin_yuanfan["id"], xu_he["id"]],
        )
        # 每条记录只含既有四个字段，字段值与新增结果逐字一致
        for record, added in zip(
            records, (lin_xinghe, lin_yuanfan, xu_he)
        ):
            self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
            self.assertEqual(record, added)

        # 同名同邮箱的两人均保留，第三人邮箱不同
        same_email = [r for r in records if r["email"] == "lin@example.test"]
        self.assertEqual(
            [(r["id"], r["company"]) for r in same_email],
            [
                (lin_xinghe["id"], COMPANY_XINGHE),
                (lin_yuanfan["id"], COMPANY_YUANFAN),
            ],
        )

        # 每次查询都是独立进程，重复执行的原始输出完全一致
        again = self.list_contacts(self.db_path)
        self.assertEqual(again.returncode, 0, again.stderr.decode("utf-8"))
        self.assertEqual(again.stderr, b"")
        self.assertEqual(again.stdout, result.stdout)

    # ---- 省略公司时的 --name / --email 筛选 ----

    def test_omitted_company_name_filter_returns_two_lins(self):
        lin_xinghe, lin_yuanfan, xu_he = self.seed_cross_company_contacts()

        # 筛选值去除首尾空白；姓名按字面子串匹配、区分大小写
        cases = [
            # 带首尾空白的“林”命中两家公司的两位林宁
            ("  林  ", [lin_xinghe, lin_yuanfan]),
            ("林宁", [lin_xinghe, lin_yuanfan]),
            # 单字“宁”同样是子串匹配
            ("\t宁\t", [lin_xinghe, lin_yuanfan]),
            (" 许 ", [xu_he]),
            ("禾", [xu_he]),
            # 非子串不命中
            ("林许", []),
            ("未录入", []),
            # 拉丁字符只按姓名列字面匹配，不会命中邮箱里的 lin
            ("lin", []),
            ("LIN", []),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                result = self.list_contacts(self.db_path, ["--name", name])
                records = self.assert_json_records(result, expected)
                self.assertEqual(
                    [r["id"] for r in records], sorted(r["id"] for r in records)
                )

    def test_omitted_company_email_filter_returns_two_lins(self):
        lin_xinghe, lin_yuanfan, xu_he = self.seed_cross_company_contacts()

        # 邮箱去除首尾空白后按完整值精确匹配、区分大小写
        success_cases = [
            ("  lin@example.test  ", [lin_xinghe, lin_yuanfan]),
            ("lin@example.test", [lin_xinghe, lin_yuanfan]),
            ("\txu@example.test\t", [xu_he]),
            # 大小写不同或缺一段都不命中
            ("LIN@EXAMPLE.TEST", []),
            ("Lin@Example.Test", []),
            ("lin@example.tes", []),
        ]
        for email, expected in success_cases:
            with self.subTest(email=email):
                result = self.list_contacts(self.db_path, ["--email", email])
                records = self.assert_json_records(result, expected)
                self.assertEqual(
                    [r["id"] for r in records], sorted(r["id"] for r in records)
                )

    def test_omitted_company_name_and_email_combined(self):
        lin_xinghe, lin_yuanfan, xu_he = self.seed_cross_company_contacts()

        # 姓名与邮箱联合筛选：两位林宁同时满足两个条件
        self.assert_json_records(
            self.list_contacts(
                self.db_path,
                ["--name", "  林  ", "--email", "  lin@example.test  "],
            ),
            [lin_xinghe, lin_yuanfan],
        )
        # 姓名许与 lin@example.test 联合：许禾邮箱不同，结果为空
        self.assert_json_records(
            self.list_contacts(
                self.db_path, ["--name", "许", "--email", "lin@example.test"]
            ),
            [],
        )
        # 姓名许与许禾本人邮箱联合：只命中许禾
        self.assert_json_records(
            self.list_contacts(
                self.db_path, ["--name", "许", "--email", "xu@example.test"]
            ),
            [xu_he],
        )

    # ---- 输出格式 ----

    def test_default_format_equals_explicit_json(self):
        self.seed_cross_company_contacts()

        omitted = self.list_contacts(self.db_path)
        explicit = self.list_contacts(self.db_path, fmt="json")
        self.assertEqual(omitted.returncode, 0, omitted.stderr.decode("utf-8"))
        self.assertEqual(explicit.returncode, 0, explicit.stderr.decode("utf-8"))
        self.assertEqual(omitted.stderr, b"")
        self.assertEqual(explicit.stderr, b"")
        # 默认 JSON 与显式 json 的原始输出逐字节相同
        self.assertEqual(omitted.stdout, explicit.stdout)
        records = json.loads(omitted.stdout.decode("utf-8"))
        self.assertEqual(len(records), 3)

    def test_csv_header_records_order_and_crlf_match_json(self):
        lin_xinghe, lin_yuanfan, xu_he = self.seed_cross_company_contacts()
        expected = [lin_xinghe, lin_yuanfan, xu_he]

        csv_result = self.list_contacts(self.db_path, fmt="csv")
        json_result = self.list_contacts(self.db_path, fmt="json")
        self.assertEqual(csv_result.returncode, 0, csv_result.stderr.decode("utf-8"))
        self.assertEqual(csv_result.stderr, b"")

        text = csv_result.stdout.decode("utf-8")
        rows = list(csv.reader(io.StringIO(text)))

        # 表头固定为 id,name,email,company
        self.assertEqual(rows[0], ["id", "name", "email", "company"])
        data_rows = rows[1:]
        json_records = self.assert_json_records(json_result, expected)

        # 解析后的记录及顺序与 JSON 一致
        self.assertEqual(len(data_rows), len(json_records))
        for row, record in zip(data_rows, json_records):
            self.assertEqual(
                row,
                [
                    str(record["id"]),
                    record["name"],
                    record["email"],
                    record["company"],
                ],
            )

        # 全部行结束符均为 CRLF，且无额外空行或提示文字
        self.assertNotIn("\r", text.replace("\r\n", ""))
        self.assertNotIn("\n", text.replace("\r\n", ""))
        expected_text = (
            "id,name,email,company\r\n"
            + "".join(
                f'{record["id"]},{record["name"]},{record["email"]},'
                f'{record["company"]}\r\n'
                for record in expected
            )
        )
        self.assertEqual(text, expected_text)

    # ---- 省略公司与空白公司的区别 ----

    def test_blank_company_is_distinct_from_omitted_company(self):
        self.seed_cross_company_contacts()

        for extra_args, expected_stderr in OMITTED_COMPANY_FAILURE_CASES:
            with self.subTest(extra_args=extra_args):
                result = self.list_contacts(self.db_path, extra_args)
                self.assert_list_rejected(result, expected_stderr)

    def test_omitted_company_blank_name_and_blank_company_differ(self):
        self.seed_cross_company_contacts()

        # 显式空白公司：company 错误
        for company in BLANK_VALUES:
            with self.subTest(company=company):
                result = self.list_contacts(self.db_path, ["--company", company])
                self.assert_list_rejected(result, COMPANY_ERROR_LINE)

        # 省略公司、空白姓名：name 错误（而不是 company 错误）
        for name in BLANK_VALUES:
            with self.subTest(name=name):
                result = self.list_contacts(self.db_path, ["--name", name])
                self.assert_list_rejected(result, NAME_ERROR_LINE)

        # 省略公司、非法邮箱：email 错误（而不是 company 错误）
        for email in INVALID_EMAILS:
            with self.subTest(email=email):
                result = self.list_contacts(self.db_path, ["--email", email])
                self.assert_list_rejected(result, EMAIL_ERROR_LINE)

    # ---- 失败查询不创建数据库 ----

    def test_failed_queries_do_not_create_missing_database(self):
        for index, (extra_args, expected_stderr) in enumerate(
            OMITTED_COMPANY_FAILURE_CASES
        ):
            fresh_db = self.tmpdir / f"cross-company-fresh-{index}.sqlite3"
            with self.subTest(extra_args=extra_args):
                self.assertFalse(fresh_db.exists())
                result = self.list_contacts(fresh_db, extra_args)
                self.assert_list_rejected(result, expected_stderr)
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    # ---- 查询不改变已有记录 ----

    def test_successful_and_failed_queries_leave_records_unchanged(self):
        lin_xinghe, lin_yuanfan, xu_he = self.seed_cross_company_contacts()

        # 成功查询：无条件、姓名筛选、邮箱筛选、联合筛选（含空结果）
        successful = [
            [],
            ["--name", "  林  "],
            ["--email", "  lin@example.test  "],
            ["--name", "许", "--email", "lin@example.test"],
            ["--name", "no-such-name"],
        ]
        for extra_args in successful:
            with self.subTest(extra_args=extra_args):
                result = self.list_contacts(self.db_path, extra_args)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                self.assertEqual(result.stderr, b"")

        # 失败查询：空白公司、省略公司加空白姓名、省略公司加非法邮箱
        for extra_args, expected_stderr in OMITTED_COMPANY_FAILURE_CASES:
            with self.subTest(extra_args=extra_args):
                result = self.list_contacts(self.db_path, extra_args)
                self.assert_list_rejected(result, expected_stderr)

        # 随后按两家公司查询：原始内容完整，编号升序不变
        self.assert_json_records(
            self.list_contacts(
                self.db_path, ["--company", COMPANY_XINGHE]
            ),
            [lin_xinghe, xu_he],
        )
        self.assert_json_records(
            self.list_contacts(
                self.db_path, ["--company", COMPANY_YUANFAN]
            ),
            [lin_yuanfan],
        )

        # 再做一次无条件跨公司查询，三条记录仍与新增结果一致
        self.assert_json_records(
            self.list_contacts(self.db_path),
            [lin_xinghe, lin_yuanfan, xu_he],
        )

    # ---- 不存在的数据库 ----

    def test_unconditional_list_creates_empty_database_with_header_only_csv(self):
        fresh_db = self.tmpdir / "cross-company-empty.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 父目录已存在、数据库文件尚不存在：无条件 list 创建空库并返回 []
        result = self.list_contacts(fresh_db)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), [])
        self.assertTrue(fresh_db.exists())

        # CSV 只输出表头，且以 CRLF 结束
        csv_result = self.list_contacts(fresh_db, fmt="csv")
        self.assertEqual(csv_result.returncode, 0, csv_result.stderr.decode("utf-8"))
        self.assertEqual(csv_result.stderr, b"")
        self.assertEqual(
            csv_result.stdout.decode("utf-8"), "id,name,email,company\r\n"
        )

        # 再次通过独立进程查询仍为空，不产生联系人
        again = self.list_contacts(fresh_db)
        self.assertEqual(again.returncode, 0, again.stderr.decode("utf-8"))
        self.assertEqual(again.stderr, b"")
        self.assertEqual(json.loads(again.stdout.decode("utf-8")), [])


if __name__ == "__main__":
    unittest.main()
