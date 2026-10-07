"""crm.py list 子命令 --format csv 输出路径及格式校验的回归测试。

固定样例为两家公司三位合成联系人：
- 星河,科技：林"宁（lin@example.test，姓名含双引号、公司名含逗号）、
  许<换行>禾（xu@example.test，姓名由“许”、一个实际换行符与“禾”组成）
- 远帆咨询：周岚（zhou@example.test）

仅覆盖已有的 CSV 输出及其格式校验边界，不涉及联系人命令、
SQLite 表结构与 JSON 行为的改动。仅使用 Python 3 标准库 unittest，
通过子进程执行 crm.py，所有样例数据放在独立临时目录中，
测试结束后自动清理，重复执行结果一致。
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

COMPANY_XINGHE = "星河,科技"
COMPANY_YUANFAN = "远帆咨询"
NAME_LIN = '林"宁'
NAME_XU = "许\n禾"
NAME_ZHOU = "周岚"
EMAIL_LIN = "lin@example.test"
EMAIL_XU = "xu@example.test"
EMAIL_ZHOU = "zhou@example.test"

FORMAT_ERROR_LINE = "format: must be json or csv"
CSV_HEADER = "id,name,email,company"
CSV_HEADER_LINE = CSV_HEADER + "\r\n"


class ListCsvOutputTestCase(unittest.TestCase):
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

    def list_contacts(self, db_path, company, fmt=None, email=None, name=None):
        cli_args = ["list", "--company", company]
        if fmt is not None:
            cli_args.extend(["--format", fmt])
        if email is not None:
            cli_args.extend(["--email", email])
        if name is not None:
            cli_args.extend(["--name", name])
        return self.run_crm(db_path, *cli_args)

    def assert_add_success(self, name, email, company):
        """新增联系人并断言成功，返回解析后的联系人字典。"""
        result = self.add_contact(self.db_path, name, email, company)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertIsInstance(record["id"], int)
        self.assertEqual(record["name"], name)
        self.assertEqual(record["email"], email)
        self.assertEqual(record["company"], company)
        return record

    def assert_json_list(self, db_path, company, expected, email=None, name=None):
        """以默认 JSON 路径断言公司下的记录（含顺序）与期望完全一致。"""
        result = self.list_contacts(
            db_path, company, fmt="json", email=email, name=name
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected)
        return records

    def parse_csv(self, result):
        """断言成功退出并把标准输出按 CSV 解析为逻辑行列表。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        text = result.stdout.decode("utf-8")
        return text, list(csv.reader(io.StringIO(text)))

    def seed_contacts(self):
        """按验收顺序新增三位联系人，编号严格以新增结果为准。

        星河,科技依次新增林"宁、许<换行>禾；远帆咨询新增周岚。
        """
        lin = self.assert_add_success(NAME_LIN, EMAIL_LIN, COMPANY_XINGHE)
        xu = self.assert_add_success(NAME_XU, EMAIL_XU, COMPANY_XINGHE)
        zhou = self.assert_add_success(NAME_ZHOU, EMAIL_ZHOU, COMPANY_YUANFAN)

        ids = [record["id"] for record in (lin, xu, zhou)]
        self.assertEqual(ids, sorted(ids))
        return lin, xu, zhou

    # ---- CSV 成功输出：表头、范围、顺序、字段 ----

    def test_csv_header_then_only_company_contacts_sorted_by_id(self):
        lin, xu, zhou = self.seed_contacts()

        result = self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="csv")
        text, rows = self.parse_csv(result)

        # 开头恰为表头，随后只含星河,科技两人，远帆咨询的周岚不出现
        self.assertTrue(text.startswith(CSV_HEADER_LINE))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], ["id", "name", "email", "company"])

        data_rows = rows[1:]
        self.assertEqual(
            [int(row[0]) for row in data_rows], [lin["id"], xu["id"]]
        )
        self.assertLess(lin["id"], xu["id"])
        self.assertNotIn(zhou["email"], text)

        for row, record in zip(data_rows, (lin, xu)):
            # 编号是新增编号的十进制文本，其余解析字段与新增记录逐字一致
            self.assertEqual(len(row), 4)
            self.assertEqual(row[0], str(record["id"]))
            self.assertTrue(row[0].isdecimal())
            self.assertEqual(int(row[0]), record["id"])
            self.assertEqual(row[1], record["name"])
            self.assertEqual(row[2], record["email"])
            self.assertEqual(row[3], record["company"])

    def test_csv_quotes_comma_double_quote_and_newline_fields(self):
        lin, xu, _zhou = self.seed_contacts()

        result = self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="csv")
        text, rows = self.parse_csv(result)

        # 整体逐字断言：含逗号/双引号/换行的字段整体加双引号，
        # 字段内双引号写成两个，姓名内部的实际换行原样保留；
        # 输出中没有任何额外提示文字
        expected = (
            CSV_HEADER_LINE
            + f'{lin["id"]},"林""宁",lin@example.test,"星河,科技"\r\n'
            + f'{xu["id"]},"许\n禾",xu@example.test,"星河,科技"\r\n'
        )
        self.assertEqual(text, expected)

        # 表头之外只有两条逻辑联系人记录：姓名内部换行不能拆成多条记录，
        # 换行必须保留在同一字段中
        data_rows = rows[1:]
        self.assertEqual(len(data_rows), 2)
        self.assertEqual(data_rows[0][1], '林"宁')
        self.assertEqual(data_rows[1][1], "许\n禾")
        self.assertIn("\n", data_rows[1][1])
        self.assertEqual(data_rows[1][3], COMPANY_XINGHE)

    def test_csv_and_json_agree_on_range_order_and_text(self):
        lin, xu, zhou = self.seed_contacts()

        for company, expected in (
            (COMPANY_XINGHE, [lin, xu]),
            (COMPANY_YUANFAN, [zhou]),
        ):
            with self.subTest(company=company):
                csv_result = self.list_contacts(self.db_path, company, fmt="csv")
                _text, rows = self.parse_csv(csv_result)
                json_records = self.assert_json_list(self.db_path, company, expected)

                data_rows = rows[1:]
                # 联系人范围与顺序一致
                self.assertEqual(
                    [int(row[0]) for row in data_rows],
                    [record["id"] for record in json_records],
                )
                # 文本字段逐字一致
                for row, record in zip(data_rows, json_records):
                    self.assertEqual(row[0], str(record["id"]))
                    self.assertEqual(row[1], record["name"])
                    self.assertEqual(row[2], record["email"])
                    self.assertEqual(row[3], record["company"])

    def test_csv_with_name_or_email_filters_keeps_existing_semantics(self):
        lin, xu, _zhou = self.seed_contacts()

        # 邮箱精确匹配：xu@example.test 只返回第二位联系人
        result = self.list_contacts(
            self.db_path, COMPANY_XINGHE, fmt="csv", email=EMAIL_XU
        )
        _text, rows = self.parse_csv(result)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ["id", "name", "email", "company"])
        self.assertEqual(rows[1][0], str(xu["id"]))
        self.assertEqual(rows[1][1], NAME_XU)
        self.assertEqual(rows[1][2], EMAIL_XU)

        # lin@example.test 只返回林"宁
        result = self.list_contacts(
            self.db_path, COMPANY_XINGHE, fmt="csv", email=EMAIL_LIN
        )
        _text, rows = self.parse_csv(result)
        self.assertEqual([row[0] for row in rows[1:]], [str(lin["id"])])
        self.assertEqual(rows[1][1], NAME_LIN)

        # 姓名字面子串匹配（区分大小写）：宁、许 分别只命中一人；
        # 以含实际换行的完整姓名作为子串同样只命中第二位
        for name_value, expected_record in (
            ("宁", lin),
            ("许", xu),
            ("禾", xu),
            (NAME_XU, xu),
        ):
            with self.subTest(name=name_value):
                result = self.list_contacts(
                    self.db_path, COMPANY_XINGHE, fmt="csv", name=name_value
                )
                _text, rows = self.parse_csv(result)
                self.assertEqual(
                    [row[0] for row in rows[1:]], [str(expected_record["id"])]
                )

        # 邮箱与姓名叠加：邮箱不匹配时即使姓名子串命中也无记录
        result = self.list_contacts(
            self.db_path,
            COMPANY_XINGHE,
            fmt="csv",
            email=EMAIL_LIN,
            name="许",
        )
        text, rows = self.parse_csv(result)
        self.assertEqual(rows, [["id", "name", "email", "company"]])
        self.assertEqual(text, CSV_HEADER_LINE)

    def test_csv_unknown_company_outputs_header_only(self):
        self.seed_contacts()

        result = self.list_contacts(self.db_path, "不存在的公司", fmt="csv")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        # 无匹配公司时只输出表头一行，无额外提示文字
        self.assertEqual(result.stdout.decode("utf-8"), CSV_HEADER_LINE)

    # ---- --format 校验边界 ----

    def test_invalid_format_is_rejected_with_exit_code_2(self):
        self.seed_contacts()

        for bad_format in ("xml", "CSV"):
            with self.subTest(format=bad_format):
                result = self.list_contacts(
                    self.db_path, COMPANY_XINGHE, fmt=bad_format
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr.decode("utf-8"),
                    FORMAT_ERROR_LINE + "\n",
                )

    def test_invalid_format_reported_even_when_company_empty(self):
        self.seed_contacts()

        # 公司同时为空（空串或纯空白）时仍只报告格式错误：
        # 格式校验先于公司校验
        for bad_format in ("xml", "CSV"):
            for empty_company in ("", "   ", "\t\t", " \t "):
                with self.subTest(format=bad_format, company=empty_company):
                    result = self.list_contacts(
                        self.db_path, empty_company, fmt=bad_format
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, b"")
                    self.assertEqual(
                        result.stderr.decode("utf-8"),
                        FORMAT_ERROR_LINE + "\n",
                    )

    def test_invalid_format_does_not_change_existing_contacts(self):
        lin, xu, zhou = self.seed_contacts()

        for bad_format in ("xml", "CSV"):
            for company in (COMPANY_XINGHE, "", "   "):
                with self.subTest(format=bad_format, company=company):
                    result = self.list_contacts(self.db_path, company, fmt=bad_format)
                    self.assertEqual(result.returncode, 2)

        # 失败校验后重新查询两家公司，记录数量与内容维持初始样例
        self.assert_json_list(self.db_path, COMPANY_XINGHE, [lin, xu])
        self.assert_json_list(self.db_path, COMPANY_YUANFAN, [zhou])

    def test_invalid_format_does_not_create_missing_database(self):
        for index, (bad_format, company) in enumerate(
            (("xml", COMPANY_XINGHE), ("CSV", ""), ("xml", "   "))
        ):
            fresh_db = self.tmpdir / f"csv-fresh-{index}.sqlite3"
            with self.subTest(format=bad_format, company=company):
                self.assertFalse(fresh_db.exists())
                result = self.list_contacts(fresh_db, company, fmt=bad_format)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr.decode("utf-8"), FORMAT_ERROR_LINE + "\n"
                )
                # 父目录存在但数据库文件尚不存在：不能创建文件及任何伴随文件
                self.assertFalse(fresh_db.exists())
                self.assertEqual(
                    list(self.tmpdir.glob(fresh_db.name + "*")), []
                )

    # ---- 默认格式与查询后数据不变 ----

    def test_omitting_format_matches_explicit_json_byte_for_byte(self):
        self.seed_contacts()

        omitted = self.list_contacts(self.db_path, COMPANY_XINGHE)
        explicit = self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="json")

        self.assertEqual(omitted.returncode, 0, omitted.stderr.decode("utf-8"))
        self.assertEqual(explicit.returncode, 0, explicit.stderr.decode("utf-8"))
        self.assertEqual(omitted.stderr, b"")
        self.assertEqual(explicit.stderr, b"")
        # 省略 --format 与显式 json 的输出逐字节一致
        self.assertEqual(omitted.stdout, explicit.stdout)
        records = json.loads(omitted.stdout.decode("utf-8"))
        self.assertEqual([record["email"] for record in records], [EMAIL_LIN, EMAIL_XU])

        # 而 csv 是另一种输出，不应与 JSON 混淆
        csv_result = self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="csv")
        self.assertNotEqual(csv_result.stdout, omitted.stdout)

    def test_successful_and_rejected_queries_leave_seed_data_unchanged(self):
        lin, xu, zhou = self.seed_contacts()

        # 初始样例快照（两家公司各自的记录数量与内容）
        initial_xinghe = self.assert_json_list(
            self.db_path, COMPANY_XINGHE, [lin, xu]
        )
        initial_yuanfan = self.assert_json_list(
            self.db_path, COMPANY_YUANFAN, [zhou]
        )
        self.assertEqual(len(initial_xinghe), 2)
        self.assertEqual(len(initial_yuanfan), 1)

        # 成功的 CSV 查询：命中、叠加邮箱条件、无匹配公司
        successful = [
            (COMPANY_XINGHE, None, None),
            (COMPANY_XINGHE, EMAIL_XU, None),
            ("不存在的公司", None, None),
        ]
        for company, email, name in successful:
            with self.subTest(kind="success", company=company, email=email):
                result = self.list_contacts(
                    self.db_path, company, fmt="csv", email=email, name=name
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))

        # 失败的格式校验：合法公司、空公司、大小写非法值
        for bad_format, company in (
            ("xml", COMPANY_XINGHE),
            ("CSV", COMPANY_XINGHE),
            ("xml", ""),
        ):
            with self.subTest(kind="rejected", format=bad_format, company=company):
                result = self.list_contacts(self.db_path, company, fmt=bad_format)
                self.assertEqual(result.returncode, 2)

        # 重新查询两家公司，记录数量与内容均维持初始样例
        self.assert_json_list(self.db_path, COMPANY_XINGHE, initial_xinghe)
        self.assert_json_list(self.db_path, COMPANY_YUANFAN, initial_yuanfan)


if __name__ == "__main__":
    unittest.main()
