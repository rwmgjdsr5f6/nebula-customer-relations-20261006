"""crm.py list 子命令省略 --company 时跨公司查询的回归测试。

固定样例为两家公司三位联系人（按此顺序新增到全新数据库，编号以新增结果为准）：
- 星河科技：林宁（lin@example.test）
- 远帆咨询：林宁（lin@example.test，与前者同名同邮箱但分属不同公司）
- 星河科技：许禾（xu@example.test）

验证的既有行为：
- 省略 --company 时跨全部公司查询，按编号升序返回，同名同邮箱的两人均保留；
- 省略公司与显式传入空白公司不是同一情况：后者报 company 错误，
  前者继续校验 --name / --email；
- 姓名按区分大小写的字面子串匹配，邮箱按区分大小写的完整值匹配，
  筛选值仍去除首尾空白；
- 默认 JSON 与显式 --format json 内容相同，CSV 表头固定且行结束符为 CRLF，
  解析后的记录及顺序与 JSON 一致；
- 成功查询退出码 0、标准错误为空；校验失败退出码 2、标准输出为空，
  且不创建尚不存在的数据库文件；
- 父目录存在而数据库文件不存在时，无条件 list 创建空库并返回空结果。

仅使用 Python 3 标准库 unittest，每次查询都启动新的 crm.py 子进程，
所有样例数据都放在独立的临时目录中，测试结束后自动清理；重复执行结果一致，
不依赖网络或任何第三方库。
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
LIN_EMAIL = "lin@example.test"
XU_EMAIL = "xu@example.test"

COMPANY_ERROR_LINE = "company: must not be empty"
NAME_ERROR_LINE = "name: must not be empty"
EMAIL_ERROR_LINE = "email: invalid email address"

# 空串、纯空白或缺少 @ 的邮箱都应在校验阶段被拒绝
INVALID_EMAILS = ["", "   ", "\t\t", " \t ", "noatsign.example.test"]
BLANK_VALUES = ["", "   ", "\t\t", " \t "]


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

    def list_cross_company(self, db_path, fmt=None, name=None, email=None,
                           company=NotImplemented):
        """执行省略 --company 的 list（company 参数仅用于显式传值的场景）。"""
        cli_args = ["list"]
        if company is not NotImplemented:
            cli_args.extend(["--company", company])
        if fmt is not None:
            cli_args.extend(["--format", fmt])
        if name is not None:
            cli_args.extend(["--name", name])
        if email is not None:
            cli_args.extend(["--email", email])
        return self.run_crm(db_path, *cli_args)

    def list_company(self, db_path, company, fmt=None):
        return self.run_crm(
            db_path, "list", "--company", company,
            *(["--format", fmt] if fmt is not None else [])
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

    def cross_company_list_records(self, db_path, fmt=None, name=None, email=None):
        """执行省略公司的 list，断言成功后返回解析后的 JSON 记录列表。"""
        result = self.list_cross_company(
            db_path, fmt=fmt, name=name, email=email
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        return records

    def assert_cross_company_list_success(self, db_path, expected_records,
                                          fmt=None, name=None, email=None):
        """断言省略公司的 list 成功：退出码 0、无标准错误，记录（含顺序）一致。"""
        records = self.cross_company_list_records(
            db_path, fmt=fmt, name=name, email=email
        )
        self.assertEqual(records, expected_records)
        return records

    def assert_list_rejected(self, result, expected_stderr_line):
        """断言 list 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), expected_stderr_line + "\n"
        )

    def parse_csv(self, raw_text):
        """按 CSV 规则解析标准输出。"""
        return list(csv.reader(io.StringIO(raw_text)))

    def seed_contacts(self):
        """在全新数据库依次新增三位联系人并返回新增记录。

        前两位均为林宁、邮箱同为 lin@example.test，但分属星河科技与远帆咨询；
        第三位为星河科技的许禾。编号以 add 返回值为准且严格升序。
        """
        lin_ning_xinghe = self.assert_add_success(
            self.add_contact(self.db_path, "林宁", LIN_EMAIL, COMPANY_XINGHE),
            {"name": "林宁", "email": LIN_EMAIL, "company": COMPANY_XINGHE},
        )
        lin_ning_yuanfan = self.assert_add_success(
            self.add_contact(self.db_path, "林宁", LIN_EMAIL, COMPANY_YUANFAN),
            {"name": "林宁", "email": LIN_EMAIL, "company": COMPANY_YUANFAN},
        )
        xu_he = self.assert_add_success(
            self.add_contact(self.db_path, "许禾", XU_EMAIL, COMPANY_XINGHE),
            {"name": "许禾", "email": XU_EMAIL, "company": COMPANY_XINGHE},
        )

        ids = [r["id"] for r in (lin_ning_xinghe, lin_ning_yuanfan, xu_he)]
        self.assertEqual(ids, sorted(ids))
        # 三位联系人编号互不相同
        self.assertEqual(len(set(ids)), 3)
        return lin_ning_xinghe, lin_ning_yuanfan, xu_he

    # ---- 省略公司时的成功查询行为 ----

    def test_list_without_company_returns_all_records_sorted_by_id(self):
        lin_ning_xinghe, lin_ning_yuanfan, xu_he = self.seed_contacts()
        expected = [lin_ning_xinghe, lin_ning_yuanfan, xu_he]

        result = self.list_cross_company(self.db_path)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")

        records = json.loads(result.stdout.decode("utf-8"))
        # 三条完整记录，按 add 返回的编号升序排列
        self.assertEqual(records, expected)
        self.assertEqual(
            [r["id"] for r in records],
            [lin_ning_xinghe["id"], lin_ning_yuanfan["id"], xu_he["id"]],
        )
        # 每条记录仅含既有四个字段，字段值与新增结果逐字一致
        for record, added in zip(records, expected):
            self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
            self.assertEqual(record, added)

        # 同名同邮箱、分属两家公司的两人均保留
        same_name_email = [r for r in records if r["name"] == "林宁"]
        self.assertEqual(len(same_name_email), 2)
        self.assertEqual({r["email"] for r in same_name_email}, {LIN_EMAIL})
        self.assertEqual(
            {r["company"] for r in same_name_email},
            {COMPANY_XINGHE, COMPANY_YUANFAN},
        )

    def test_list_without_company_name_filter_returns_first_two(self):
        lin_ning_xinghe, lin_ning_yuanfan, xu_he = self.seed_contacts()

        # 省略公司并按 --name 林 筛选：只返回跨公司的两位林宁，许禾不返回
        records = self.assert_cross_company_list_success(
            self.db_path, [lin_ning_xinghe, lin_ning_yuanfan], name="林"
        )
        self.assertEqual(
            [r["id"] for r in records],
            [lin_ning_xinghe["id"], lin_ning_yuanfan["id"]],
        )
        # 许禾编号不出现在结果中
        self.assertNotIn(xu_he["id"], [r["id"] for r in records])

    def test_list_without_company_email_filter_returns_first_two(self):
        lin_ning_xinghe, lin_ning_yuanfan, _xu_he = self.seed_contacts()

        # 省略公司并按完整邮箱筛选：两位同邮箱的林宁都返回
        self.assert_cross_company_list_success(
            self.db_path,
            [lin_ning_xinghe, lin_ning_yuanfan],
            email=LIN_EMAIL,
        )

    def test_list_without_company_name_and_email_combined(self):
        _lin_ning_xinghe, _lin_ning_yuanfan, _xu_he = self.seed_contacts()

        # 姓名许与林宁邮箱联合筛选：许禾邮箱不同，结果为空数组
        records = self.assert_cross_company_list_success(
            self.db_path, [], name="许", email=LIN_EMAIL
        )
        self.assertEqual(records, [])

        # 联合为 林宁 + 该邮箱时仍返回前两人
        self.assert_cross_company_list_success(
            self.db_path,
            [_lin_ning_xinghe, _lin_ning_yuanfan],
            name="林",
            email=LIN_EMAIL,
        )

    def test_filters_strip_surrounding_whitespace(self):
        lin_ning_xinghe, lin_ning_yuanfan, _xu_he = self.seed_contacts()
        expected = [lin_ning_xinghe, lin_ning_yuanfan]

        for padded_name in ("  林", "林  ", "\t林\t", " \t林 \t"):
            with self.subTest(padded_name=padded_name):
                self.assert_cross_company_list_success(
                    self.db_path, expected, name=padded_name
                )
        for padded_email in (
            "  " + LIN_EMAIL,
            LIN_EMAIL + "  ",
            "\t" + LIN_EMAIL + "\t",
            " \t" + LIN_EMAIL + " \t",
        ):
            with self.subTest(padded_email=padded_email):
                self.assert_cross_company_list_success(
                    self.db_path, expected, email=padded_email
                )

        # 姓名与邮箱都带首尾空白时，联合筛选仍只返回前两人
        self.assert_cross_company_list_success(
            self.db_path, expected, name="  林  ", email="  " + LIN_EMAIL + "  "
        )
        # 空白被剥离后，许与该邮箱联合仍无命中
        self.assert_cross_company_list_success(
            self.db_path, [], name="  许  ", email="  " + LIN_EMAIL + "  "
        )

    def test_name_filter_is_case_sensitive_literal_substring(self):
        _lin_ning_xinghe, _lin_ning_yuanfan, xu_he = self.seed_contacts()

        # 字面子串：林、宁、林宁 都命中两位林宁；每条结果姓名都含该子串
        for fragment in ("林", "宁", "林宁"):
            with self.subTest(fragment=fragment):
                records = self.cross_company_list_records(
                    self.db_path, name=fragment
                )
                self.assertEqual(len(records), 2)
                self.assertTrue(all(fragment in r["name"] for r in records))

        # 禾 只命中许禾
        records_he = self.cross_company_list_records(self.db_path, name="禾")
        self.assertEqual(len(records_he), 1)
        self.assertEqual(records_he[0], xu_he)

        # 不存在的中文字面与任何 ASCII 文本均无命中（不存在大小写折叠）
        for fragment in ("周", "LIN", "lin", "林宁林"):
            with self.subTest(fragment=fragment):
                self.assert_cross_company_list_success(
                    self.db_path, [], name=fragment
                )

    def test_email_filter_is_case_sensitive_full_value(self):
        self.seed_contacts()

        # 大小写不同的邮箱、被截断或被加长的地址都不命中：必须是完整值
        for email in (
            "LIN@EXAMPLE.TEST",
            "Lin@Example.Test",
            "lin@example.tes",
            "xulin@example.test",
            "lin@example.test.other",
        ):
            with self.subTest(email=email):
                self.assert_cross_company_list_success(
                    self.db_path, [], email=email
                )

        # 林宁的完整邮箱跨公司命中两人
        records = self.cross_company_list_records(self.db_path, email=LIN_EMAIL)
        self.assertEqual(len(records), 2)
        self.assertEqual({r["name"] for r in records}, {"林宁"})

        # 许禾的完整邮箱只命中许禾一人
        records = self.cross_company_list_records(self.db_path, email=XU_EMAIL)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "许禾")

    # ---- 输出格式 ----

    def test_default_json_equals_explicit_json(self):
        self.seed_contacts()

        omitted = self.list_cross_company(self.db_path)
        explicit = self.list_cross_company(self.db_path, fmt="json")
        self.assertEqual(omitted.returncode, 0, omitted.stderr.decode("utf-8"))
        self.assertEqual(explicit.returncode, 0, explicit.stderr.decode("utf-8"))
        self.assertEqual(omitted.stderr, b"")
        self.assertEqual(explicit.stderr, b"")
        # 默认 JSON 与显式 json 的标准输出逐字节相同
        self.assertEqual(omitted.stdout, explicit.stdout)
        records = json.loads(omitted.stdout.decode("utf-8"))
        self.assertEqual(len(records), 3)
        self.assertEqual(
            {r["company"] for r in records},
            {COMPANY_XINGHE, COMPANY_YUANFAN},
        )

    def test_csv_matches_json_records_order_with_crlf(self):
        lin_ning_xinghe, lin_ning_yuanfan, xu_he = self.seed_contacts()
        expected = [lin_ning_xinghe, lin_ning_yuanfan, xu_he]

        csv_result = self.list_cross_company(self.db_path, fmt="csv")
        json_result = self.list_cross_company(self.db_path, fmt="json")
        self.assertEqual(csv_result.returncode, 0, csv_result.stderr.decode("utf-8"))
        self.assertEqual(json_result.returncode, 0, json_result.stderr.decode("utf-8"))
        self.assertEqual(csv_result.stderr, b"")

        text = csv_result.stdout.decode("utf-8")
        rows = self.parse_csv(text)

        # 表头固定为 id,name,email,company
        self.assertEqual(rows[0], ["id", "name", "email", "company"])
        data_rows = rows[1:]
        json_records = json.loads(json_result.stdout.decode("utf-8"))
        self.assertEqual(json_records, expected)

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
        self.assertEqual(
            [row[0] for row in data_rows],
            [str(r["id"]) for r in expected],
        )

        # 行结束符为 CRLF：每行都以 \r\n 结束，且不存在裸 LF/CR
        expected_text = (
            "id,name,email,company\r\n"
            + "".join(
                f'{r["id"]},{r["name"]},{r["email"]},{r["company"]}\r\n'
                for r in expected
            )
        )
        self.assertEqual(text, expected_text)
        self.assertTrue(text.endswith("\r\n"))
        self.assertNotIn("\r", text.replace("\r\n", ""))
        self.assertNotIn("\n", text.replace("\r\n", ""))

    def test_csv_with_filters_matches_json(self):
        lin_ning_xinghe, lin_ning_yuanfan, _xu_he = self.seed_contacts()

        for kwargs in (
            {"name": "林"},
            {"email": LIN_EMAIL},
            {"name": "林", "email": LIN_EMAIL},
            {"name": "许", "email": LIN_EMAIL},
        ):
            with self.subTest(kwargs=kwargs):
                csv_result = self.list_cross_company(
                    self.db_path, fmt="csv", **kwargs
                )
                json_result = self.list_cross_company(
                    self.db_path, fmt="json", **kwargs
                )
                self.assertEqual(
                    csv_result.returncode, 0, csv_result.stderr.decode("utf-8")
                )
                rows = self.parse_csv(csv_result.stdout.decode("utf-8"))
                json_records = json.loads(json_result.stdout.decode("utf-8"))
                self.assertEqual(rows[0], ["id", "name", "email", "company"])
                data_rows = rows[1:]
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

        # 无命中时 CSV 只有表头一行
        no_match = self.list_cross_company(
            self.db_path, fmt="csv", name="许", email=LIN_EMAIL
        )
        self.assertEqual(no_match.returncode, 0, no_match.stderr.decode("utf-8"))
        self.assertEqual(no_match.stderr, b"")
        self.assertEqual(no_match.stdout.decode("utf-8"), "id,name,email,company\r\n")

    # ---- 省略公司与空白公司的区别 ----

    def test_explicit_blank_company_is_rejected(self):
        self.seed_contacts()

        # 显式传入空白公司与省略公司不同：一律报 company 错误，
        # 即使同时省略/提供其他条件
        for company in BLANK_VALUES:
            with self.subTest(company=company):
                result = self.list_cross_company(self.db_path, company=company)
                self.assert_list_rejected(result, COMPANY_ERROR_LINE)

        # 空白公司与空白姓名、无效邮箱同时出现时，公司错误仍优先
        result = self.list_cross_company(
            self.db_path, company="   ", name="   ", email="noatsign.example.test"
        )
        self.assert_list_rejected(result, COMPANY_ERROR_LINE)

    def test_omitted_company_blank_name_is_rejected(self):
        self.seed_contacts()

        # 省略公司、姓名为空白：报 name 错误（公司条件确实被省略而非当作空值）
        for name in BLANK_VALUES:
            with self.subTest(name=name):
                result = self.list_cross_company(self.db_path, name=name)
                self.assert_list_rejected(result, NAME_ERROR_LINE)

        # 姓名与邮箱同时无效时，姓名先于邮箱校验
        result = self.list_cross_company(
            self.db_path, name="   ", email="noatsign.example.test"
        )
        self.assert_list_rejected(result, NAME_ERROR_LINE)

    def test_omitted_company_invalid_email_is_rejected(self):
        self.seed_contacts()

        # 省略公司、邮箱无效：报 email 错误
        for email in INVALID_EMAILS:
            with self.subTest(email=email):
                result = self.list_cross_company(self.db_path, email=email)
                self.assert_list_rejected(result, EMAIL_ERROR_LINE)

    def test_failed_validation_does_not_create_missing_database(self):
        # 空白公司、省略公司加空白姓名、省略公司加无效邮箱：
        # 均在连接数据库前失败，文件及任何 SQLite 伴随文件都不应出现
        failing_invocations = (
            [("company", value) for value in BLANK_VALUES]
            + [("name", value) for value in BLANK_VALUES]
            + [("email", value) for value in INVALID_EMAILS]
        )
        for index, (field, value) in enumerate(failing_invocations):
            fresh_db = self.tmpdir / f"cross-company-fresh-{index}.sqlite3"
            with self.subTest(field=field, value=value):
                self.assertFalse(fresh_db.exists())
                result = self.list_cross_company(fresh_db, **{field: value})
                expected_line = {
                    "company": COMPANY_ERROR_LINE,
                    "name": NAME_ERROR_LINE,
                    "email": EMAIL_ERROR_LINE,
                }[field]
                self.assert_list_rejected(result, expected_line)
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

    # ---- 查询对已有数据的影响 ----

    def test_success_and_failed_queries_leave_records_unchanged(self):
        lin_ning_xinghe, lin_ning_yuanfan, xu_he = self.seed_contacts()

        # 成功的跨公司查询：全量、姓名、邮箱、联合且无命中
        successful = [
            {},
            {"name": "林"},
            {"email": LIN_EMAIL},
            {"name": "许", "email": LIN_EMAIL},
            {"fmt": "csv"},
            {"fmt": "csv", "name": "林", "email": LIN_EMAIL},
        ]
        for kwargs in successful:
            with self.subTest(kwargs=kwargs):
                result = self.list_cross_company(self.db_path, **kwargs)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                self.assertEqual(result.stderr, b"")

        # 失败的查询：空白公司、省略公司加空白姓名/无效邮箱
        failing = [
            {"company": "   "},
            {"name": "\t\t"},
            {"email": "noatsign.example.test"},
            {"name": "   ", "email": ""},
        ]
        for kwargs in failing:
            with self.subTest(kwargs=kwargs):
                result = self.list_cross_company(self.db_path, **kwargs)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")

        # 随后按两家公司分别查询，原始内容完整：星河科技为林宁、许禾，
        # 远帆咨询为林宁，编号顺序不变
        xinghe = self.list_company(self.db_path, COMPANY_XINGHE)
        self.assertEqual(xinghe.returncode, 0, xinghe.stderr.decode("utf-8"))
        self.assertEqual(xinghe.stderr, b"")
        self.assertEqual(
            json.loads(xinghe.stdout.decode("utf-8")),
            [lin_ning_xinghe, xu_he],
        )

        yuanfan = self.list_company(self.db_path, COMPANY_YUANFAN)
        self.assertEqual(yuanfan.returncode, 0, yuanfan.stderr.decode("utf-8"))
        self.assertEqual(yuanfan.stderr, b"")
        self.assertEqual(
            json.loads(yuanfan.stdout.decode("utf-8")),
            [lin_ning_yuanfan],
        )

        # 跨公司全量查询仍为同样三条
        self.assert_cross_company_list_success(
            self.db_path, [lin_ning_xinghe, lin_ning_yuanfan, xu_he]
        )

    # ---- 不存在的数据库 ----

    def test_unconditional_list_creates_empty_database(self):
        fresh_db = self.tmpdir / "fresh-cross-company.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 父目录已存在、数据库文件不存在：无条件 list 创建空库并返回 []
        result = self.list_cross_company(fresh_db)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), [])
        self.assertTrue(fresh_db.exists())

        # 再次通过公开命令查询仍为空数组
        again = self.list_cross_company(fresh_db)
        self.assertEqual(again.returncode, 0, again.stderr.decode("utf-8"))
        self.assertEqual(again.stderr, b"")
        self.assertEqual(json.loads(again.stdout.decode("utf-8")), [])

    def test_unconditional_list_csv_on_missing_database_outputs_header_only(self):
        fresh_db = self.tmpdir / "fresh-cross-company-csv.sqlite3"
        self.assertFalse(fresh_db.exists())

        result = self.list_cross_company(fresh_db, fmt="csv")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertTrue(fresh_db.exists())
        # CSV 只输出表头，CRLF 结束
        self.assertEqual(result.stdout.decode("utf-8"), "id,name,email,company\r\n")

        # 再次查询（JSON 与 CSV）仍为空
        again_json = self.list_cross_company(fresh_db)
        self.assertEqual(again_json.returncode, 0, again_json.stderr.decode("utf-8"))
        self.assertEqual(json.loads(again_json.stdout.decode("utf-8")), [])

        again_csv = self.list_cross_company(fresh_db, fmt="csv")
        self.assertEqual(again_csv.returncode, 0, again_csv.stderr.decode("utf-8"))
        self.assertEqual(
            again_csv.stdout.decode("utf-8"), "id,name,email,company\r\n"
        )


if __name__ == "__main__":
    unittest.main()
