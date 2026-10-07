"""crm.py list 子命令 --format csv 输出路径的回归测试。

固定样例为两家公司三位合成联系人（按此顺序新增，编号以新增结果为准）：
- 星河,科技（公司名含逗号）：林"宁（lin@example.test）、
  许<换行>禾（xu@example.test，姓名第二个与第三个字之间是一个实际换行符）
- 远帆咨询：周岚（zhou@example.test）

仅使用 Python 3 标准库 unittest，通过子进程执行 crm.py，
所有样例数据都放在独立的临时目录中，测试结束后自动清理；
重复执行结果一致，不依赖网络或任何已有客户库。
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
FORMAT_ERROR_LINE = "format: must be json or csv"

# 第二位联系人姓名：许、一个实际换行字符、禾依次组成
XU_HE_NAME = "许\n禾"


class ListCsvFormatTestCase(unittest.TestCase):
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

    def assert_json_list_success(self, db_path, company, expected_records,
                                 email=None, name=None):
        """断言 JSON list 返回的记录（含顺序）与期望完全一致。"""
        result = self.list_contacts(
            db_path, company, fmt="json", email=email, name=name
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertEqual(records, expected_records)
        return records

    def parse_csv(self, raw_text):
        """按 CSV 规则解析标准输出，返回去除末尾空行后的行列表。"""
        return list(csv.reader(io.StringIO(raw_text)))

    def assert_csv_list_success(self, result, expected_records):
        """断言 CSV list 成功：退出码 0、无标准错误，解析行与期望记录一致。

        表头固定为 id,name,email,company；编号是新增编号的十进制文本，
        其余字段与新增记录逐字一致。
        """
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")

        text = result.stdout.decode("utf-8")
        rows = self.parse_csv(text)
        self.assertEqual(
            rows[0], ["id", "name", "email", "company"]
        )
        data_rows = rows[1:]
        self.assertEqual(len(data_rows), len(expected_records))
        for row, record in zip(data_rows, expected_records):
            self.assertEqual(
                row,
                [
                    str(record["id"]),
                    record["name"],
                    record["email"],
                    record["company"],
                ],
            )
        return text, data_rows

    def seed_contacts(self):
        """按验收顺序新增三位联系人，编号以新增结果为准并保持升序。"""
        lin_ning = self.assert_add_success(
            self.add_contact(
                self.db_path, '林"宁', "lin@example.test", COMPANY_XINGHE
            ),
            {"name": '林"宁', "email": "lin@example.test",
             "company": COMPANY_XINGHE},
        )
        xu_he = self.assert_add_success(
            self.add_contact(
                self.db_path, XU_HE_NAME, "xu@example.test", COMPANY_XINGHE
            ),
            {"name": XU_HE_NAME, "email": "xu@example.test",
             "company": COMPANY_XINGHE},
        )
        zhou_lan = self.assert_add_success(
            self.add_contact(
                self.db_path, "周岚", "zhou@example.test", COMPANY_YUANFAN
            ),
            {"name": "周岚", "email": "zhou@example.test",
             "company": COMPANY_YUANFAN},
        )

        ids = [r["id"] for r in (lin_ning, xu_he, zhou_lan)]
        self.assertEqual(ids, sorted(ids))
        return lin_ning, xu_he, zhou_lan

    # ---- 成功 CSV 输出行为 ----

    def test_csv_list_header_and_company_filter_sorted_by_id(self):
        lin_ning, xu_he, zhou_lan = self.seed_contacts()

        result = self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="csv")
        text, rows = self.assert_csv_list_success(result, [lin_ning, xu_he])

        # 输出以表头开头，整体只有表头加该公司两人，按编号升序
        self.assertTrue(text.startswith("id,name,email,company\r\n"))
        self.assertEqual(
            [row[0] for row in rows],
            [str(lin_ning["id"]), str(xu_he["id"])],
        )
        # 远帆咨询的周岚不出现在该公司结果中
        self.assertNotIn(str(zhou_lan["id"]), [row[0] for row in rows])

        # 行以 CRLF 结束且无额外空行或提示文字
        self.assertEqual(
            text.split("\r\n"),
            [
                "id,name,email,company",
                f'{lin_ning["id"]},"林""宁",lin@example.test,"星河,科技"',
                f'{xu_he["id"]},"许\n禾",xu@example.test,"星河,科技"',
                "",
            ],
        )

    def test_csv_quoting_rules_for_comma_quote_and_newline(self):
        lin_ning, xu_he, _zhou_lan = self.seed_contacts()

        result = self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="csv")
        text = result.stdout.decode("utf-8")
        physical_lines = text.split("\r\n")

        # 含逗号、双引号或换行的字段整体加双引号；字段内双引号写成两个
        self.assertEqual(
            physical_lines[1],
            f'{lin_ning["id"]},"林""宁",lin@example.test,"星河,科技"',
        )
        # 姓名内部的换行是裸 LF 且保留在同一字段内；物理行（按 CRLF 切分）
        # 不因该换行而多出联系人记录
        self.assertEqual(
            physical_lines[2],
            f'{xu_he["id"]},"许\n禾",xu@example.test,"星河,科技"',
        )
        rows = self.parse_csv(text)
        self.assertEqual(len(rows), 3)  # 表头 + 两位联系人
        self.assertEqual(rows[2][1], XU_HE_NAME)

    def test_csv_matches_json_range_order_and_text_fields(self):
        lin_ning, xu_he, _zhou_lan = self.seed_contacts()

        csv_result = self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="csv")
        json_result = self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="json")
        self.assertEqual(csv_result.returncode, 0, csv_result.stderr.decode("utf-8"))
        self.assertEqual(json_result.returncode, 0, json_result.stderr.decode("utf-8"))

        json_records = json.loads(json_result.stdout.decode("utf-8"))
        csv_rows = self.parse_csv(csv_result.stdout.decode("utf-8"))[1:]

        # 联系人范围、顺序一致；编号同为十进制文本，文本字段逐字一致
        self.assertEqual(len(csv_rows), len(json_records))
        for row, record in zip(csv_rows, json_records):
            self.assertEqual(row[0], str(record["id"]))
            self.assertEqual(row[1], record["name"])
            self.assertEqual(row[2], record["email"])
            self.assertEqual(row[3], record["company"])
        self.assertEqual(
            [r[0] for r in csv_rows], [str(lin_ning["id"]), str(xu_he["id"])]
        )

    def test_csv_with_email_filter_returns_only_second_contact(self):
        _lin_ning, xu_he, _zhou_lan = self.seed_contacts()

        result = self.list_contacts(
            self.db_path,
            COMPANY_XINGHE,
            fmt="csv",
            email="xu@example.test",
        )
        _text, rows = self.assert_csv_list_success(result, [xu_he])
        self.assertEqual(rows[0], [
            str(xu_he["id"]), XU_HE_NAME, "xu@example.test", COMPANY_XINGHE
        ])

    def test_csv_with_name_filter_uses_existing_substring_semantics(self):
        lin_ning, xu_he, _zhou_lan = self.seed_contacts()

        # --name 禾 只命中姓名内部带换行的许禾；--name 林 只命中林"宁
        result_he = self.list_contacts(
            self.db_path, COMPANY_XINGHE, fmt="csv", name="禾"
        )
        self.assert_csv_list_success(result_he, [xu_he])

        result_lin = self.list_contacts(
            self.db_path, COMPANY_XINGHE, fmt="csv", name="林"
        )
        self.assert_csv_list_success(result_lin, [lin_ning])

    def test_csv_no_match_outputs_header_only(self):
        self.seed_contacts()

        result = self.list_contacts(self.db_path, "无此公司", fmt="csv")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        # 只有表头一行（CRLF 结束），没有任何联系人记录或提示文字
        self.assertEqual(result.stdout.decode("utf-8"), "id,name,email,company\r\n")

    def test_default_format_equals_explicit_json(self):
        self.seed_contacts()

        omitted = self.list_contacts(self.db_path, COMPANY_XINGHE)
        explicit = self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="json")
        self.assertEqual(omitted.returncode, 0, omitted.stderr.decode("utf-8"))
        self.assertEqual(explicit.returncode, 0, explicit.stderr.decode("utf-8"))
        self.assertEqual(omitted.stderr, b"")
        self.assertEqual(explicit.stderr, b"")
        self.assertEqual(omitted.stdout, explicit.stdout)
        records = json.loads(omitted.stdout.decode("utf-8"))
        self.assertEqual({r["company"] for r in records}, {COMPANY_XINGHE})
        self.assertEqual(len(records), 2)

    # ---- 格式校验边界 ----

    def assert_format_rejected(self, result):
        """断言格式校验失败：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), FORMAT_ERROR_LINE + "\n"
        )

    def test_invalid_format_values_are_rejected(self):
        self.seed_contacts()

        for bad_format in ("xml", "CSV"):
            with self.subTest(format=bad_format):
                result = self.list_contacts(
                    self.db_path, COMPANY_XINGHE, fmt=bad_format
                )
                self.assert_format_rejected(result)

    def test_invalid_format_reported_even_when_company_empty(self):
        self.seed_contacts()

        # 格式先于公司校验：同时非法时仍只报告格式错误
        for bad_format in ("xml", "CSV"):
            with self.subTest(format=bad_format):
                result = self.list_contacts(
                    self.db_path, "", fmt=bad_format
                )
                self.assert_format_rejected(result)

    # ---- 失败与查询对数据、文件的影响 ----

    def test_format_failure_does_not_create_missing_database(self):
        for index, bad_format in enumerate(("xml", "CSV")):
            fresh_db = self.tmpdir / f"list-csv-fresh-{index}.sqlite3"
            with self.subTest(format=bad_format):
                self.assertFalse(fresh_db.exists())
                # 公司合法与公司为空两种情形都在校验阶段失败
                self.assert_format_rejected(
                    self.list_contacts(fresh_db, COMPANY_XINGHE, fmt=bad_format)
                )
                self.assert_format_rejected(
                    self.list_contacts(fresh_db, "", fmt=bad_format)
                )
                # 数据库文件及任何 SQLite 伴随文件都不应被创建
                self.assertFalse(fresh_db.exists())
                self.assertEqual(
                    list(self.tmpdir.glob(fresh_db.name + "*")), []
                )

    def test_queries_and_validation_failures_leave_records_unchanged(self):
        lin_ning, xu_he, zhou_lan = self.seed_contacts()

        # 成功 CSV 查询：命中、无命中、叠加邮箱条件
        successful = [
            self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="csv"),
            self.list_contacts(self.db_path, "无此公司", fmt="csv"),
            self.list_contacts(
                self.db_path, COMPANY_XINGHE, fmt="csv",
                email="xu@example.test",
            ),
        ]
        for result in successful:
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))

        # 失败的格式校验：非法格式本身以及与空公司叠加
        rejected = [
            self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="xml"),
            self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="CSV"),
            self.list_contacts(self.db_path, "", fmt="xml"),
            self.list_contacts(self.db_path, "", fmt="CSV"),
        ]
        for result in rejected:
            self.assert_format_rejected(result)

        # 重新查询两家公司（JSON 与 CSV）：记录数量与内容维持初始样例
        self.assert_json_list_success(
            self.db_path, COMPANY_XINGHE, [lin_ning, xu_he]
        )
        self.assert_json_list_success(
            self.db_path, COMPANY_YUANFAN, [zhou_lan]
        )
        self.assert_csv_list_success(
            self.list_contacts(self.db_path, COMPANY_XINGHE, fmt="csv"),
            [lin_ning, xu_he],
        )
        self.assert_csv_list_success(
            self.list_contacts(self.db_path, COMPANY_YUANFAN, fmt="csv"),
            [zhou_lan],
        )


if __name__ == "__main__":
    unittest.main()
